#!/bin/bash
# Plexamp Entrypoint Script
# Waits for FIFO reader before starting Plexamp to prevent "Broken pipe" errors

FIFO_PATH="/tmp/snapcast-fifos/plexamp-fifo"
MAX_WAIT=60  # Maximum seconds to wait

echo "[Plexamp Entrypoint] Waiting for FIFO reader..."

# Wait for FIFO to exist
elapsed=0
while [ ! -p "$FIFO_PATH" ]; do
    if [ $elapsed -ge $MAX_WAIT ]; then
        echo "[Plexamp Entrypoint] WARNING: FIFO not found after ${MAX_WAIT}s, starting anyway"
        break
    fi
    echo "[Plexamp Entrypoint] Waiting for FIFO at $FIFO_PATH..."
    sleep 2
    elapsed=$((elapsed + 2))
done

# Wait for a reader to be available (non-blocking write test)
# When there's no reader, opening FIFO for writing blocks or fails
elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
    # Try to open FIFO for writing with timeout
    # If successful, a reader exists
    if timeout 1 bash -c "echo -n '' > '$FIFO_PATH'" 2>/dev/null; then
        echo "[Plexamp Entrypoint] FIFO reader detected, starting Plexamp"
        break
    fi

    echo "[Plexamp Entrypoint] No FIFO reader yet, waiting... (${elapsed}s)"
    sleep 2
    elapsed=$((elapsed + 2))
done

if [ $elapsed -ge $MAX_WAIT ]; then
    echo "[Plexamp Entrypoint] WARNING: No FIFO reader after ${MAX_WAIT}s, starting anyway"
fi

# Start Plexamp
exec /usr/bin/node /opt/plexamp/js/index.js
