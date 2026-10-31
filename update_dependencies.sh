#!/usr/bin/env bash
# Upgrade every dependency: git tags, the uv lock, .venv, and per-service requirements.
#
# Usage (from repo root):
#   ./update_dependencies.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$ROOT/scripts/update_dependencies.py" "$@"
