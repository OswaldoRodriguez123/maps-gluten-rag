#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAME="com.mapsgluten.scraper.plist"
TEMPLATE="$PROJECT_DIR/launchd/$NAME.template"
TARGET="$HOME/Library/LaunchAgents/$NAME"

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

python3 - "$PROJECT_DIR" "$TEMPLATE" "$TARGET" <<'PY'
import pathlib
import sys

project, template, target = sys.argv[1:4]
content = pathlib.Path(template).read_text(encoding="utf-8")
pathlib.Path(target).write_text(content.replace("__PROJECT_DIR__", project), encoding="utf-8")
PY

launchctl bootout "gui/$(id -u)" "$TARGET" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"

echo "Instalado en $TARGET"
echo "Prueba ahora: launchctl kickstart -k gui/$(id -u)/com.mapsgluten.scraper"
