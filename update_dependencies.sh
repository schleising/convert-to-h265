#!/usr/bin/env bash
# Upgrade every dependency: pyproject.toml, git tags, the uv lock, .venv, and requirements.
#
# Usage (from repo root):
#   ./update_dependencies.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$ROOT/scripts/update_dependencies.py" "$@"
