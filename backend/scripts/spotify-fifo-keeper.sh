#!/bin/bash
set -e

# Spotify FIFO Keeper
# Prevents spotifyd from blocking when writing to FIFO when no Snapcast stream exists
# Continuously reads and discards data from FIFO when stream is not active

# Get instance ID from first argument (for multi-instance mode)
INSTANCE_ID="$1"

if [ -n "$INSTANCE_ID" ]; then
    # Multi-instance mode
    FIFO_PATH="/tmp/spotify-${INSTANCE_ID}-fifo"

    # Get endpoint name from settings.json for stream name matching
    if [ -f "/app/data/settings.json" ]; then
        ENDPOINT_NAME=$(python3 -c "
import json
try:
    with open('/app/data/settings.json', 'r') as f:
        settings = json.load(f)
        endpoints = settings.get('integrations', {}).get('spotify', {}).get('endpoints', [])
        for ep in endpoints:
            if ep.get('id') == '${INSTANCE_ID}':
                print(ep.get('deviceName', 'Endpoint ${INSTANCE_ID}'))
                break
        else:
            print('Endpoint ${INSTANCE_ID}')
except:
    print('Endpoint ${INSTANCE_ID}')
" 2>/dev/null)
    else
        ENDPOINT_NAME="Endpoint ${INSTANCE_ID}"
    fi

    STREAM_NAME="Spotify - ${ENDPOINT_NAME}"
else
    # Single-instance mode (legacy)
    FIFO_PATH="/tmp/spotifyfifo"
    STREAM_NAME="Spotify"
fi

CHECK_INTERVAL=1

echo "[Spotify FIFO Keeper] Starting for $FIFO_PATH (stream: $STREAM_NAME)"

while true; do
    # Check if Spotify stream exists in Snapcast
    # Use HTTP JSON-RPC to query server status
    if ! curl -s http://localhost:1780/jsonrpc -H "Content-Type: application/json" -d '{
        "jsonrpc": "2.0",
        "method": "Server.GetStatus",
        "id": 1
    }' | grep -q "\"name\":\"$STREAM_NAME\""; then
        # No stream - read and discard FIFO data to prevent spotifyd from blocking
        # Use timeout to prevent hanging if pipe is empty
        timeout 1 cat "$FIFO_PATH" > /dev/null 2>&1 || true
    fi

    # Brief sleep to prevent excessive CPU usage
    sleep "$CHECK_INTERVAL"
done
