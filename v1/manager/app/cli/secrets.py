from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from app.config import get_settings
from app.tools.secrets_store import ManagerSecretsStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli.secrets")
    sub = parser.add_subparsers(dest="command", required=True)

    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("--key", required=True)
    set_cmd.add_argument("--scope", default="global")

    edit_cmd = sub.add_parser("edit")
    edit_cmd.add_argument("--editor", default="")

    args = parser.parse_args()

    settings = get_settings()
    store = ManagerSecretsStore(settings)

    if args.command == "set":
        _cmd_set(store, args.key, args.scope)
    elif args.command == "edit":
        _cmd_edit(store, args.editor)


def _cmd_set(store: ManagerSecretsStore, key: str, scope: str) -> None:
    value = getpass.getpass(prompt=f"Value for {key}: ").strip()
    if not value:
        raise SystemExit("Empty value is not allowed")

    namespace = None if scope == "global" else scope
    result = store.set_secret(key=key, value=value, namespace=namespace)
    print(yaml.safe_dump(result, sort_keys=False).strip())


def _cmd_edit(store: ManagerSecretsStore, editor_override: str) -> None:
    with store.lock():
        payload = store.load_payload()
        meta = store.load_meta()

        tmp_parent = Path("/dev/shm") if Path("/dev/shm").exists() else Path("/tmp")
        fd, tmp_path_raw = tempfile.mkstemp(prefix="tooldock-secrets-", suffix=".yaml", dir=str(tmp_parent))
        tmp_path = Path(tmp_path_raw)
        os.close(fd)
        os.chmod(tmp_path, 0o600)

        tmp_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

        editor = editor_override or os.environ.get("EDITOR") or "vi"
        subprocess.run([editor, str(tmp_path)], check=True)

        updated = yaml.safe_load(tmp_path.read_text(encoding="utf-8")) or {}
        if not isinstance(updated, dict):
            raise SystemExit("Edited file must be a YAML object")

        _sync_meta_with_payload(meta, updated)
        store.save(updated, meta)
        tmp_path.unlink(missing_ok=True)

    print("Secrets updated")


def _sync_meta_with_payload(meta: dict, payload: dict) -> None:
    meta.setdefault("global", {})
    meta.setdefault("namespaces", {})
    payload.setdefault("global", {})
    payload.setdefault("namespaces", {})

    for key in payload["global"]:
        meta["global"][key] = {"status": "set"}

    for ns, entries in payload["namespaces"].items():
        ns_meta = meta["namespaces"].setdefault(ns, {})
        for key in entries:
            ns_meta[key] = {"status": "set"}


if __name__ == "__main__":
    main()
