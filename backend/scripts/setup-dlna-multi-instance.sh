#!/bin/bash
# Setup script for multiple DLNA/UPnP endpoints
# Reads endpoint configuration from DLNA_ENDPOINTS_JSON env var (exported by get-settings.py)

set -e

echo "Setting up DLNA endpoints from settings..."

# Generate supervisord config from settings.json
# This dynamically creates program sections for all configured endpoints
echo "Generating supervisord configuration..."
python3 /app/scripts/generate-dlna-supervisord-config.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to generate supervisord configuration"
    exit 1
fi

# Disable old single-instance DLNA service (migration to multi-instance)
echo "Disabling legacy single-instance DLNA service..."
if [ -f "/app/supervisord/gmrender.ini" ]; then
    if grep -q "autostart=true" "/app/supervisord/gmrender.ini"; then
        echo "  - Disabling gmrender.ini"
        sed -i 's/autostart=true/autostart=false/' "/app/supervisord/gmrender.ini"
    fi
fi

# Parse endpoints JSON from environment variable OR directly from settings.json
# DLNA_ENDPOINTS_JSON is set by get-settings.py during container startup
# If not set (e.g., when called by API), read directly from settings.json
if [ -z "$DLNA_ENDPOINTS_JSON" ]; then
    if [ -f "/app/data/settings.json" ]; then
        echo "Reading DLNA endpoints from settings.json..."
        DLNA_ENDPOINTS_JSON=$(python3 -c "import json; data=json.load(open('/app/data/settings.json')); print(json.dumps(data.get('integrations', {}).get('dlna', {}).get('endpoints', [])))")
    else
        echo "WARNING: No settings.json found, using default single endpoint"
        DLNA_ENDPOINTS_JSON='[{"id":"1","enabled":true,"deviceName":"Plum Audio","port":49494,"uuid":""}]'
    fi
fi

# Get list of configured endpoint IDs for cleanup
CONFIGURED_IDS=$(echo "$DLNA_ENDPOINTS_JSON" | python3 -c "import sys, json; print(' '.join([ep['id'] for ep in json.load(sys.stdin)]))")
echo "Configured endpoint IDs: $CONFIGURED_IDS"

# Clean up old resources for removed endpoints (check 1-10)
echo "Cleaning up old resources..."
for check_id in 1 2 3 4 5 6 7 8 9 10; do
    if ! echo "$CONFIGURED_IDS" | grep -q "\b${check_id}\b"; then
        # Remove FIFO if it exists
        if [ -p "/tmp/dlna-${check_id}-fifo" ]; then
            echo "  Removing old FIFO for endpoint ${check_id}"
            rm -f "/tmp/dlna-${check_id}-fifo"
        fi
        # Remove metadata file if it exists
        if [ -f "/tmp/dlna-${check_id}-metadata.json" ]; then
            echo "  Removing old metadata file for endpoint ${check_id}"
            rm -f "/tmp/dlna-${check_id}-metadata.json"
        fi
        # Remove wrapper script if it exists
        if [ -f "/usr/share/snapserver/plug-ins/dlna-control-script-${check_id}.py" ]; then
            echo "  Removing old wrapper script for endpoint ${check_id}"
            rm -f "/usr/share/snapserver/plug-ins/dlna-control-script-${check_id}.py"
        fi
    fi
done

# Parse JSON array to get endpoint count
ENDPOINT_COUNT=$(echo "$DLNA_ENDPOINTS_JSON" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")

if [ "$ENDPOINT_COUNT" -eq 0 ]; then
    echo "No DLNA endpoints configured"
    exit 0
fi

echo "Configuring $ENDPOINT_COUNT DLNA endpoint(s):"

# Process each endpoint
for i in $(seq 0 $((ENDPOINT_COUNT-1))); do
    # Extract endpoint properties using python3
    ENDPOINT_JSON=$(echo "$DLNA_ENDPOINTS_JSON" | python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin)[$i]))")

    INSTANCE_ID=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
    ENABLED=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('enabled', True))")
    NAME=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['deviceName'])")
    PORT=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['port'])")
    UUID=$(echo "$ENDPOINT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('uuid', ''))")

    if [ "$ENABLED" = "False" ] || [ "$ENABLED" = "false" ]; then
        echo "  - Instance ${INSTANCE_ID}: DISABLED"
        continue
    fi

    echo "  - Instance ${INSTANCE_ID}: ${NAME} (port ${PORT}, UPnP discovery via Avahi)"

    # Create FIFO pipe for audio output
    FIFO_PATH="/tmp/dlna-${INSTANCE_ID}-fifo"
    if [ ! -p "$FIFO_PATH" ]; then
        mkfifo "$FIFO_PATH"
        chmod 666 "$FIFO_PATH"
        chown snapcast:snapcast "$FIFO_PATH"
        echo "    Created FIFO: $FIFO_PATH"
    fi

    # Ensure wrapper script directory exists
    mkdir -p /usr/share/snapserver/plug-ins

    # Create control script wrapper (works around Snapcast's no-arguments limitation)
    # Snapcast calls control scripts without arguments, so we use a wrapper that adds --instance-id
    WRAPPER_SCRIPT="/usr/share/snapserver/plug-ins/dlna-control-script-${INSTANCE_ID}.py"
    cat > "$WRAPPER_SCRIPT" <<EOF
#!/usr/bin/env python3
# Auto-generated wrapper for DLNA control script instance ${INSTANCE_ID}
# Snapcast limitation: control scripts can't take arguments, so we use execv to pass --instance-id
import sys, os
os.execv(
    "/usr/share/snapserver/plug-ins/dlna-control-script.py",
    ["/usr/share/snapserver/plug-ins/dlna-control-script.py", "--instance-id", "${INSTANCE_ID}"]
)
EOF
    chmod +x "$WRAPPER_SCRIPT"
    echo "    Created wrapper: $WRAPPER_SCRIPT"
done

echo "DLNA multi-instance setup complete"
exit 0
