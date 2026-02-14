from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.registry.loader import load_tools_from_file
from app.registry.models import NamespaceInfo

_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_RESERVED = {"_system"}


def scan_namespaces(tools_dir: Path) -> dict[str, NamespaceInfo]:
    namespaces: dict[str, NamespaceInfo] = {}
    if not tools_dir.exists():
        return namespaces

    for entry in sorted(tools_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.name in _RESERVED:
            continue
        if not _NAMESPACE_RE.match(entry.name):
            continue

        ns = NamespaceInfo(name=entry.name, path=entry)
        req = entry / "requirements.txt"
        if req.exists():
            ns.requirements_path = req
            ns.requirements_hash = _file_sha256(req)

        cfg = entry / "tooldock.yaml"
        if cfg.exists():
            ns.config_path = cfg

        for py_file in sorted(entry.glob("*.py"), key=lambda p: p.name):
            ns.tools.extend(load_tools_from_file(entry.name, py_file))

        namespaces[entry.name] = ns

    return namespaces


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
