#!/bin/bash
# Start Bluetooth services if enabled
# This script is run by supervisord after initialization

set -e

echo "==========================================="
echo "Bluetooth Service Starter"
echo "==========================================="
echo "BLUETOOTH_ENABLED=${BLUETOOTH_ENABLED}"
echo "==========================================="

if [ "${BLUETOOTH_ENABLED}" = "1" ]; then
    echo "Bluetooth is ENABLED - starting services..."

    # Wait for supervisord to be fully ready
    sleep 3

    # Start Bluetooth services via supervisorctl
    echo "Starting bluetoothd..."
    supervisorctl -c /app/supervisord/supervisord.conf start bluetoothd || {
        echo "ERROR: Failed to start bluetoothd"
        exit 1
    }

    # Wait for bluetoothd to initialize
    sleep 3

    echo "Starting bluetooth-init..."
    supervisorctl -c /app/supervisord/supervisord.conf start bluetooth-init || {
        echo "ERROR: Failed to start bluetooth-init"
        exit 1
    }

    # Wait for Bluetooth to be configured
    sleep 5

    echo "Starting bluealsa..."
    supervisorctl -c /app/supervisord/supervisord.conf start bluealsa || {
        echo "ERROR: Failed to start bluealsa"
        exit 1
    }

    # Wait for bluealsa to initialize
    sleep 3

    echo "Starting bluealsa-aplay..."
    supervisorctl -c /app/supervisord/supervisord.conf start bluealsa-aplay || {
        echo "ERROR: Failed to start bluealsa-aplay"
        exit 1
    }

    echo "==========================================="
    echo "✓ All Bluetooth services started!"
    echo "==========================================="

    # Show service status
    supervisorctl -c /app/supervisord/supervisord.conf status | grep -E "bluetooth|bluealsa"

else
    echo "Bluetooth is DISABLED - skipping Bluetooth services"
fi

# Keep this process running
echo "Bluetooth service starter complete, keeping alive..."
tail -f /dev/null
