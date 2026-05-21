#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This installer only supports macOS." >&2
    exit 1
fi

load_install_state

mkdir -p "$APP_SUPPORT_DIR" "$LAUNCH_AGENTS_DIR" "$LOG_DIR" "$WORK_DIR" "$INSTALLED_SCRIPTS_DIR" "$RUNTIME_ROOT"

mkdir -p "$BIN_DIR"

if [ ! -w "$BIN_DIR" ]; then
    echo "$BIN_DIR is not writable. Choose a writable user bin directory." >&2
    exit 1
fi

if [ ! -w "$WORK_DIR" ]; then
    echo "Working directory $WORK_DIR is not writable." >&2
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON_BIN="$(command -v python3)"
else
    echo "python3 is required but was not found." >&2
    exit 1
fi

sync_runtime_tree() {
    mkdir -p "$RUNTIME_ROOT/src"
    /usr/bin/rsync -a --delete --exclude '__pycache__' "$REPO_ROOT/src/" "$RUNTIME_ROOT/src/"
}

install_runtime_scripts() {
    local script_name
    for script_name in common.sh run_converter.sh start_converter stop_converter restart_converter status_converter uninstall_converter; do
        cp "$SCRIPT_DIR/$script_name" "$INSTALLED_SCRIPTS_DIR/$script_name"
    done

    chmod +x \
        "$INSTALLED_SCRIPTS_DIR/run_converter.sh" \
        "$INSTALLED_SCRIPTS_DIR/start_converter" \
        "$INSTALLED_SCRIPTS_DIR/stop_converter" \
        "$INSTALLED_SCRIPTS_DIR/restart_converter" \
        "$INSTALLED_SCRIPTS_DIR/status_converter" \
        "$INSTALLED_SCRIPTS_DIR/uninstall_converter"
}

sync_runtime_tree
install_runtime_scripts

if [ ! -x "$RUNTIME_VENV_DIR/bin/python" ]; then
    "$BOOTSTRAP_PYTHON_BIN" -m venv "$RUNTIME_VENV_DIR"
fi

PYTHON_BIN="$RUNTIME_VENV_DIR/bin/python"
"$PYTHON_BIN" -m pip install -r "$REPO_ROOT/backend/requirements.txt"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg is required but was not found on PATH." >&2
    exit 1
fi

if ! ffmpeg -hide_banner -encoders 2>/dev/null | grep -q "hevc_videotoolbox"; then
    echo "ffmpeg does not support hevc_videotoolbox." >&2
    exit 1
fi

render_template() {
    local template_path="$1"
    local destination_path="$2"

    sed \
        -e "s|__REPO_ROOT__|$REPO_ROOT|g" \
    -e "s|__APP_SUPPORT_DIR__|$APP_SUPPORT_DIR|g" \
        -e "s|__HOME__|$HOME|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
    -e "s|__RUNNER_PATH__|$INSTALLED_SCRIPTS_DIR/run_converter.sh|g" \
    -e "s|__WORKING_DIRECTORY__|$RUNTIME_ROOT|g" \
        "$template_path" > "$destination_path"
}

migrate_existing_config() {
    local config_path="$1"
    local old_secrets_dir
    old_secrets_dir="$REPO_ROOT/src/secrets"
    local new_secrets_dir
    new_secrets_dir="$APP_SUPPORT_DIR/runtime/src/secrets"

    if grep -Eq '^vt_qv = (45|50|55)$' "$config_path"; then
        /usr/bin/sed -i '' -E 's/^vt_qv = (45|50|55)$/vt_qv = 50/' "$config_path"
        echo "Updated vt_qv to 50 in $config_path"
    fi

    if grep -Eq '^vt_qv_small_height = (45|50|55)$' "$config_path"; then
        /usr/bin/sed -i '' -E 's/^vt_qv_small_height = (45|50|55)$/vt_qv_small_height = 50/' "$config_path"
        echo "Updated vt_qv_small_height to 50 in $config_path"
    fi

    if ! grep -Eq '^vt_g = ' "$config_path"; then
        printf '\nvt_g = 72\nvt_keyint_min = 24\nvt_spatial_aq = 1\nvt_realtime = 0\n' >> "$config_path"
        echo "Added VideoToolbox settings to $config_path"
    else
        /usr/bin/sed -i '' -E 's/^vt_g = .*/vt_g = 72/' "$config_path"
        /usr/bin/sed -i '' -E 's/^vt_keyint_min = .*/vt_keyint_min = 24/' "$config_path"
        if grep -Eq '^vt_spatial_aq = ' "$config_path"; then
            /usr/bin/sed -i '' -E 's/^vt_spatial_aq = .*/vt_spatial_aq = 1/' "$config_path"
        else
            printf 'vt_spatial_aq = 1\n' >> "$config_path"
        fi
        /usr/bin/sed -i '' -E 's/^vt_realtime = .*/vt_realtime = 0/' "$config_path"
        echo "Updated VideoToolbox settings in $config_path"
    fi

    if grep -Fq "secrets_dir = \"$old_secrets_dir\"" "$config_path"; then
        /usr/bin/sed -i '' "s|secrets_dir = \"$old_secrets_dir\"|secrets_dir = \"$new_secrets_dir\"|" "$config_path"
        echo "Updated secrets_dir to runtime copy in $config_path"
    fi
}

if [ ! -f "$CONFIG_DEST" ]; then
    render_template "$SCRIPT_DIR/templates/config.macos.toml" "$CONFIG_DEST"
    echo "Created native config at $CONFIG_DEST"
else
    migrate_existing_config "$CONFIG_DEST"
fi

if [ ! -f "$ENV_DEST" ]; then
    cp "$SCRIPT_DIR/templates/converter.env" "$ENV_DEST"
    echo "Created environment template at $ENV_DEST"
fi

render_template "$SCRIPT_DIR/templates/com.schleising.convert-to-h265.converter.plist" "$PLIST_DEST"

helper_scripts=(start_converter stop_converter restart_converter status_converter uninstall_converter)
for helper_script in "${helper_scripts[@]}"; do
    ln -sf "$INSTALLED_SCRIPTS_DIR/$helper_script" "$BIN_DIR/$helper_script"
done

ensure_zsh_path_block "$ZSHRC_PATH" "$BIN_DIR"

cat > "$INSTALL_STATE_PATH" <<EOF
BIN_DIR="$BIN_DIR"
INSTALLED_SCRIPTS_DIR="$INSTALLED_SCRIPTS_DIR"
PLIST_DEST="$PLIST_DEST"
CONFIG_DEST="$CONFIG_DEST"
ENV_DEST="$ENV_DEST"
LOG_DIR="$LOG_DIR"
WORK_DIR="$WORK_DIR"
RUNTIME_ROOT="$RUNTIME_ROOT"
RUNTIME_VENV_DIR="$RUNTIME_VENV_DIR"
ZSHRC_PATH="$ZSHRC_PATH"
PYTHON_BIN="$PYTHON_BIN"
REPO_ROOT="$REPO_ROOT"
LABEL="$LABEL"
EOF

if grep -Eq '^DB_URL=(CHANGE_ME)?$' "$ENV_DEST"; then
    echo "DB_URL is not configured in $ENV_DEST. Service files were installed only."
    echo "Set DB_URL in $ENV_DEST and then run start_converter."
    exit 0
fi

echo "Installed converter service."
echo "Config: $CONFIG_DEST"
echo "Env:    $ENV_DEST"
echo "Plist:  $PLIST_DEST"
echo "Helpers: $BIN_DIR"
echo "Runtime: $RUNTIME_ROOT"
echo "zsh PATH updated in: $ZSHRC_PATH"
echo "Run start_converter to start the service."