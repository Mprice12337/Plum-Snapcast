#!/bin/bash
set -e

# DLNA FIFO Keeper
# Prevents gmrender-resurrect from blocking when writing to FIFO when no Snapcast stream exists
# Continuously reads and discards data from FIFO when stream is not active
#
# Multi-Instance Support:
# - Takes instance ID as first argument: $1
# - Each instance has its own FIFO and stream name
# - Stream name format: "DLNA - {deviceName}" (e.g., "DLNA - Living Room")

INSTANCE_ID="$1"

if [ -n "$INSTANCE_ID" ]; then
    # Multi-instance mode
    FIFO_PATH="/tmp/dlna-${INSTANCE_ID}-fifo"

    # Get device name from settings.json for stream name matching
    DEVICE_NAME=$(python3 -c "
import json, sys
try:
    with open('/app/data/settings.json', 'r') as f:
        settings = json.load(f)
    endpoints = settings.get('integrations', {}).get('dlna', {}).get('endpoints', [])
    for ep in endpoints:
        if ep.get('id') == '$INSTANCE_ID':
            print(ep.get('deviceName', 'DLNA $INSTANCE_ID'))
            sys.exit(0)
    print('DLNA $INSTANCE_ID')
except:
    print('DLNA $INSTANCE_ID')
" 2>/dev/null || echo "DLNA ${INSTANCE_ID}")

    STREAM_NAME="DLNA - ${DEVICE_NAME}"
else
    # Single instance mode (legacy)
    FIFO_PATH="/tmp/dlna-fifo"
    STREAM_NAME="DLNA"
fi

CHECK_INTERVAL=1

echo "[DLNA FIFO Keeper] Starting for $FIFO_PATH (stream: $STREAM_NAME)"

while true; do
    # Check if DLNA stream exists in Snapcast
    # Use HTTP JSON-RPC to query server status
    if ! curl -s http://localhost:1780/jsonrpc -H "Content-Type: application/json" -d '{
        "jsonrpc": "2.0",
        "method": "Server.GetStatus",
        "id": 1
    }' | grep -q "\"name\":\"$STREAM_NAME\""; then
        # No stream - read and discard FIFO data to prevent gmrender from blocking
        # Use timeout to prevent hanging if pipe is empty
        timeout 1 cat "$FIFO_PATH" > /dev/null 2>&1 || true
    fi

    # Brief sleep to prevent excessive CPU usage
    sleep "$CHECK_INTERVAL"
done
