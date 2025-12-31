#!/bin/bash
# Setup script for multiple AirPlay endpoints
# Reads endpoint configuration from AIRPLAY_ENDPOINTS_JSON env var (exported by get-settings.py)

set -e

echo "Setting up AirPlay endpoints from settings..."

# Generate supervisord config from settings.json
# This dynamically creates program sections for all configured endpoints
echo "Generating supervisord configuration..."
python3 /app/scripts/generate-airplay-supervisord-config.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to generate supervisord configuration"
    exit 1
fi

# Disable old single-instance AirPlay services (migration from v1 to multi-instance)
echo "Disabling legacy single-instance AirPlay services..."
for old_config in /app/supervisord/fifo-keeper.ini /app/supervisord/stream-lifecycle-manager.ini; do
    if [ -f "$old_config" ]; then
        if grep -q "autostart=true" "$old_config"; then
            echo "  - Disabling $(basename $old_config)"
            sed -i 's/autostart=true/autostart=false/' "$old_config"
        fi
    fi
done

# Parse endpoints JSON from environment variable OR directly from settings.json
# AIRPLAY_ENDPOINTS_JSON is set by get-settings.py during container startup
# If not set (e.g., when called by API), read directly from settings.json
if [ -z "$AIRPLAY_ENDPOINTS_JSON" ]; then
    if [ -f "/app/data/settings.json" ]; then
        echo "Reading AirPlay endpoints from settings.json..."
        AIRPLAY_ENDPOINTS_JSON=$(python3 -c "import json; data=json.load(open('/app/data/settings.json')); print(json.dumps(data.get('integrations', {}).get('airplay', {}).get('endpoints', [])))")
    else
        echo "WARNING: No settings.json found, using default single endpoint"
        AIRPLAY_ENDPOINTS_JSON='[{"id":"1","enabled":true,"deviceName":"Plum Audio","port":5050,"udpPortBase":6001}]'
    fi
fi

# Get list of configured endpoint IDs for cleanup
CONFIGURED_IDS=$(echo "$AIRPLAY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(' '.join([ep['id'] for ep in json.load(sys.stdin)]))")
echo "Configured endpoint IDs: $CONFIGURED_IDS"

# Clean up old config files and wrapper scripts for removed endpoints (check 1-10)
echo "Cleaning up old config files..."
for check_id in 1 2 3 4 5 6 7 8 9 10; do
    if ! echo "$CONFIGURED_IDS" | grep -q "\b${check_id}\b"; then
        # Remove config file if it exists
        if [ -f "/app/config/shairport-sync-${check_id}.conf" ]; then
            echo "  Removing old config for endpoint ${check_id}"
            rm -f "/app/config/shairport-sync-${check_id}.conf"
        fi
        # Remove wrapper script if it exists
        if [ -f "/usr/share/snapserver/plug-ins/airplay-control-script-${check_id}.py" ]; then
            echo "  Removing old wrapper script for endpoint ${check_id}"
            rm -f "/usr/share/snapserver/plug-ins/airplay-control-script-${check_id}.py"
        fi
    fi
done

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

    if [ "$ENABLED" = "False" ] || [ "$ENABLED" = "false" ]; then
        echo "  - Instance ${INSTANCE_ID}: DISABLED"
        continue
    fi

    echo "  - Instance ${INSTANCE_ID}: ${NAME} (port ${PORT}, UDP ${UDP_BASE}-$((UDP_BASE+9)), MQTT + D-Bus/MPRIS)"

    # Create config file from template
    CONFIG_FILE="/app/config/shairport-sync-${INSTANCE_ID}.conf"
    sed -e "s/AIRPLAY_NAME/${NAME}/g" \
        -e "s/AIRPLAY_PORT/${PORT}/g" \
        -e "s/AIRPLAY_UDP_BASE/${UDP_BASE}/g" \
        -e "s/INSTANCE_ID/${INSTANCE_ID}/g" \
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
    # CRITICAL: Only create if doesn't exist - don't update mtime of existing files
    # Updating mtime triggers false "active_end" detection in lifecycle manager
    if [ ! -f "${SIGNAL_FILE}" ]; then
        touch "${SIGNAL_FILE}"
        chmod 666 "${SIGNAL_FILE}" 2>/dev/null || true
        chown snapcast:snapcast "${SIGNAL_FILE}" 2>/dev/null || true
        echo "    ✓ Signal file created: ${SIGNAL_FILE}"
    else
        echo "    ✓ Signal file exists: ${SIGNAL_FILE}"
    fi

    # Create instance-specific control script wrapper
    # Snapcast's JSON-RPC API doesn't support arguments in controlscript parameter,
    # so we create a wrapper script that calls the main script with --instance-id
    WRAPPER_SCRIPT="/usr/share/snapserver/plug-ins/airplay-control-script-${INSTANCE_ID}.py"
    cat > "${WRAPPER_SCRIPT}" <<EOF
#!/usr/bin/env python3
"""Wrapper script for AirPlay instance ${INSTANCE_ID}"""
import sys
import os
# Execute main control script with instance ID
os.execv("/usr/share/snapserver/plug-ins/airplay-control-script.py",
         ["/usr/share/snapserver/plug-ins/airplay-control-script.py", "--instance-id", "${INSTANCE_ID}"])
EOF
    chmod +x "${WRAPPER_SCRIPT}"
    echo "    ✓ Control script wrapper: ${WRAPPER_SCRIPT}"
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
