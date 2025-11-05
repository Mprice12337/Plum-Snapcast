#!/bin/bash
# Debug script for AirPlay control script issues

echo "=== AirPlay Control Script Debugging ==="
echo ""

echo "1. Checking if control script exists and is executable..."
if [ -f /app/scripts/airplay-control-script.py ]; then
    echo "   ✓ Control script exists"
    ls -l /app/scripts/airplay-control-script.py
else
    echo "   ✗ Control script NOT found"
fi
echo ""

echo "2. Checking Python and D-Bus availability..."
python3 --version
python3 -c "import dbus; print('   ✓ python3-dbus is installed')" 2>&1
echo ""

echo "3. Checking if D-Bus system bus is accessible..."
if [ -S /var/run/dbus/system_bus_socket ]; then
    echo "   ✓ D-Bus socket exists: /var/run/dbus/system_bus_socket"
    ls -l /var/run/dbus/system_bus_socket
else
    echo "   ✗ D-Bus socket NOT found"
fi
echo ""

echo "4. Checking if shairport-sync is running..."
if pgrep -x shairport-sync > /dev/null; then
    echo "   ✓ shairport-sync is running (PID: $(pgrep -x shairport-sync))"
else
    echo "   ✗ shairport-sync is NOT running"
fi
echo ""

echo "5. Checking D-Bus services..."
if command -v dbus-send >/dev/null 2>&1; then
    echo "   Checking for org.gnome.ShairportSync service..."
    dbus-send --system --print-reply --dest=org.freedesktop.DBus \
        /org/freedesktop/DBus org.freedesktop.DBus.ListNames 2>&1 | \
        grep -i shairport && echo "   ✓ ShairportSync D-Bus service found" || \
        echo "   ✗ ShairportSync D-Bus service NOT found"
else
    echo "   ⚠ dbus-send not available, skipping D-Bus service check"
fi
echo ""

echo "6. Checking control script logs..."
if [ -f /tmp/airplay-control-script.log ]; then
    echo "   ✓ Control script log exists"
    echo "   Last 20 lines:"
    tail -n 20 /tmp/airplay-control-script.log
else
    echo "   ✗ No control script log found at /tmp/airplay-control-script.log"
fi
echo ""

echo "7. Checking snapserver configuration..."
if [ -f /app/config/snapserver.conf ]; then
    echo "   ✓ snapserver.conf exists"
    echo "   AirPlay source configuration:"
    grep -A 1 "source.*snapfifo" /app/config/snapserver.conf || echo "   ✗ No AirPlay source found in config"
else
    echo "   ✗ snapserver.conf NOT found"
fi
echo ""

echo "8. Checking if snapserver is running..."
if pgrep -x snapserver > /dev/null; then
    echo "   ✓ snapserver is running (PID: $(pgrep -x snapserver))"
else
    echo "   ✗ snapserver is NOT running"
fi
echo ""

echo "9. Testing D-Bus connection to shairport-sync..."
python3 << 'PYEOF'
import sys
try:
    import dbus
    bus = dbus.SystemBus()
    print("   ✓ Connected to D-Bus system bus")

    try:
        proxy = bus.get_object('org.gnome.ShairportSync', '/org/gnome/ShairportSync/RemoteControl')
        print("   ✓ Found ShairportSync RemoteControl object")

        iface = dbus.Interface(proxy, 'org.freedesktop.DBus.Properties')
        try:
            title = iface.Get('org.gnome.ShairportSync.RemoteControl', 'Title')
            print(f"   ✓ Can read properties (Title: {title})")
        except Exception as e:
            print(f"   ⚠ Can't read Title property (might be OK if no track playing): {e}")

    except dbus.exceptions.DBusException as e:
        print(f"   ✗ Cannot connect to ShairportSync D-Bus service: {e}")
        print("   This usually means shairport-sync isn't running or D-Bus interface is disabled")

except ImportError:
    print("   ✗ python3-dbus not available")
    sys.exit(1)
except Exception as e:
    print(f"   ✗ Error: {e}")
    sys.exit(1)
PYEOF
echo ""

echo "10. Checking shairport-sync D-Bus configuration..."
if [ -f /app/config/shairport-sync.conf ]; then
    echo "   D-Bus configuration in shairport-sync.conf:"
    grep -A 5 "^dbus" /app/config/shairport-sync.conf || echo "   ✗ No D-Bus config found"
else
    echo "   ✗ shairport-sync.conf NOT found"
fi
echo ""

echo "=== Debugging Complete ==="
echo ""
echo "To manually test the control script, run:"
echo "  python3 /app/scripts/airplay-control-script.py --stream Airplay"
echo ""
echo "To view live control script logs:"
echo "  tail -f /tmp/airplay-control-script.log"
echo ""
echo "To check snapserver logs:"
echo "  cat /var/log/supervisord/snapserver-*.log"
