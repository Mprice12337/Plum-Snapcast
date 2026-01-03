#!/bin/bash
# Wrapper script for snapserver that waits for Avahi to be ready
# This ensures zeroconf (mDNS) service advertising works properly

# Don't use set -e because we want to handle avahi-browse failures gracefully

# Initial delay to let D-Bus and Avahi start (higher priority services)
echo "[$(date)] Giving D-Bus and Avahi time to start..." >&2
sleep 15

echo "[$(date)] Waiting for Avahi D-Bus to be ready..." >&2

# Wait up to 90 seconds for Avahi D-Bus to be fully operational
for i in {1..90}; do
    # Run avahi-browse and capture output
    # When Avahi D-Bus is ready, avahi-browse will output service lines (starting with +/=/-)
    # When Avahi is not ready, we get "Daemon not running" or no output
    OUTPUT=$(timeout 1 avahi-browse -a -t 2>&1 || true)

    # Check if we got any valid output (lines starting with + or = or -)
    # This indicates Avahi D-Bus is responding
    if echo "$OUTPUT" | grep -q "^[+=-]"; then
        echo "[$(date)] Avahi D-Bus is responding and discovering services!" >&2
        break
    elif echo "$OUTPUT" | grep -q "Daemon not running"; then
        echo "[$(date)] Waiting for Avahi daemon to start... ($i/90)" >&2
        sleep 1
    else
        # No output or unexpected output - Avahi might not be started yet
        echo "[$(date)] Waiting for Avahi D-Bus... ($i/90)" >&2
        sleep 1
    fi

    # Check if we've exhausted all retries
    if [ $i -eq 90 ]; then
        echo "[$(date)] WARNING: Avahi D-Bus not responding after 90 seconds, starting anyway..." >&2
    fi
done

# Extra grace period for Avahi to fully initialize service publishing
echo "[$(date)] Waiting additional 5 seconds for Avahi stability..." >&2
sleep 5

echo "[$(date)] Starting Snapserver..." >&2
exec /usr/bin/snapserver "$@"
