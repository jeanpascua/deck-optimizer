#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="deck-optimizer"
CONFIG_DIR="$HOME/.config/deck-optimizer"

echo "=== deck-optimizer installer ==="
echo ""

check_platform() {
    if [ ! -f /etc/os-release ] || ! grep -q "SteamOS" /etc/os-release 2>/dev/null; then
        echo "WARNING: Not running on SteamOS. Deck-side features (TDP, GPU clock) won't work."
        echo "         PC-side optimizer (sync_deck.py) will still work."
        echo ""
    fi
}

check_ryzenadj() {
    if ! command -v ryzenadj &>/dev/null; then
        echo "ryzenadj not found. To install on SteamOS:"
        echo "  sudo steamos-readonly disable"
        echo "  sudo pacman-key --init && sudo pacman-key --populate"
        echo "  sudo pacman -S base-devel cmake git pciutils"
        echo "  git clone https://github.com/FlyGoat/RyzenAdj ~/ryzenadj"
        echo "  cd ~/ryzenadj && mkdir build && cd build && cmake .. && make"
        echo "  sudo cp ryzenadj /usr/local/bin/ && sudo chmod +s /usr/local/bin/ryzenadj"
        echo "  sudo steamos-readonly enable"
        echo ""
        echo "Skipping service install (ryzenadj required)."
        return 1
    fi
    echo "OK: ryzenadj found at $(command -v ryzenadj)"
    return 0
}

setup_config() {
    mkdir -p "$CONFIG_DIR"
    if [ ! -f "$CONFIG_DIR/config.json" ]; then
        python3 "$PROJECT_DIR/src/config.py"
    else
        echo "Config already exists at $CONFIG_DIR/config.json"
        read -p "Reconfigure? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python3 "$PROJECT_DIR/src/config.py"
        fi
    fi
}

install_service() {
    local service_src="$PROJECT_DIR/config/$SERVICE_NAME.service"
    local service_dst="$HOME/.config/systemd/user/$SERVICE_NAME.service"
    local resume_src="$PROJECT_DIR/config/$SERVICE_NAME-resume.service"
    local resume_dst="$HOME/.config/systemd/user/$SERVICE_NAME-resume.service"

    mkdir -p "$HOME/.config/systemd/user"

    cp "$service_src" "$service_dst"
    sed -i "s|%h/projects/deck-optimizer|$PROJECT_DIR|g" "$service_dst"

    if [ -f "$resume_src" ]; then
        cp "$resume_src" "$resume_dst"
        sed -i "s|%h/projects/deck-optimizer|$PROJECT_DIR|g" "$resume_dst"
        systemctl --user enable "$SERVICE_NAME-resume" 2>/dev/null || true
    fi

    systemctl --user daemon-reload
    systemctl --user enable "$SERVICE_NAME"
    systemctl --user start "$SERVICE_NAME"

    echo ""
    echo "OK: service installed and started"
    echo "  Logs:     journalctl --user -u $SERVICE_NAME -f"
    echo "  Profiles: $CONFIG_DIR/profiles.json"
    echo "  Config:   $CONFIG_DIR/config.json"
}

check_platform
setup_config
if check_ryzenadj; then
    install_service
fi

echo ""
echo "=== Installation complete ==="
echo ""
echo "To optimize games from a PC:"
echo "  cd $PROJECT_DIR/src && python3 -m optimizer.sync_deck"
echo ""
echo "To optimize a single game:"
echo "  cd $PROJECT_DIR/src && python3 -m optimizer.cli --game 'Game Name' --app-id 12345"
