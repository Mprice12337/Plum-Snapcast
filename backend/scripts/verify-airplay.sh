#!/bin/bash
echo "=== AirPlay Service Verification ==="

# Check D-Bus
echo "1. D-Bus status:"
if [ -S /var/run/dbus/system_bus_socket ]; then
    echo "   ✓ D-Bus socket exists"
else
    echo "   ✗ D-Bus socket missing!"
fi

# Check Avahi daemon
echo -e "\n2. Avahi daemon:"
if pgrep avahi-daemon > /dev/null; then
    echo "   ✓ Avahi daemon running (PID: $(pgrep avahi-daemon))"
    avahi-daemon --check && echo "   ✓ Avahi daemon responsive" || echo "   ✗ Avahi daemon not responsive"
else
    echo "   ✗ Avahi daemon not running!"
fi

# Check Shairport-sync
echo -e "\n3. Shairport-sync:"
if pgrep shairport-sync > /dev/null; then
    echo "   ✓ Shairport-sync running (PID: $(pgrep shairport-sync))"
else
    echo "   ✗ Shairport-sync not running!"
fi

# Check for AirPlay advertisement
echo -e "\n4. AirPlay advertisement:"
timeout 5 avahi-browse -r _raop._tcp 2>&1 | grep "${AIRPLAY_DEVICE_NAME:-Plum Audio}" && \
    echo "   ✓ AirPlay service advertised!" || \
    echo "   ✗ AirPlay service not found in mDNS"

# Show all services
echo -e "\n5. All advertised services:"
timeout 3 avahi-browse -at | head -20