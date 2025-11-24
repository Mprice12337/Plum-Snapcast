#!/bin/bash
# Diagnostic script for Plum-Snapcast on Raspberry Pi
# Run this on your Pi to diagnose shairport-sync and avahi failures

echo "=========================================="
echo "Plum-Snapcast Diagnostics"
echo "=========================================="
echo ""

# Check if container is running
echo "1. Container Status:"
docker ps | grep plum-snapcast
echo ""

# Check supervisord status
echo "2. Supervisor Service Status:"
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
echo ""

# Get shairport-sync logs
echo "3. Shairport-Sync Logs (last 50 lines):"
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -50 shairport-sync
echo ""

# Get avahi logs
echo "4. Avahi Daemon Logs (last 50 lines):"
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -50 avahi
echo ""

# Check D-Bus
echo "5. D-Bus Process:"
docker exec plum-snapcast-server ps aux | grep dbus | grep -v grep
echo ""

# Test Python D-Bus
echo "6. Python D-Bus Test:"
docker exec plum-snapcast-server python3 -c "import dbus; print('✓ D-Bus import successful')" 2>&1
echo ""

# Check control script syntax
echo "7. Control Script Syntax Check:"
docker exec plum-snapcast-server python3 -m py_compile /app/scripts/airplay-control-script.py && echo "✓ Script compiles successfully" || echo "✗ Script has syntax errors"
echo ""

# Check file permissions
echo "8. Script Permissions:"
docker exec plum-snapcast-server ls -la /app/scripts/airplay-control-script.py
echo ""

# Check shairport-sync config
echo "9. Shairport-Sync Config:"
docker exec plum-snapcast-server cat /app/config/shairport-sync.conf
echo ""

# Check avahi config
echo "10. Avahi Config:"
docker exec plum-snapcast-server cat /etc/avahi/avahi-daemon.conf
echo ""

# Test shairport-sync manually
echo "11. Test Shairport-Sync Manual Start:"
docker exec plum-snapcast-server timeout 3 shairport-sync --help 2>&1 | head -5
echo ""

echo "=========================================="
echo "Diagnostics Complete"
echo "=========================================="
