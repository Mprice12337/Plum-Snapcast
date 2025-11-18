#!/bin/bash
# Start Bluetooth services if enabled
# This script is run by supervisord after initialization

# DO NOT use set -e - we want to handle errors gracefully
# set -e would cause the script to exit and supervisord to fail

echo "==========================================="
echo "Bluetooth Service Starter"
echo "==========================================="
echo "BLUETOOTH_ENABLED=${BLUETOOTH_ENABLED}"
echo "==========================================="

# Function to wait for supervisord to be ready
wait_for_supervisord() {
    echo "Waiting for supervisord socket to be ready..."
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        # Check if supervisor socket exists and is accessible
        if [ -S /var/run/supervisor.sock ]; then
            # Wait a bit more to ensure RPC interface is fully ready
            sleep 2
            echo "Supervisord socket is ready!"
            return 0
        fi
        attempt=$((attempt + 1))
        echo "  Attempt $attempt/$max_attempts..."
        sleep 1
    done

    echo "ERROR: Supervisord socket not ready after $max_attempts seconds"
    return 1
}

# Function to start a service with retry
start_service() {
    local service_name=$1
    local max_attempts=3
    local attempt=0

    echo "Starting $service_name..."

    while [ $attempt -lt $max_attempts ]; do
        if supervisorctl -c /app/supervisord/supervisord.conf start "$service_name" 2>&1 | grep -q "started\|already"; then
            echo "  ✓ $service_name started successfully"
            return 0
        fi
        attempt=$((attempt + 1))
        echo "  Attempt $attempt/$max_attempts failed, retrying..."
        sleep 2
    done

    echo "  ✗ WARNING: Failed to start $service_name after $max_attempts attempts"
    return 1
}

if [ "${BLUETOOTH_ENABLED}" = "1" ]; then
    echo "Bluetooth is ENABLED - starting services..."

    # Wait for supervisord to be ready
    if ! wait_for_supervisord; then
        echo "Cannot start Bluetooth services - supervisord not ready"
        echo "Bluetooth services will not be available"
        # Don't exit - just keep running
        tail -f /dev/null
        exit 0
    fi

    # Start services in sequence
    start_service bluetoothd
    sleep 3

    start_service bluetooth-init
    sleep 5

    start_service bluealsa
    sleep 3

    start_service bluealsa-aplay
    sleep 2

    echo "==========================================="
    echo "Bluetooth services startup complete!"
    echo "==========================================="

    # Show final status
    echo "Service status:"
    supervisorctl -c /app/supervisord/supervisord.conf status 2>/dev/null | grep -E "bluetooth|bluealsa" || echo "  (Status check failed)"

else
    echo "Bluetooth is DISABLED - skipping Bluetooth services"
fi

# Keep this process running (required for supervisord)
echo ""
echo "Bluetooth service starter running..."
echo "==========================================="
exec tail -f /dev/null
