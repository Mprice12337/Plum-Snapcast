#!/bin/bash
# Bluetooth initialization script
# Configures the Bluetooth adapter for audio reception

set -e

# Configuration from environment
ADAPTER="${BLUETOOTH_ADAPTER:-hci0}"
DEVICE_NAME="${BLUETOOTH_DEVICE_NAME:-Plum Audio}"
DISCOVERABLE="${BLUETOOTH_DISCOVERABLE:-1}"
AUTO_PAIR="${BLUETOOTH_AUTO_PAIR:-1}"

echo "Starting Bluetooth initialization..."
echo "Adapter: $ADAPTER"
echo "Device name: $DEVICE_NAME"
echo "Discoverable: $DISCOVERABLE"
echo "Auto-pair: $AUTO_PAIR"

# Wait for bluetoothd to be ready
echo "Waiting for bluetoothd to start..."
for i in $(seq 1 30); do
    if bluetoothctl show "$ADAPTER" >/dev/null 2>&1; then
        echo "Bluetoothd is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: Timeout waiting for bluetoothd"
        exit 1
    fi
    sleep 1
done

# Configure adapter using bluetoothctl
echo "Configuring Bluetooth adapter $ADAPTER..."

# Power on the adapter
bluetoothctl power on

# Set device name
bluetoothctl system-alias "$DEVICE_NAME"

# Make device pairable
bluetoothctl pairable on

# Set discoverable mode
if [ "$DISCOVERABLE" = "1" ]; then
    bluetoothctl discoverable on
    echo "Bluetooth device is discoverable as: $DEVICE_NAME"
else
    bluetoothctl discoverable off
    echo "Bluetooth device is NOT discoverable"
fi

# Enable pairing agent if auto-pair is enabled
if [ "$AUTO_PAIR" = "1" ]; then
    # The default agent will handle pairing
    bluetoothctl agent on
    bluetoothctl default-agent
    echo "Bluetooth pairing agent enabled (auto-accept mode)"
fi

echo "Bluetooth initialization complete!"
echo "Adapter: $ADAPTER"
echo "Status:"
bluetoothctl show "$ADAPTER"

# Keep the script running to maintain agent
if [ "$AUTO_PAIR" = "1" ]; then
    echo "Keeping Bluetooth agent active..."
    # Wait indefinitely
    tail -f /dev/null
fi
