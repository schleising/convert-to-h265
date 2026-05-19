#!/bin/bash

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$COMMON_DIR/../.." && pwd)"

LABEL="com.schleising.convert-to-h265.converter"
APP_SUPPORT_DIR="$HOME/Library/Application Support/convert-to-h265"
INSTALL_STATE_PATH="$APP_SUPPORT_DIR/install.env"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
DEFAULT_PLIST_DEST="$LAUNCH_AGENTS_DIR/$LABEL.plist"
DEFAULT_CONFIG_DEST="$APP_SUPPORT_DIR/config.toml"
DEFAULT_ENV_DEST="$APP_SUPPORT_DIR/converter.env"
DEFAULT_LOG_DIR="$HOME/Library/Logs/convert-to-h265"
DEFAULT_WORK_DIR="/tmp/Movies/convert-to-h265-work"
DEFAULT_BIN_DIR="$HOME/.local/bin"
DEFAULT_INSTALLED_SCRIPTS_DIR="$APP_SUPPORT_DIR/bin"
DEFAULT_RUNTIME_ROOT="$APP_SUPPORT_DIR/runtime"
DEFAULT_ZSHRC_PATH="$HOME/.zshrc"
PATH_BLOCK_START="# >>> convert-to-h265 helpers >>>"
PATH_BLOCK_END="# <<< convert-to-h265 helpers <<<"

resolve_script_dir() {
    local source_path="$1"

    while [ -L "$source_path" ]; do
        local source_dir
        source_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
        source_path="$(readlink "$source_path")"
        case "$source_path" in
            /*) ;;
            *) source_path="$source_dir/$source_path" ;;
        esac
    done

    cd -P "$(dirname "$source_path")" && pwd
}

load_install_state() {
    if [ -f "$INSTALL_STATE_PATH" ]; then
        # shellcheck disable=SC1090
        source "$INSTALL_STATE_PATH"
    fi

    BIN_DIR="${BIN_DIR:-$DEFAULT_BIN_DIR}"
    INSTALLED_SCRIPTS_DIR="${INSTALLED_SCRIPTS_DIR:-$DEFAULT_INSTALLED_SCRIPTS_DIR}"
    PLIST_DEST="${PLIST_DEST:-$DEFAULT_PLIST_DEST}"
    CONFIG_DEST="${CONFIG_DEST:-$DEFAULT_CONFIG_DEST}"
    ENV_DEST="${ENV_DEST:-$DEFAULT_ENV_DEST}"
    LOG_DIR="${LOG_DIR:-$DEFAULT_LOG_DIR}"
    WORK_DIR="${WORK_DIR:-$DEFAULT_WORK_DIR}"
    RUNTIME_ROOT="${RUNTIME_ROOT:-$DEFAULT_RUNTIME_ROOT}"
    RUNTIME_VENV_DIR="${RUNTIME_VENV_DIR:-$RUNTIME_ROOT/.venv}"
    ZSHRC_PATH="${ZSHRC_PATH:-$DEFAULT_ZSHRC_PATH}"
}

launchctl_domain() {
    printf 'gui/%s\n' "$(id -u)"
}

launchctl_target() {
    printf '%s/%s\n' "$(launchctl_domain)" "$LABEL"
}

service_is_loaded() {
    launchctl print "$(launchctl_target)" >/dev/null 2>&1
}

ensure_zsh_path_block() {
    local zshrc_path="$1"
    local bin_dir="$2"

    touch "$zshrc_path"

    if grep -Fq "$PATH_BLOCK_START" "$zshrc_path"; then
        return
    fi

    {
        printf '\n%s\n' "$PATH_BLOCK_START"
        printf 'if [[ ":$PATH:" != *":%s:"* ]]; then\n' "$bin_dir"
        printf '    export PATH="%s:$PATH"\n' "$bin_dir"
        printf 'fi\n'
        printf '%s\n' "$PATH_BLOCK_END"
    } >> "$zshrc_path"
}

remove_zsh_path_block() {
    local zshrc_path="$1"

    if [ ! -f "$zshrc_path" ]; then
        return
    fi

    /usr/bin/awk -v start="$PATH_BLOCK_START" -v end="$PATH_BLOCK_END" '
        $0 == start { skip=1; next }
        $0 == end { skip=0; next }
        !skip { print }
    ' "$zshrc_path" > "$zshrc_path.tmp"

    mv "$zshrc_path.tmp" "$zshrc_path"
}