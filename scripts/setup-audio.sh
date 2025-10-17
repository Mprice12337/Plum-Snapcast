#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[AUDIO SETUP]${NC} $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log "Starting Raspberry Pi audio configuration..."

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    error "Please run as root or with sudo"
    exit 1
fi

# Check if we're on a Raspberry Pi
if [ ! -f /proc/device-tree/model ]; then
    warn "Not running on a Raspberry Pi - some features may not work"
fi

# Step 1: Force audio output to 3.5mm jack
log "Configuring audio output to 3.5mm jack..."
if command -v raspi-config &> /dev/null; then
    raspi-config nonint do_audio 1
    info "✓ Audio forced to 3.5mm jack (headphones)"
else
    warn "raspi-config not found - skipping audio routing configuration"
fi

# Step 2: Create ALSA configuration
log "Creating ALSA configuration..."
tee /etc/asound.conf > /dev/null <<EOF
# Plum Snapcast Audio Configuration
# Force all audio to the 3.5mm headphone jack

pcm.!default {
    type hw
    card Headphones
}

ctl.!default {
    type hw
    card Headphones
}
EOF

info "✓ ALSA configuration created at /etc/asound.conf"

# Step 3: List available audio devices
log "Available audio devices:"
aplay -l || warn "Could not list audio devices"

# Step 4: Set initial volume
log "Setting initial volume to 80%..."
if amixer -c Headphones sset 'Headphone' 80% &> /dev/null; then
    info "✓ Initial volume set to 80%"
else
    warn "Could not set volume - this may need to be done manually after reboot"
fi

# Step 5: Test audio output (optional)
echo ""
read -p "Would you like to test audio output? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log "Playing test tone for 2 seconds..."
    speaker-test -c 2 -t wav -l 1 || warn "Test failed - check your audio connections"
fi

# Step 6: Create helper script for volume control
log "Creating volume control helper script..."
tee /usr/local/bin/plum-volume > /dev/null <<'EOF'
#!/bin/bash
# Helper script to control Plum audio volume

if [ -z "$1" ]; then
    # Show current volume
    amixer -c Headphones sget 'Headphone' | grep -oP '\d+(?=%)' | head -1
else
    # Set volume
    amixer -c Headphones sset 'Headphone' "$1%" > /dev/null
    echo "Volume set to $1%"
fi
EOF

chmod +x /usr/local/bin/plum-volume
info "✓ Volume control script created at /usr/local/bin/plum-volume"
info "  Usage: plum-volume [0-100]"

echo ""
log "🎉 Audio configuration complete!"
echo ""
info "Next steps:"
info "  1. Reboot your Raspberry Pi: sudo reboot"
info "  2. After reboot, start Docker containers: cd docker && docker-compose up -d"
info "  3. Check snapclient logs: docker logs plum-snapcast-client"
info "  4. Test audio: plum-volume 80"
echo ""
log "If audio doesn't work after reboot, verify with: aplay -l"