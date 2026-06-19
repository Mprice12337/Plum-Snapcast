#!/bin/bash

###############################################################################
# Plum WiFi Setup - Host Installer
###############################################################################
# Installs the host-side captive-portal WiFi configuration service on a
# Raspberry Pi running Raspberry Pi OS (Bookworm or newer) with NetworkManager.
#
# Usage (from a checked-out repo):
#   sudo bash scripts/wifi-setup/install.sh
#
# What it does:
#   - Installs runtime deps (python3-flask, dnsmasq-base, iptables)
#   - Copies the daemon + static assets to /opt/plum-wifi-setup
#   - Installs and enables the systemd unit
#   - Sanity-checks that NetworkManager is the active network stack
#
###############################################################################

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERROR: must run as root (use sudo)${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/plum-wifi-setup"
SERVICE_NAME="plum-wifi-setup.service"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Plum WiFi Setup Installer${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

###############################################################################
# Sanity checks
###############################################################################
echo -e "${YELLOW}[1/5] Checking environment...${NC}"

if ! command -v nmcli &> /dev/null; then
    echo -e "${RED}NetworkManager (nmcli) is not installed.${NC}"
    echo "This service requires NetworkManager. On older Raspberry Pi OS images"
    echo "the default is dhcpcd. Switch to NetworkManager with:"
    echo "  sudo raspi-config  ->  Advanced Options  ->  Network Config  ->  NetworkManager"
    exit 1
fi

NM_STATE="$(nmcli -t -f RUNNING general 2>/dev/null | head -n1 || true)"
if [ "$NM_STATE" != "running" ]; then
    echo -e "${YELLOW}Warning: NetworkManager is installed but not currently running.${NC}"
fi

if ! ip link show wlan0 &> /dev/null; then
    echo -e "${YELLOW}Warning: wlan0 interface not found. Set PLUM_WIFI_IFACE in the${NC}"
    echo -e "${YELLOW}systemd unit if your wireless interface has a different name.${NC}"
fi

echo -e "${GREEN}✓ Environment OK${NC}"
echo ""

###############################################################################
# Install dependencies
###############################################################################
echo -e "${YELLOW}[2/5] Installing dependencies...${NC}"
apt-get update
apt-get install -y --no-install-recommends \
    python3 \
    python3-flask \
    dnsmasq-base \
    iptables
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

###############################################################################
# Copy files
###############################################################################
echo -e "${YELLOW}[3/5] Installing files to ${INSTALL_DIR}...${NC}"
mkdir -p "$INSTALL_DIR/static"
install -m 0755 "$SCRIPT_DIR/plum-wifi-setup.py" "$INSTALL_DIR/plum-wifi-setup.py"
install -m 0644 "$SCRIPT_DIR/static/setup.html"  "$INSTALL_DIR/static/setup.html"
echo -e "${GREEN}✓ Files installed${NC}"
echo ""

###############################################################################
# Install systemd unit
###############################################################################
echo -e "${YELLOW}[4/5] Installing systemd service...${NC}"
install -m 0644 "$SCRIPT_DIR/$SERVICE_NAME" "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
echo -e "${GREEN}✓ Service enabled${NC}"
echo ""

###############################################################################
# Start / restart
###############################################################################
echo -e "${YELLOW}[5/5] Starting service...${NC}"
systemctl restart "$SERVICE_NAME"
sleep 1
systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Plum WiFi Setup installed successfully.${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Behavior:"
echo "  - On boot the daemon checks whether the Pi has network connectivity."
echo "  - If no network is available for ~30s, it brings up the 'plum-setup'"
echo "    WiFi access point (WPA2, password 'plumsetup') on wlan0."
echo "  - Connecting a phone/laptop will trigger the captive portal at"
echo "    http://192.168.4.1 where the user picks a WiFi network."
echo "  - Once connected, the AP shuts itself down."
echo ""
echo "Useful commands:"
echo "  sudo systemctl status   plum-wifi-setup"
echo "  sudo systemctl restart  plum-wifi-setup"
echo "  sudo journalctl -u      plum-wifi-setup -f"
echo ""
