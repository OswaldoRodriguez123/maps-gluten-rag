#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x .venv/bin/python ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

"$PY" -m maps_gluten run "$@"

if [ "${MAPS_SYNC_DRIVE:-0}" = "1" ]; then
  ./scripts/sync_drive.sh
fi
