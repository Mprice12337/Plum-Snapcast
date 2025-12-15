#!/bin/sh
# FIFO Keeper - Keeps FIFO pipe open for reading to prevent blocking writers
# This allows shairport-sync to write audio even when no Snapcast stream exists

FIFO_PATH="${1:-/tmp/snapfifo}"

echo "[FIFO Keeper] Starting for: $FIFO_PATH"

# Ensure FIFO exists
if [ ! -p "$FIFO_PATH" ]; then
    echo "[FIFO Keeper] ERROR: $FIFO_PATH is not a FIFO pipe"
    exit 1
fi

# Continuously read and discard data from FIFO
# This keeps the pipe open and prevents writers from blocking
while true; do
    # Read from FIFO and discard to /dev/null
    # If the FIFO closes (e.g., writer disconnects), cat will exit and loop will restart
    cat "$FIFO_PATH" > /dev/null 2>&1

    # Small delay before reopening to prevent tight loop
    sleep 0.1
done
