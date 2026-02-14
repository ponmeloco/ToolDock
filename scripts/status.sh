#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SHOW_LOGS=0
TAIL_LINES=80

usage() {
  cat <<'EOF'
Usage: scripts/status.sh [--logs] [--tail N]

Options:
  --logs     Include recent logs from both services.
  --tail N   Number of log lines when --logs is used (default: 80).
  -h, --help Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --logs)
      SHOW_LOGS=1
      shift
      ;;
    --tail)
      TAIL_LINES="${2:-}"
      if [[ -z "${TAIL_LINES}" || ! "${TAIL_LINES}" =~ ^[0-9]+$ ]]; then
        echo "Invalid --tail value: ${2:-<missing>}" >&2
        exit 1
      fi
      shift 2
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

echo "[status] docker compose ps"
docker compose ps

running_services="$(docker compose ps --services --status running || true)"

echo
echo "[status] core health"
if grep -qx "tooldock-core" <<<"$running_services"; then
  docker compose exec -T tooldock-core python - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://localhost:8000/health", timeout=3) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    print(resp.status, data)
PY
else
  echo "tooldock-core is not running"
fi

echo
echo "[status] manager health"
if grep -qx "tooldock-manager" <<<"$running_services"; then
  docker compose exec -T tooldock-manager python - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://localhost:8001/health", timeout=3) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    print(resp.status, data)
PY
else
  echo "tooldock-manager is not running"
fi

if [[ "$SHOW_LOGS" -eq 1 ]]; then
  echo
  echo "[status] recent logs"
  docker compose logs --no-color --tail="$TAIL_LINES" tooldock-core tooldock-manager
fi
