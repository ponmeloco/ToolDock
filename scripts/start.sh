#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CLEAN_FIRST=0
NO_BUILD=0

usage() {
  cat <<'EOF'
Usage: scripts/start.sh [--clean] [--no-build]

Options:
  --clean     Remove runtime leftovers before startup.
  --no-build  Start without rebuilding images.
  -h, --help  Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clean)
      CLEAN_FIRST=1
      shift
      ;;
    --no-build)
      NO_BUILD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[start] created .env from .env.example"
fi

CORE_PORT="${CORE_PORT:-}"
MANAGER_PORT="${MANAGER_PORT:-}"
if [[ -f .env ]]; then
  while IFS='=' read -r key value; do
    case "$key" in
      CORE_PORT) [[ -n "$CORE_PORT" ]] || CORE_PORT="${value:-}" ;;
      MANAGER_PORT) [[ -n "$MANAGER_PORT" ]] || MANAGER_PORT="${value:-}" ;;
    esac
  done < <(grep -E '^(CORE_PORT|MANAGER_PORT)=' .env || true)
fi
CORE_PORT="${CORE_PORT:-8000}"
MANAGER_PORT="${MANAGER_PORT:-8001}"

mkdir -p .tooldock-data/tools .tooldock-data/venvs .tooldock-data/secrets .tooldock-data/workers .tooldock-data/namespaces

if [[ "$CLEAN_FIRST" -eq 1 ]]; then
  bash scripts/clean.sh
fi

echo "[start] starting containers"
if [[ "$NO_BUILD" -eq 1 ]]; then
  docker compose up -d
else
  docker compose up --build -d
fi

wait_for_healthy() {
  local service="$1"
  local timeout="$2"
  local line

  for ((i=1; i<=timeout; i++)); do
    line="$(docker compose ps "$service" | sed -n '2p')"
    if [[ "$line" == *"(healthy)"* ]]; then
      echo "[start] ${service} is healthy"
      return 0
    fi
    sleep 1
  done

  echo "[start] timeout waiting for ${service} health" >&2
  docker compose ps >&2
  return 1
}

wait_for_healthy "tooldock-core" 90
wait_for_healthy "tooldock-manager" 90

echo "[start] ready"
echo "[start] core:    http://localhost:${CORE_PORT}"
echo "[start] manager: http://localhost:${MANAGER_PORT}"
