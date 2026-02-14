from __future__ import annotations

import base64
import json
import os
import secrets as pysecrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import CoreSettings


@dataclass(slots=True)
class SecretStatus:
    key: str
    scope: str
    status: str


class SecretsStore:
    def __init__(self, settings: CoreSettings):
        self._settings = settings
        data_dir = Path(settings.data_dir)
        self._tools_dir = data_dir / "tools"
        self._enc_path = data_dir / "secrets.enc"
        self._meta_path = data_dir / "secrets.meta.yaml"

        self._global_values: dict[str, str] = {}
        self._namespace_values: dict[str, dict[str, str]] = {}
        self._meta: dict[str, Any] = {"global": {}, "namespaces": {}}

    def load(self) -> None:
        self._meta = _read_yaml_file(self._meta_path, default={"global": {}, "namespaces": {}})

        payload = self._read_payload()
        self._global_values = {
            str(k): str(v) for k, v in (payload.get("global") or {}).items() if v is not None
        }

        namespaces: dict[str, dict[str, str]] = {}
        for ns, data in (payload.get("namespaces") or {}).items():
            if not isinstance(data, dict):
                continue
            namespaces[str(ns)] = {str(k): str(v) for k, v in data.items() if v is not None}
        self._namespace_values = namespaces

    def get_env(self, namespace: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self._global_values)
        env.update(self._namespace_values.get(namespace, {}))
        env.update(self._namespace_defaults(namespace))
        return env

    def list_status(self, namespace: str | None = None) -> list[SecretStatus]:
        out: list[SecretStatus] = []

        global_meta = self._meta.get("global") or {}
        if namespace is None:
            for key, entry in global_meta.items():
                out.append(SecretStatus(key=str(key), scope="global", status=_meta_status(entry)))

        namespaces_meta = self._meta.get("namespaces") or {}
        for ns_name, meta in namespaces_meta.items():
            if namespace is not None and ns_name != namespace:
                continue
            for key, entry in (meta or {}).items():
                out.append(SecretStatus(key=str(key), scope=str(ns_name), status=_meta_status(entry)))

        return out

    def check_namespace_requirements(self, namespace: str) -> dict[str, list[str]]:
        required = self._required_secrets(namespace)
        satisfied: list[str] = []
        missing: list[str] = []
        placeholders: list[str] = []

        for key in required:
            status = self._secret_status(namespace, key)
            if status == "set":
                satisfied.append(key)
            elif status == "placeholder":
                placeholders.append(key)
            else:
                missing.append(key)

        return {
            "namespace": namespace,
            "satisfied": satisfied,
            "missing": missing,
            "placeholders": placeholders,
        }

    def _secret_status(self, namespace: str, key: str) -> str:
        if key in self._namespace_values.get(namespace, {}):
            return "set"
        if key in self._global_values:
            return "set"

        namespaces_meta = (self._meta.get("namespaces") or {}).get(namespace) or {}
        if key in namespaces_meta:
            return _meta_status(namespaces_meta[key])

        global_meta = self._meta.get("global") or {}
        if key in global_meta:
            return _meta_status(global_meta[key])
        return "missing"

    def _required_secrets(self, namespace: str) -> list[str]:
        config_path = self._tools_dir / namespace / "tooldock.yaml"
        if not config_path.exists():
            return []
        data = _read_yaml_file(config_path, default={})
        raw = data.get("secrets") or []
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if item]

    def _namespace_defaults(self, namespace: str) -> dict[str, str]:
        config_path = self._tools_dir / namespace / "tooldock.yaml"
        if not config_path.exists():
            return {}
        data = _read_yaml_file(config_path, default={})
        env = data.get("env") or {}
        if not isinstance(env, dict):
            return {}
        return {str(k): str(v) for k, v in env.items() if v is not None}

    def _read_payload(self) -> dict[str, Any]:
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


def encrypt_payload(payload: dict[str, Any], secrets_key: str) -> str:
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


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


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
