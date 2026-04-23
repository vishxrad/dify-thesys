#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="$ROOT_DIR/local-plugins/thesys"
DIST_DIR="$ROOT_DIR/local-plugins/dist"
OUTPUT_PATH="${1:-$DIST_DIR/thesys-0.1.0.difypkg}"

mkdir -p "$DIST_DIR"

python3 - "$PLUGIN_DIR" "$OUTPUT_PATH" <<'PY'
from pathlib import Path
import sys
import zipfile

plugin_dir = Path(sys.argv[1]).resolve()
output_path = Path(sys.argv[2]).resolve()

excluded_parts = {".venv", "__pycache__", ".pytest_cache"}
excluded_suffixes = {".pyc"}

with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(plugin_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        if path.suffix in excluded_suffixes:
            continue
        archive.write(path, path.relative_to(plugin_dir).as_posix())
PY

printf 'Created %s\n' "$OUTPUT_PATH"
