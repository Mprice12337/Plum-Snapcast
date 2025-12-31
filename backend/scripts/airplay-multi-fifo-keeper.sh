#!/bin/bash
# FIFO Keeper for AirPlay Multi-Instance
# Prevents shairport-sync from blocking when no Snapcast stream is consuming the FIFO
# Usage: airplay-multi-fifo-keeper.sh <instance-id>

INSTANCE_ID="$1"

if [ -z "$INSTANCE_ID" ]; then
    echo "ERROR: Instance ID required"
    echo "Usage: $0 <instance-id>"
    exit 1
fi

FIFO_PATH="/tmp/airplay-${INSTANCE_ID}-fifo"

echo "AirPlay Instance ${INSTANCE_ID} FIFO Keeper starting..."
echo "FIFO: ${FIFO_PATH}"

# Wait for FIFO to exist
while [ ! -p "${FIFO_PATH}" ]; do
    echo "Waiting for FIFO: ${FIFO_PATH}"
    sleep 1
done

echo "FIFO found: ${FIFO_PATH}"

# Continuously read and discard data
# This keeps the pipe open so shairport-sync doesn't block
# when no Snapcast stream is actively reading
while true; do
    cat "${FIFO_PATH}" > /dev/null 2>&1
    # If cat exits (pipe closed), wait briefly and retry
    sleep 0.1
done
