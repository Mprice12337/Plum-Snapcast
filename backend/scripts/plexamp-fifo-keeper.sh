#!/bin/bash
set -e

# Plexamp FIFO Keeper
# Prevents Plexamp from getting "Broken pipe" errors when writing to FIFO
# when no Snapcast stream exists (stream not yet created or timed out)
#
# This script continuously reads and discards data from the FIFO when the
# Plexamp Snapcast stream doesn't exist, providing a fallback reader.
#
# CRITICAL: Uses background cat process for continuous reading to ensure
# there's always a reader available (no gaps for Plexamp entrypoint probe).

FIFO_PATH="/tmp/snapcast-fifos/plexamp-fifo"
STREAM_NAME="Plexamp"
CHECK_INTERVAL=2
CAT_PID=""

echo "[Plexamp FIFO Keeper] Starting for $FIFO_PATH (stream: $STREAM_NAME)"

# Cleanup function
cleanup() {
    if [ -n "$CAT_PID" ] && kill -0 "$CAT_PID" 2>/dev/null; then
        kill "$CAT_PID" 2>/dev/null || true
    fi
    exit 0
}
trap cleanup EXIT INT TERM

# Wait for FIFO to exist
while [ ! -p "$FIFO_PATH" ]; do
    echo "[Plexamp FIFO Keeper] Waiting for FIFO at $FIFO_PATH..."
    sleep 2
done

echo "[Plexamp FIFO Keeper] FIFO exists, starting monitoring loop"

# Start initial background reader (always have a reader available)
cat "$FIFO_PATH" > /dev/null 2>&1 &
CAT_PID=$!
echo "[Plexamp FIFO Keeper] Started background reader (PID $CAT_PID)"

while true; do
    # Check if Plexamp stream exists in Snapcast
    # Use explicit check: get status, look for stream with our ID in the streams array
    RESPONSE=$(curl -s -m 3 http://localhost:1780/jsonrpc -H "Content-Type: application/json" -d '{
        "jsonrpc": "2.0",
        "method": "Server.GetStatus",
        "id": 1
    }' 2>/dev/null || echo "")

    # Check if response contains our stream in the streams section
    # The stream ID appears as "id":"Plexamp" within the streams array
    if echo "$RESPONSE" | grep -q '"streams".*"id":"'"$STREAM_NAME"'"'; then
        STREAM_EXISTS="1"
    else
        STREAM_EXISTS="0"
    fi

    if [ "$STREAM_EXISTS" = "1" ]; then
        # Stream exists - Snapserver is reading, stop our reader
        if [ -n "$CAT_PID" ] && kill -0 "$CAT_PID" 2>/dev/null; then
            echo "[Plexamp FIFO Keeper] Stream exists, stopping background reader"
            kill "$CAT_PID" 2>/dev/null || true
            CAT_PID=""
        fi
    else
        # No stream - ensure background reader is running
        if [ -z "$CAT_PID" ] || ! kill -0 "$CAT_PID" 2>/dev/null; then
            cat "$FIFO_PATH" > /dev/null 2>&1 &
            CAT_PID=$!
            echo "[Plexamp FIFO Keeper] Stream absent, started background reader (PID $CAT_PID)"
        fi
    fi

    sleep "$CHECK_INTERVAL"
done
