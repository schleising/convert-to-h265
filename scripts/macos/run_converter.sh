#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

load_install_state

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if [ -f "$ENV_DEST" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_DEST"
    set +a
fi

export FOLDER_WALKER="FALSE"
export CONVERTER_CONFIG_PATH="${CONVERTER_CONFIG_PATH:-$CONFIG_DEST}"
export BACKEND_NAME="${BACKEND_NAME:-$(scutil --get LocalHostName 2>/dev/null || hostname)}"

mkdir -p "$WORK_DIR" "$LOG_DIR"

if [ -n "${PYTHON_BIN:-}" ] && [ -x "$PYTHON_BIN" ]; then
    :
elif [ -x "$RUNTIME_VENV_DIR/bin/python" ]; then
    PYTHON_BIN="$RUNTIME_VENV_DIR/bin/python"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "python3 is required but was not found" >&2
    exit 1
fi

required_vars=(DB_URL DB_NAME DB_COLLECTION PUSH_COLLECTION)
for required_var in "${required_vars[@]}"; do
    if [ -z "${!required_var:-}" ]; then
        echo "$required_var must be set in $ENV_DEST or the environment" >&2
        exit 1
    fi
done

if [ -d "$RUNTIME_ROOT/src" ]; then
    cd "$RUNTIME_ROOT"
    exec "$PYTHON_BIN" "$RUNTIME_ROOT/src/main.py"
fi

cd "$REPO_ROOT"
exec "$PYTHON_BIN" "$REPO_ROOT/src/main.py"