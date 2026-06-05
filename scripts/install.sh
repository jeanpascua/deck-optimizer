#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="deck-auto-tdp"
RESUME_SERVICE_NAME="deck-auto-tdp-resume"

check_ryzenadj() {
    if ! command -v ryzenadj &>/dev/null; then
        echo "ERROR: ryzenadj not found. Install it first:"
        echo "  sudo pacman -S ryzenadj  (SteamOS)"
        echo "  Or build from source: https://github.com/FlyGoat/RyzenAdj"
        exit 1
    fi
    echo "OK: ryzenadj found at $(command -v ryzenadj)"
}

set_ryzenadj_permissions() {
    local bin
    bin="$(command -v ryzenadj)"
    if [ "$(stat -c '%u' "$bin")" != "0" ]; then
        echo "WARNING: ryzenadj not owned by root — skipping setuid"
        return
    fi
    sudo chmod u+s "$bin"
    echo "OK: ryzenadj setuid set (runs as root without sudo)"
}

check_gpu_sysfs() {
    if [ ! -f /sys/class/drm/card0/device/gpu_busy_percent ]; then
        echo "WARNING: /sys/class/drm/card0/device/gpu_busy_percent not found"
        echo "GPU monitoring may not work on this device"
    else
        echo "OK: GPU sysfs interface available"
    fi
}

install_service() {
    local service_src="$PROJECT_DIR/config/$SERVICE_NAME.service"
    local service_dst="$HOME/.config/systemd/user/$SERVICE_NAME.service"

    mkdir -p "$HOME/.config/systemd/user"
    cp "$service_src" "$service_dst"
    sed -i "s|%h/projects/deck-auto-tdp|$PROJECT_DIR|g" "$service_dst"

    systemctl --user daemon-reload
    systemctl --user enable "$SERVICE_NAME"
    systemctl --user start "$SERVICE_NAME"

    echo "OK: service installed and started"
    echo "    logs: journalctl --user -u $SERVICE_NAME -f"
    echo "    profiles: ~/.config/deck-auto-tdp/profiles.json"
}

install_resume_service() {
    local service_src="$PROJECT_DIR/config/$RESUME_SERVICE_NAME.service"
    local service_dst="$HOME/.config/systemd/user/$RESUME_SERVICE_NAME.service"

    cp "$service_src" "$service_dst"
    sed -i "s|%h/projects/deck-auto-tdp|$PROJECT_DIR|g" "$service_dst"

    systemctl --user daemon-reload
    systemctl --user enable "$RESUME_SERVICE_NAME"

    echo "OK: resume hook installed (fires on wake from suspend)"
    echo "    logs: journalctl --user -u $RESUME_SERVICE_NAME"
}

echo "=== deck-auto-tdp installer ==="
check_ryzenadj
set_ryzenadj_permissions
check_gpu_sysfs
install_service
install_resume_service
echo "Done."
