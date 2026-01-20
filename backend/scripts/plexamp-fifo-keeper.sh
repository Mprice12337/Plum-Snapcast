#!/bin/bash
set -e

# Plexamp FIFO Keeper
# Prevents Plexamp from getting "Broken pipe" errors when writing to FIFO
# when no Snapcast stream exists (stream not yet created or timed out)
#
# This script continuously reads and discards data from the FIFO when the
# Plexamp Snapcast stream doesn't exist, providing a fallback reader.
#
# CRITICAL: This must start BEFORE Plexamp to ensure there's always a reader
# when Plexamp first opens the FIFO.

FIFO_PATH="/tmp/snapcast-fifos/plexamp-fifo"
STREAM_NAME="Plexamp"
CHECK_INTERVAL=1

echo "[Plexamp FIFO Keeper] Starting for $FIFO_PATH (stream: $STREAM_NAME)"

# Wait for FIFO to exist
while [ ! -p "$FIFO_PATH" ]; do
    echo "[Plexamp FIFO Keeper] Waiting for FIFO at $FIFO_PATH..."
    sleep 2
done

echo "[Plexamp FIFO Keeper] FIFO exists, starting monitoring loop"

while true; do
    # Check if Plexamp stream exists in Snapcast
    # Use HTTP JSON-RPC to query server status
    STREAM_EXISTS=$(curl -s http://localhost:1780/jsonrpc -H "Content-Type: application/json" -d '{
        "jsonrpc": "2.0",
        "method": "Server.GetStatus",
        "id": 1
    }' 2>/dev/null | grep -c "\"id\":\"$STREAM_NAME\"" || echo "0")

    if [ "$STREAM_EXISTS" = "0" ]; then
        # No stream - read and discard FIFO data to prevent Plexamp from getting "Broken pipe"
        # Use timeout to prevent hanging if pipe is empty
        # Read in a loop to continuously drain the FIFO
        timeout 1 cat "$FIFO_PATH" > /dev/null 2>&1 || true
    fi

    # Brief sleep to prevent excessive CPU usage
    sleep "$CHECK_INTERVAL"
done
