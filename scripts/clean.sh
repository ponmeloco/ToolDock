#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p .tooldock-data/tools .tooldock-data/venvs .tooldock-data/secrets .tooldock-data/workers .tooldock-data/namespaces

echo "[clean] stopping compose stack"
docker compose down --remove-orphans >/dev/null 2>&1 || true

echo "[clean] clearing runtime data (container-owned)"
docker compose run --rm --entrypoint sh tooldock-core -c \
  "rm -rf /data/tools/* /data/venvs/* /data/secrets/* /data/workers/* /data/namespaces/*" \
  >/dev/null 2>&1 || true

echo "[clean] clearing runtime data (host-owned)"
find .tooldock-data -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
mkdir -p .tooldock-data/tools .tooldock-data/venvs .tooldock-data/secrets .tooldock-data/workers .tooldock-data/namespaces

echo "[clean] removing test/build caches"
rm -rf .pytest_cache
find core manager tests -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true

echo "[clean] done"
