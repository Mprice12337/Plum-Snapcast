#!/bin/bash
# Bluetooth initialization script
# Configures the Bluetooth adapter for audio reception

set -e

# Configuration from environment
ADAPTER="${BLUETOOTH_ADAPTER:-hci0}"
DEVICE_NAME="${BLUETOOTH_DEVICE_NAME:-Plum Audio}"
DISCOVERABLE="${BLUETOOTH_DISCOVERABLE:-1}"
AUTO_PAIR="${BLUETOOTH_AUTO_PAIR:-1}"

echo "========================================"
echo "Bluetooth Initialization Starting"
echo "========================================"
echo "Adapter: $ADAPTER"
echo "Device name: $DEVICE_NAME"
echo "Discoverable: $DISCOVERABLE"
echo "Auto-pair: $AUTO_PAIR"
echo "========================================"

# Wait for D-Bus to be available
echo "Waiting for D-Bus..."
for i in $(seq 1 30); do
    if [ -S /var/run/dbus/system_bus_socket ]; then
        echo "D-Bus socket found"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: Timeout waiting for D-Bus"
        exit 1
    fi
    sleep 1
done

# Wait for bluetoothd to be ready
echo "Waiting for bluetoothd to start..."
for i in $(seq 1 30); do
    if bluetoothctl list 2>/dev/null | grep -q "$ADAPTER"; then
        echo "Bluetoothd is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: Timeout waiting for bluetoothd"
        echo "Available adapters:"
        bluetoothctl list || true
        exit 1
    fi
    sleep 1
done

# Give bluetoothd a moment to fully initialize
sleep 2

# Configure adapter using bluetoothctl in command mode
echo "Configuring Bluetooth adapter $ADAPTER..."

# Create a bluetoothctl command script
cat > /tmp/bt-init-commands.txt <<EOF
power on
pairable on
discoverable $([ "$DISCOVERABLE" = "1" ] && echo "on" || echo "off")
agent on
default-agent
EOF

# Execute commands via bluetoothctl
echo "Executing Bluetooth configuration commands..."
bluetoothctl <<EOF
power on
pairable on
discoverable $([ "$DISCOVERABLE" = "1" ] && echo "on" || echo "off")
agent NoInputNoOutput
default-agent
EOF

# Give commands time to apply
sleep 2

# Set device name via D-Bus (more reliable than bluetoothctl)
echo "Setting device name via D-Bus..."
if command -v gdbus >/dev/null 2>&1; then
    gdbus call --system \
        --dest org.bluez \
        --object-path /org/bluez/hci0 \
        --method org.freedesktop.DBus.Properties.Set \
        org.bluez.Adapter1 \
        Alias "<'$DEVICE_NAME'>" 2>/dev/null || {
        echo "Warning: Could not set device name via D-Bus, trying bluetoothctl..."
        echo "system-alias '$DEVICE_NAME'" | bluetoothctl
    }
else
    echo "Setting name via bluetoothctl..."
    echo "system-alias '$DEVICE_NAME'" | bluetoothctl
fi

sleep 1

# Verify configuration
echo ""
echo "========================================"
echo "Bluetooth Configuration Complete!"
echo "========================================"
echo "Adapter Status:"
bluetoothctl show | grep -E "(Name|Alias|Powered|Discoverable|Pairable)" || bluetoothctl show

echo ""
echo "Checking discoverability..."
if bluetoothctl show | grep -q "Discoverable: yes"; then
    echo "✓ Device IS discoverable as: $DEVICE_NAME"
else
    echo "✗ WARNING: Device is NOT discoverable!"
    echo "  Attempting to force discoverable mode..."
    echo "discoverable on" | bluetoothctl
    sleep 2
    bluetoothctl show | grep Discoverable
fi

# Keep the script running to maintain the agent
if [ "$AUTO_PAIR" = "1" ]; then
    echo ""
    echo "Bluetooth agent active - ready for pairing"
    echo "========================================"

    # Keep agent alive
    # Use bluetoothctl in agent mode
    exec bluetoothctl
else
    echo ""
    echo "Auto-pairing disabled"
    echo "========================================"
    tail -f /dev/null
fi
