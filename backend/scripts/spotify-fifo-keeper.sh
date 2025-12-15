#!/bin/bash
set -e

# Spotify FIFO Keeper
# Prevents spotifyd from blocking when writing to FIFO when no Snapcast stream exists
# Continuously reads and discards data from FIFO when stream is not active

FIFO_PATH="/tmp/spotifyfifo"
STREAM_NAME="Spotify"
CHECK_INTERVAL=1

echo "[Spotify FIFO Keeper] Starting for $FIFO_PATH"

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
