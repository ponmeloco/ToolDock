from __future__ import annotations

import base64
import fcntl
import json
import secrets as pysecrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import ManagerSettings
from app.tools.common import data_paths


@dataclass(slots=True)
class SecretStatus:
    key: str
    scope: str
    status: str


class ManagerSecretsStore:
    def __init__(self, settings: ManagerSettings):
        self._settings = settings
        paths = data_paths(settings)
        self._meta_path = paths["meta"]
        self._enc_path = paths["enc"]
        self._lock_path = paths["lock"]
        self._tools_dir = paths["tools"]

        self._meta_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self):
        self._lock_path.touch(exist_ok=True)
        with self._lock_path.open("r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def load_meta(self) -> dict[str, Any]:
        return _read_yaml_file(self._meta_path, default={"global": {}, "namespaces": {}})

    def load_payload(self) -> dict[str, Any]:
        if not self._enc_path.exists():
            return {"global": {}, "namespaces": {}}

        raw = self._enc_path.read_text(encoding="utf-8")
        key = self._settings.secrets_key
        if key:
            envelope = json.loads(raw)
            return _decrypt_envelope(envelope, key)

        if not self._settings.allow_insecure_secrets:
            raise RuntimeError("SECRETS_KEY is required unless ALLOW_INSECURE_SECRETS=1")

        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            return {"global": {}, "namespaces": {}}
        return data

    def save(self, payload: dict[str, Any], meta: dict[str, Any]) -> None:
        self._meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")

        key = self._settings.secrets_key
        if key:
            wire = _encrypt_payload(payload, key)
            self._enc_path.write_text(wire, encoding="utf-8")
            return

        if not self._settings.allow_insecure_secrets:
            raise RuntimeError("SECRETS_KEY is required unless ALLOW_INSECURE_SECRETS=1")

        self._enc_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def prepare_secret(self, key: str, namespace: str | None = None) -> dict[str, Any]:
        with self.lock():
            payload = self.load_payload()
            meta = self.load_meta()
            _ensure_meta_shape(meta)
            _ensure_payload_shape(payload)

            if namespace:
                ns_meta = meta["namespaces"].setdefault(namespace, {})
                ns_meta[key] = {"status": "placeholder"}
            else:
                meta["global"][key] = {"status": "placeholder"}

            self.save(payload, meta)

        scope = namespace or "global"
        return {
            "key": key,
            "scope": scope,
            "meta_file": str(self._meta_path),
            "instructions": f"Run: docker compose exec tooldock-manager python -m app.cli.secrets set --key {key} --scope {scope}",
        }

    def set_secret(self, key: str, value: str, namespace: str | None = None) -> dict[str, Any]:
        with self.lock():
            payload = self.load_payload()
            meta = self.load_meta()
            _ensure_meta_shape(meta)
            _ensure_payload_shape(payload)

            if namespace:
                ns_values = payload["namespaces"].setdefault(namespace, {})
                ns_values[key] = value
                ns_meta = meta["namespaces"].setdefault(namespace, {})
                ns_meta[key] = {"status": "set"}
                scope = namespace
            else:
                payload["global"][key] = value
                meta["global"][key] = {"status": "set"}
                scope = "global"

            self.save(payload, meta)

        return {"updated": True, "key": key, "scope": scope}

    def remove_secret(self, key: str, namespace: str | None = None) -> dict[str, Any]:
        with self.lock():
            payload = self.load_payload()
            meta = self.load_meta()
            _ensure_meta_shape(meta)
            _ensure_payload_shape(payload)

            if namespace:
                payload["namespaces"].setdefault(namespace, {}).pop(key, None)
                meta["namespaces"].setdefault(namespace, {}).pop(key, None)
                scope = namespace
            else:
                payload["global"].pop(key, None)
                meta["global"].pop(key, None)
                scope = "global"

            self.save(payload, meta)

        return {"removed": True, "key": key, "scope": scope}

    def list_status(self, namespace: str | None = None) -> list[SecretStatus]:
        meta = self.load_meta()
        _ensure_meta_shape(meta)

        out: list[SecretStatus] = []
        if namespace is None:
            for key, entry in meta["global"].items():
                out.append(SecretStatus(key=key, scope="global", status=_meta_status(entry)))

        for ns, entries in meta["namespaces"].items():
            if namespace is not None and ns != namespace:
                continue
            for key, entry in entries.items():
                out.append(SecretStatus(key=key, scope=ns, status=_meta_status(entry)))

        return out

    def check_namespace(self, namespace: str) -> dict[str, Any]:
        required = _required_secrets(self._tools_dir / namespace / "tooldock.yaml")

        payload = self.load_payload()
        meta = self.load_meta()
        _ensure_meta_shape(meta)
        _ensure_payload_shape(payload)

        globals_values = payload.get("global", {})
        ns_values = payload.get("namespaces", {}).get(namespace, {})
        global_meta = meta.get("global", {})
        ns_meta = meta.get("namespaces", {}).get(namespace, {})

        satisfied: list[str] = []
        missing: list[str] = []
        placeholders: list[str] = []

        for key in required:
            if key in ns_values or key in globals_values:
                satisfied.append(key)
                continue

            status = "missing"
            if key in ns_meta:
                status = _meta_status(ns_meta[key])
            elif key in global_meta:
                status = _meta_status(global_meta[key])

            if status == "placeholder":
                placeholders.append(key)
            elif status == "set":
                satisfied.append(key)
            else:
                missing.append(key)

        return {
            "namespace": namespace,
            "satisfied": satisfied,
            "missing": missing,
            "placeholders": placeholders,
        }


def _required_secrets(path: Path) -> list[str]:
    if not path.exists():
        return []
    data = _read_yaml_file(path, default={})
    raw = data.get("secrets") or []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def _ensure_meta_shape(meta: dict[str, Any]) -> None:
    meta.setdefault("global", {})
    meta.setdefault("namespaces", {})


def _ensure_payload_shape(payload: dict[str, Any]) -> None:
    payload.setdefault("global", {})
    payload.setdefault("namespaces", {})


def _read_yaml_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return default
    return data


def _meta_status(entry: Any) -> str:
    if isinstance(entry, dict):
        status = str(entry.get("status", "")).strip()
        if status in {"set", "placeholder", "missing"}:
            return status
    if isinstance(entry, str) and entry in {"set", "placeholder", "missing"}:
        return entry
    return "missing"


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _encrypt_payload(payload: dict[str, Any], secrets_key: str) -> str:
    salt = pysecrets.token_bytes(16)
    key = _derive_fernet_key(secrets_key, salt)
    fernet = Fernet(key)
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ciphertext = fernet.encrypt(plaintext)
    envelope = {
        "version": 1,
        "kdf": "pbkdf2-sha256",
        "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
        "ciphertext": ciphertext.decode("ascii"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(envelope, separators=(",", ":"))


def _decrypt_envelope(envelope: dict[str, Any], secrets_key: str) -> dict[str, Any]:
    salt_b64 = str(envelope.get("salt") or "")
    ciphertext = str(envelope.get("ciphertext") or "")
    if not salt_b64 or not ciphertext:
        return {"global": {}, "namespaces": {}}

    salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
    key = _derive_fernet_key(secrets_key, salt)
    fernet = Fernet(key)
    try:
        plaintext = fernet.decrypt(ciphertext.encode("ascii"))
    except InvalidToken as exc:
        raise RuntimeError("Unable to decrypt secrets.enc with provided SECRETS_KEY") from exc

    data = json.loads(plaintext.decode("utf-8"))
    if not isinstance(data, dict):
        return {"global": {}, "namespaces": {}}
    return data
