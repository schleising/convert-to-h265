#!/usr/bin/env bash
# Upgrade git dependency tags, the uv lock, .venv, and per-service requirements files.
#
# Usage (from repo root):
#   ./update_dependencies.sh
#   ./update_dependencies.sh --dry-run

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$ROOT/scripts/update_dependencies.py" "$@"
