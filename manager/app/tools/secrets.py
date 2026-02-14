from __future__ import annotations

from typing import Any

from app.config import ManagerSettings
from app.tools.secrets_store import ManagerSecretsStore


class SecretTools:
    def __init__(self, settings: ManagerSettings):
        self._store = ManagerSecretsStore(settings)

    def prepare_secret(self, key: str, namespace: str | None = None) -> dict[str, Any]:
        return self._store.prepare_secret(key, namespace=namespace)

    def list_secrets(self, namespace: str | None = None) -> list[dict[str, Any]]:
        statuses = self._store.list_status(namespace=namespace)
        return [{"key": item.key, "scope": item.scope, "status": item.status} for item in statuses]

    def remove_secret(self, key: str, namespace: str | None = None) -> dict[str, Any]:
        return self._store.remove_secret(key, namespace=namespace)

    def check_secrets(self, namespace: str) -> dict[str, Any]:
        return self._store.check_namespace(namespace)
