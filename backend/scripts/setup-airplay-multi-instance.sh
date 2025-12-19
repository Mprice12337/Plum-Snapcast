#!/bin/bash
# Setup script for multiple AirPlay endpoints
# Reads endpoint configuration from AIRPLAY_ENDPOINTS_JSON env var (exported by get-settings.py)

set -e

echo "Setting up AirPlay endpoints from settings..."

# Parse endpoints JSON from environment variable
# AIRPLAY_ENDPOINTS_JSON is set by get-settings.py based on settings.json
if [ -z "$AIRPLAY_ENDPOINTS_JSON" ]; then
    echo "WARNING: AIRPLAY_ENDPOINTS_JSON not set, using default single endpoint"
    # Create default single endpoint if not configured
    AIRPLAY_ENDPOINTS_JSON='[{"id":"1","enabled":true,"deviceName":"Plum Audio","port":5000,"udpPortBase":6001}]'
fi

# Parse JSON array into bash arrays
# Each endpoint has: id, enabled, deviceName, port, udpPortBase
ENDPOINT_COUNT=$(echo "$AIRPLAY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")

if [ "$ENDPOINT_COUNT" -eq 0 ]; then
    echo "No AirPlay endpoints configured"
    exit 0
fi

echo "Configuring $ENDPOINT_COUNT AirPlay endpoint(s):"

# Process each endpoint
for i in $(seq 0 $((ENDPOINT_COUNT-1))); do
    # Extract endpoint properties using python3
    ENDPOINT_JSON=$(echo "$AIRPLAY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin)[$i]))")

    INSTANCE_ID=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
    ENABLED=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('enabled', True))")
    NAME=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['deviceName'])")
    PORT=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['port'])")
    UDP_BASE=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['udpPortBase'])")

    # Only instance 1 gets D-Bus control (to avoid conflicts)
    if [ "$INSTANCE_ID" = "1" ]; then
        DBUS="yes"
    else
        DBUS="no"
    fi

    if [ "$ENABLED" = "False" ] || [ "$ENABLED" = "false" ]; then
        echo "  - Instance ${INSTANCE_ID}: DISABLED"
        continue
    fi

    echo "  - Instance ${INSTANCE_ID}: ${NAME} (port ${PORT}, UDP ${UDP_BASE}-$((UDP_BASE+9)), D-Bus=${DBUS})"

    # Create config file from template
    CONFIG_FILE="/app/config/shairport-sync-${INSTANCE_ID}.conf"
    sed -e "s/AIRPLAY_NAME/${NAME}/g" \
        -e "s/AIRPLAY_PORT/${PORT}/g" \
        -e "s/AIRPLAY_UDP_BASE/${UDP_BASE}/g" \
        -e "s/INSTANCE_ID/${INSTANCE_ID}/g" \
        -e "s/DBUS_ENABLED/${DBUS}/g" \
        /app/config/shairport-sync.conf.template > "${CONFIG_FILE}"

    # Ensure config file is owned by snapcast user (for dynamic updates via API)
    chown snapcast:snapcast "${CONFIG_FILE}" 2>/dev/null || true
    chmod 644 "${CONFIG_FILE}" 2>/dev/null || true

    echo "    ✓ Config: ${CONFIG_FILE}"

    # Create FIFO pipe for audio
    FIFO_PATH="/tmp/airplay-${INSTANCE_ID}-fifo"
    if [ ! -p "${FIFO_PATH}" ]; then
        mkfifo "${FIFO_PATH}"
        chmod 666 "${FIFO_PATH}"
        chown snapcast:snapcast "${FIFO_PATH}" 2>/dev/null || true
        echo "    ✓ Audio FIFO: ${FIFO_PATH}"
    fi

    # Create metadata pipe
    METADATA_PIPE="/tmp/airplay-${INSTANCE_ID}-metadata"
    if [ ! -p "${METADATA_PIPE}" ]; then
        mkfifo "${METADATA_PIPE}"
        chmod 666 "${METADATA_PIPE}"
        chown snapcast:snapcast "${METADATA_PIPE}" 2>/dev/null || true
        echo "    ✓ Metadata pipe: ${METADATA_PIPE}"
    fi

    # Create artwork cache directory
    ARTWORK_DIR="/tmp/shairport-sync-${INSTANCE_ID}/.cache/coverart"
    mkdir -p "${ARTWORK_DIR}"
    chown -R snapcast:snapcast "/tmp/shairport-sync-${INSTANCE_ID}/.cache" 2>/dev/null || true
    chmod -R 777 "/tmp/shairport-sync-${INSTANCE_ID}/.cache" 2>/dev/null || true
    echo "    ✓ Artwork cache: ${ARTWORK_DIR}"

    # Create stream end signal file
    SIGNAL_FILE="/tmp/airplay-${INSTANCE_ID}-stream-end.signal"
    touch "${SIGNAL_FILE}"
    chmod 666 "${SIGNAL_FILE}" 2>/dev/null || true
    chown snapcast:snapcast "${SIGNAL_FILE}" 2>/dev/null || true
    echo "    ✓ Signal file: ${SIGNAL_FILE}"

    # Enable/disable supervisord services based on endpoint enabled state
    # Update airplay-multi-instance.ini to set autostart for this endpoint
    SUPERVISOR_CONFIG="/app/supervisord/airplay-multi-instance.ini"

    if [ "$ENABLED" = "False" ] || [ "$ENABLED" = "false" ]; then
        # Disable all services for this endpoint
        sed -i "/^\[program:shairport-sync-${INSTANCE_ID}\]/,/^$/s/^autostart=true/autostart=false/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
        sed -i "/^\[program:airplay-${INSTANCE_ID}-fifo-keeper\]/,/^$/s/^autostart=true/autostart=false/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
        sed -i "/^\[program:airplay-${INSTANCE_ID}-lifecycle-manager\]/,/^$/s/^autostart=true/autostart=false/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
    else
        # Enable all services for this endpoint
        sed -i "/^\[program:shairport-sync-${INSTANCE_ID}\]/,/^$/s/^autostart=false/autostart=true/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
        sed -i "/^\[program:airplay-${INSTANCE_ID}-fifo-keeper\]/,/^$/s/^autostart=false/autostart=true/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
        sed -i "/^\[program:airplay-${INSTANCE_ID}-lifecycle-manager\]/,/^$/s/^autostart=false/autostart=true/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
    fi
done

# Disable any unconfigured instances (1, 2, 3)
# Get list of configured instance IDs
CONFIGURED_IDS=$(echo "$AIRPLAY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(' '.join([ep['id'] for ep in json.load(sys.stdin)]))")

# Check instances 1, 2, 3 and disable if not configured
for check_id in 1 2 3; do
    if ! echo "$CONFIGURED_IDS" | grep -q "\b${check_id}\b"; then
        echo "Disabling unconfigured instance ${check_id}..."
        SUPERVISOR_CONFIG="/app/supervisord/airplay-multi-instance.ini"
        sed -i "/^\[program:shairport-sync-${check_id}\]/,/^$/s/^autostart=true/autostart=false/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
        sed -i "/^\[program:airplay-${check_id}-fifo-keeper\]/,/^$/s/^autostart=true/autostart=false/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
        sed -i "/^\[program:airplay-${check_id}-lifecycle-manager\]/,/^$/s/^autostart=true/autostart=false/" "$SUPERVISOR_CONFIG" 2>/dev/null || true
    fi
done

echo ""
echo "AirPlay endpoint configuration complete!"
echo ""
echo "Configured endpoints:"
for i in $(seq 0 $((ENDPOINT_COUNT-1))); do
    ENDPOINT_JSON=$(echo "$AIRPLAY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin)[$i]))")
    INSTANCE_ID=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
    ENABLED=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('enabled', True))")
    NAME=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['deviceName'])")

    if [ "$ENABLED" = "False" ] || [ "$ENABLED" = "false" ]; then
        echo "  - Instance ${INSTANCE_ID}: ${NAME} (DISABLED)"
    else
        echo "  - Instance ${INSTANCE_ID}: ${NAME} (ENABLED)"
    fi
done
echo ""
echo "Enabled endpoints will be visible on the network after container start."
