#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REMOVE_VOLUMES=0
REMOVE_IMAGES=0

usage() {
  cat <<'EOF'
Usage: scripts/stop.sh [--volumes] [--rmi]

Options:
  --volumes  Also remove compose volumes.
  --rmi      Also remove images built by compose.
  -h, --help Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --volumes)
      REMOVE_VOLUMES=1
      shift
      ;;
    --rmi)
      REMOVE_IMAGES=1
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

cmd=(docker compose down --remove-orphans)
if [[ "$REMOVE_VOLUMES" -eq 1 ]]; then
  cmd+=(--volumes)
fi
if [[ "$REMOVE_IMAGES" -eq 1 ]]; then
  cmd+=(--rmi local)
fi

echo "[stop] stopping stack"
"${cmd[@]}"
echo "[stop] done"
