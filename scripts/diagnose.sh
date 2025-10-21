#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[DIAG]${NC} $1"
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

# Navigate to docker directory
cd "$(dirname "$0")/../docker"

log "🔍 Plum-Snapcast Diagnostics"
echo ""

# Check if containers are running
log "Container Status:"
docker-compose ps

echo ""

# Check container logs
log "Recent Snapcast Server Logs:"
docker-compose logs --tail=20 snapserver

echo ""

# Check if services are listening on expected ports
log "Network Port Status:"
PI_IP=$(hostname -I | awk '{print $1}')
info "Pi IP Address: $PI_IP"

echo ""
info "Checking key ports:"
for port in 1704 1705 1780 1788 3689 5000 5353; do
    if netstat -ln | grep -q ":$port "; then
        echo "✅ Port $port is listening"
    else
        echo "❌ Port $port is NOT listening"
    fi
done

echo ""

# Check Avahi/mDNS services
log "mDNS/Avahi Services:"
if command -v avahi-browse &> /dev/null; then
    info "Scanning for AirPlay services on network:"
    timeout 5 avahi-browse -t _airplay._tcp || echo "No AirPlay services found or avahi-browse timed out"

    echo ""
    info "Scanning for Spotify Connect services:"
    timeout 5 avahi-browse -t _spotify-connect._tcp || echo "No Spotify Connect services found"
else
    warn "avahi-browse not installed. Install with: sudo apt-get install avahi-utils"
fi

echo ""

# Check if shairport-sync is running inside container
log "Services inside container:"
if docker-compose exec snapserver pgrep shairport-sync > /dev/null 2>&1; then
    echo "✅ shairport-sync is running"
else
    echo "❌ shairport-sync is NOT running"
fi

if docker-compose exec snapserver pgrep snapserver > /dev/null 2>&1; then
    echo "✅ snapserver is running"
else
    echo "❌ snapserver is NOT running"
fi

if docker-compose exec snapserver pgrep avahi-daemon > /dev/null 2>&1; then
    echo "✅ avahi-daemon is running"
else
    echo "❌ avahi-daemon is NOT running"
fi

echo ""

# Check snapcast configuration
log "Snapcast Configuration:"
if docker-compose exec snapserver test -f /app/config/snapserver.conf; then
    info "Active snapcast sources:"
    docker-compose exec snapserver grep "^source =" /app/config/snapserver.conf || echo "No active sources found"
else
    error "snapserver.conf not found"
fi

echo ""

# Quick connectivity test
log "Connectivity Test:"
info "Testing Snapcast JSON-RPC API:"
if curl -s --connect-timeout 5 "http://$PI_IP:1780/jsonrpc" > /dev/null; then
    echo "✅ Snapcast API is accessible"
else
    echo "❌ Snapcast API is NOT accessible"
fi

echo ""
log "🔧 Troubleshooting Tips:"
echo "1. Make sure you're on the same network as the Pi"
echo "2. Try restarting services: docker-compose restart"
echo "3. Check firewall settings on the Pi"
echo "4. For AirPlay: Look for '$AIRPLAY_DEVICE_NAME' in your device's AirPlay menu"
echo "5. For Spotify: Enable Spotify and look for '$SPOTIFY_DEVICE_NAME' in Spotify Connect"
echo ""
echo "Frontend: http://$PI_IP:3000"
echo "Logs: docker-compose logs -f snapserver"