#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

REMOTE="${RCLONE_REMOTE:-gdrive}"
DIR="${RCLONE_DIR:-NotebookLM}"
OUT="${MAPS_OUT_DIR:-data}"
BASE="${MAPS_OUT_BASENAME:-mis_lugares_sin_gluten}"

if ! command -v rclone >/dev/null 2>&1; then
  echo "Falta rclone. Instálalo con: brew install rclone" >&2
  exit 1
fi

for ext in md jsonl; do
  file="$OUT/$BASE.$ext"
  if [ -f "$file" ]; then
    rclone copyto "$file" "$REMOTE:$DIR/$BASE.$ext"
    echo "Subido: $file -> $REMOTE:$DIR/$BASE.$ext"
  fi
done
