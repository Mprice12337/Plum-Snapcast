#!/bin/bash
# Setup script for multiple Spotify Connect endpoints
# Reads endpoint configuration from SPOTIFY_ENDPOINTS_JSON env var (exported by get-settings.py)

set -e

echo "Setting up Spotify Connect endpoints from settings..."

# Generate supervisord config from settings.json
# This dynamically creates program sections for all configured endpoints
echo "Generating supervisord configuration..."
python3 /app/scripts/generate-spotify-supervisord-config.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to generate supervisord configuration"
    exit 1
fi

# Disable old single-instance Spotify services (migration from v1 to multi-instance)
echo "Disabling legacy single-instance Spotify services..."
for old_config in /app/supervisord/spotifyd.ini /app/supervisord/spotify-fifo-keeper.ini /app/supervisord/spotify-stream-lifecycle-manager.ini; do
    if [ -f "$old_config" ]; then
        if grep -q "autostart=true" "$old_config"; then
            echo "  - Disabling $(basename $old_config)"
            sed -i 's/autostart=true/autostart=false/' "$old_config"
        fi
    fi
done

# Parse endpoints JSON from environment variable OR directly from settings.json
# SPOTIFY_ENDPOINTS_JSON is set by get-settings.py during container startup
# If not set (e.g., when called by API), read directly from settings.json
if [ -z "$SPOTIFY_ENDPOINTS_JSON" ]; then
    if [ -f "/app/data/settings.json" ]; then
        echo "Reading Spotify endpoints from settings.json..."
        SPOTIFY_ENDPOINTS_JSON=$(python3 -c "import json; data=json.load(open('/app/data/settings.json')); print(json.dumps(data.get('integrations', {}).get('spotify', {}).get('endpoints', [])))")
    else
        echo "WARNING: No settings.json found, using default single endpoint"
        SPOTIFY_ENDPOINTS_JSON='[{"id":"1","enabled":false,"deviceName":"Plum Audio","zeroconfPort":5354}]'
    fi
fi

# Get bitrate from settings (shared across all endpoints)
if [ -z "$SPOTIFY_BITRATE" ]; then
    if [ -f "/app/data/settings.json" ]; then
        SPOTIFY_BITRATE=$(python3 -c "import json; data=json.load(open('/app/data/settings.json')); print(data.get('integrations', {}).get('spotify', {}).get('bitrate', 320))")
    else
        SPOTIFY_BITRATE=320
    fi
fi
echo "Using bitrate: ${SPOTIFY_BITRATE} kbps (shared across all endpoints)"

# Get list of configured endpoint IDs for cleanup
CONFIGURED_IDS=$(echo "$SPOTIFY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(' '.join([ep['id'] for ep in json.load(sys.stdin)]))")
echo "Configured endpoint IDs: $CONFIGURED_IDS"

# Clean up old config files and wrapper scripts for removed endpoints (check 1-10)
echo "Cleaning up old config files..."
for check_id in 1 2 3 4 5 6 7 8 9 10; do
    if ! echo "$CONFIGURED_IDS" | grep -q "\b${check_id}\b"; then
        # Remove config file if it exists
        if [ -f "/app/config/spotifyd-${check_id}.conf" ]; then
            echo "  Removing old config for endpoint ${check_id}"
            rm -f "/app/config/spotifyd-${check_id}.conf"
        fi
        # Remove wrapper script if it exists
        if [ -f "/usr/share/snapserver/plug-ins/spotify-control-script-${check_id}.py" ]; then
            echo "  Removing old wrapper script for endpoint ${check_id}"
            rm -f "/usr/share/snapserver/plug-ins/spotify-control-script-${check_id}.py"
        fi
        # Remove FIFO if it exists
        if [ -p "/tmp/spotify-${check_id}-fifo" ]; then
            echo "  Removing old FIFO for endpoint ${check_id}"
            rm -f "/tmp/spotify-${check_id}-fifo"
        fi
        # Remove cache directory if it exists
        if [ -d "/tmp/spotify-${check_id}-cache" ]; then
            echo "  Removing old cache for endpoint ${check_id}"
            rm -rf "/tmp/spotify-${check_id}-cache"
        fi
    fi
done

# Parse JSON array into bash arrays
# Each endpoint has: id, enabled, deviceName, zeroconfPort
ENDPOINT_COUNT=$(echo "$SPOTIFY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")

if [ "$ENDPOINT_COUNT" -eq 0 ]; then
    echo "No Spotify Connect endpoints configured"
    exit 0
fi

echo "Configuring $ENDPOINT_COUNT Spotify Connect endpoint(s):"

# Process each endpoint
for i in $(seq 0 $((ENDPOINT_COUNT-1))); do
    # Extract endpoint properties using python3
    ENDPOINT_JSON=$(echo "$SPOTIFY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin)[$i]))")

    INSTANCE_ID=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
    ENABLED=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('enabled', False))")
    NAME=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['deviceName'])")
    ZEROCONF_PORT=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['zeroconfPort'])")

    if [ "$ENABLED" = "False" ] || [ "$ENABLED" = "false" ]; then
        echo "  - Instance ${INSTANCE_ID}: DISABLED"
        continue
    fi

    echo "  - Instance ${INSTANCE_ID}: ${NAME} (zeroconf port ${ZEROCONF_PORT}, ${SPOTIFY_BITRATE} kbps, D-Bus/MPRIS)"

    # Create config file from template
    CONFIG_FILE="/app/config/spotifyd-${INSTANCE_ID}.conf"
    sed -e "s/SPOTIFY_NAME/${NAME}/g" \
        -e "s/INSTANCE_ID/${INSTANCE_ID}/g" \
        -e "s/SPOTIFY_ZEROCONF_PORT/${ZEROCONF_PORT}/g" \
        -e "s/SPOTIFY_BITRATE/${SPOTIFY_BITRATE}/g" \
        /app/config/spotifyd.conf.template > "${CONFIG_FILE}"

    # Ensure config file is owned by snapcast user (for dynamic updates via API)
    chown snapcast:snapcast "${CONFIG_FILE}" 2>/dev/null || true
    chmod 644 "${CONFIG_FILE}" 2>/dev/null || true

    echo "    ✓ Config: ${CONFIG_FILE}"

    # Create FIFO pipe for audio
    FIFO_PATH="/tmp/spotify-${INSTANCE_ID}-fifo"
    if [ ! -p "${FIFO_PATH}" ]; then
        mkfifo "${FIFO_PATH}"
        chmod 666 "${FIFO_PATH}"
        chown snapcast:snapcast "${FIFO_PATH}" 2>/dev/null || true
        echo "    ✓ Audio FIFO: ${FIFO_PATH}"
    fi

    # Create spotifyd cache directory
    CACHE_DIR="/tmp/spotify-${INSTANCE_ID}-cache"
    mkdir -p "${CACHE_DIR}"
    chown -R snapcast:snapcast "${CACHE_DIR}" 2>/dev/null || true
    chmod -R 755 "${CACHE_DIR}" 2>/dev/null || true
    echo "    ✓ Cache directory: ${CACHE_DIR}"

    # Create instance-specific control script wrapper
    # Snapcast's JSON-RPC API doesn't support arguments in controlscript parameter,
    # so we create a wrapper script that calls the main script with --instance-id
    WRAPPER_SCRIPT="/usr/share/snapserver/plug-ins/spotify-control-script-${INSTANCE_ID}.py"
    cat > "${WRAPPER_SCRIPT}" <<EOF
#!/usr/bin/env python3
"""Wrapper script for Spotify Connect instance ${INSTANCE_ID}"""
import sys
import os
# Execute main control script with instance ID
os.execv("/usr/share/snapserver/plug-ins/spotify-control-script.py",
         ["/usr/share/snapserver/plug-ins/spotify-control-script.py", "--instance-id", "${INSTANCE_ID}"])
EOF
    chmod +x "${WRAPPER_SCRIPT}"
    echo "    ✓ Control script wrapper: ${WRAPPER_SCRIPT}"
done

echo ""
echo "Spotify Connect endpoint configuration complete!"
echo ""
echo "Configured endpoints:"
for i in $(seq 0 $((ENDPOINT_COUNT-1))); do
    ENDPOINT_JSON=$(echo "$SPOTIFY_ENDPOINTS_JSON" | python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin)[$i]))")
    INSTANCE_ID=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
    ENABLED=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('enabled', False))")
    NAME=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['deviceName'])")

    if [ "$ENABLED" = "False" ] || [ "$ENABLED" = "false" ]; then
        echo "  - Instance ${INSTANCE_ID}: ${NAME} (DISABLED)"
    else
        echo "  - Instance ${INSTANCE_ID}: ${NAME} (ENABLED - will be visible on network)"
    fi
done
echo ""
