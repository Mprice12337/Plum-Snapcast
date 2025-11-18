#!/bin/bash

###############################################################################
# Plum-Snapcast Fresh Pi Setup Script
###############################################################################
# This script configures a fresh Raspberry Pi OS Lite installation for running
# Plum-Snapcast. It installs all required dependencies and configures the system.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/Plum-Snapcast/main/scripts/fresh-pi-setup.sh | sudo bash
#
# Or download and run locally:
#   sudo bash fresh-pi-setup.sh
#
# This script must be run with sudo/root privileges.
###############################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERROR: This script must be run as root (use sudo)${NC}"
    exit 1
fi

# Get the actual user who ran sudo (not root)
ACTUAL_USER="${SUDO_USER:-$USER}"
if [ "$ACTUAL_USER" = "root" ]; then
    echo -e "${YELLOW}Warning: Running as root without sudo. User will be 'root'.${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Plum-Snapcast Fresh Pi Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "This script will install and configure:"
echo "  - Docker Engine"
echo "  - Git"
echo "  - Audio device permissions"
echo ""
echo "Target user: $ACTUAL_USER"
echo ""

###############################################################################
# Step 1: Update system packages
###############################################################################
echo -e "${YELLOW}[1/5] Updating system packages...${NC}"
apt-get update
apt-get upgrade -y
echo -e "${GREEN}✓ System packages updated${NC}"
echo ""

###############################################################################
# Step 2: Install Docker
###############################################################################
echo -e "${YELLOW}[2/5] Installing Docker...${NC}"

# Check if Docker is already installed
if command -v docker &> /dev/null; then
    echo "  Docker is already installed ($(docker --version))"
else
    echo "  Downloading Docker installation script..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh

    echo "  Running Docker installation script..."
    sh /tmp/get-docker.sh

    rm /tmp/get-docker.sh
    echo -e "${GREEN}✓ Docker installed successfully${NC}"
fi

# Add user to docker group
if id -nG "$ACTUAL_USER" | grep -qw "docker"; then
    echo "  User $ACTUAL_USER is already in docker group"
else
    echo "  Adding user $ACTUAL_USER to docker group..."
    usermod -aG docker "$ACTUAL_USER"
    echo -e "${GREEN}✓ User added to docker group${NC}"
    echo -e "${YELLOW}  Note: User must log out and back in for group changes to take effect${NC}"
fi

echo ""

###############################################################################
# Step 3: Install Git
###############################################################################
echo -e "${YELLOW}[3/5] Installing Git...${NC}"

if command -v git &> /dev/null; then
    echo "  Git is already installed ($(git --version))"
else
    apt-get install -y git
    echo -e "${GREEN}✓ Git installed successfully${NC}"
fi

echo ""

###############################################################################
# Step 4: Configure audio device permissions
###############################################################################
echo -e "${YELLOW}[4/5] Configuring audio device permissions...${NC}"

UDEV_RULE_FILE="/etc/udev/rules.d/99-audio-permissions.rules"
UDEV_RULE='SUBSYSTEM=="sound", MODE="0666"'

if [ -f "$UDEV_RULE_FILE" ] && grep -q "$UDEV_RULE" "$UDEV_RULE_FILE"; then
    echo "  Audio permissions rule already exists"
else
    echo "  Creating udev rule for audio device access..."
    echo "$UDEV_RULE" > "$UDEV_RULE_FILE"

    echo "  Reloading udev rules..."
    udevadm control --reload-rules
    udevadm trigger

    echo -e "${GREEN}✓ Audio device permissions configured${NC}"
fi

echo ""

###############################################################################
# Step 5: Install Docker Compose (if needed)
###############################################################################
echo -e "${YELLOW}[5/5] Checking Docker Compose...${NC}"

# Check if docker compose command exists (Docker Compose V2)
if docker compose version &> /dev/null; then
    echo "  Docker Compose V2 is available ($(docker compose version))"
    echo -e "${GREEN}✓ Docker Compose ready${NC}"
else
    echo -e "${YELLOW}  Docker Compose V2 not found, may need manual installation${NC}"
fi

echo ""

###############################################################################
# Summary
###############################################################################
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ Fresh Pi setup complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Installed/Configured:"
echo "  ✓ Docker Engine"
echo "  ✓ Git"
echo "  ✓ Audio device permissions"
echo "  ✓ User '$ACTUAL_USER' added to docker group"
echo ""
echo -e "${YELLOW}IMPORTANT: You must log out and back in for docker group membership to take effect.${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1. Log out and back in (or reboot):"
echo "   logout"
echo "   # or"
echo "   sudo reboot"
echo ""
echo "2. Clone the Plum-Snapcast repository:"
echo "   git clone https://github.com/YOUR_USERNAME/Plum-Snapcast.git ~/Plum-Snapcast"
echo ""
echo "3. Deploy the application:"
echo "   cd ~/Plum-Snapcast/docker"
echo "   cp .env.example .env"
echo "   nano .env  # Edit configuration if needed"
echo "   docker compose pull"
echo "   docker compose up -d"
echo ""
echo "4. Verify services are running:"
echo "   docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status"
echo ""
echo "5. Access the web interface:"
echo "   http://$(hostname -I | awk '{print $1}'):3000"
echo ""

exit 0
