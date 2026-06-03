#!/bin/bash
# Wrapper script for spotifyd that waits for Avahi to be ready
# This ensures zeroconf (mDNS) service advertising works properly for Spotify Connect discovery

# Don't use set -e because we want to handle avahi-browse failures gracefully

# Get the instance ID from argument (e.g., "1" for spotifyd-1)
INSTANCE_ID="${1:-}"
shift  # Remove instance ID from args, rest goes to spotifyd

if [ -z "$INSTANCE_ID" ]; then
    echo "[$(date)] ERROR: Instance ID required as first argument" >&2
    exit 1
fi

CONFIG_PATH="/app/config/spotifyd-${INSTANCE_ID}.conf"

if [ ! -f "$CONFIG_PATH" ]; then
    echo "[$(date)] ERROR: Config file not found: $CONFIG_PATH" >&2
    exit 1
fi

echo "[$(date)] [spotifyd-${INSTANCE_ID}] Waiting for Avahi to be ready for zeroconf discovery..." >&2

# Wait up to 60 seconds for Avahi D-Bus to be fully operational
for i in {1..60}; do
    # Run avahi-browse and capture output
    # When Avahi D-Bus is ready, avahi-browse will output service lines (starting with +/=/-)
    # When Avahi is not ready, we get "Daemon not running" or no output
    OUTPUT=$(timeout 2 avahi-browse -a -t 2>&1 || true)

    # Check if we got any valid output (lines starting with + or = or -)
    # This indicates Avahi D-Bus is responding
    if echo "$OUTPUT" | grep -q "^[+=-]"; then
        echo "[$(date)] [spotifyd-${INSTANCE_ID}] Avahi is ready and discovering services!" >&2
        break
    elif echo "$OUTPUT" | grep -q "Daemon not running"; then
        echo "[$(date)] [spotifyd-${INSTANCE_ID}] Waiting for Avahi daemon... ($i/60)" >&2
        sleep 1
    else
        # No output or unexpected output - Avahi might not be started yet
        echo "[$(date)] [spotifyd-${INSTANCE_ID}] Waiting for Avahi D-Bus... ($i/60)" >&2
        sleep 1
    fi

    # Check if we've exhausted all retries
    if [ $i -eq 60 ]; then
        echo "[$(date)] [spotifyd-${INSTANCE_ID}] WARNING: Avahi not responding after 60 seconds, starting anyway..." >&2
    fi
done

# Extra grace period for Avahi to be fully ready for registrations
echo "[$(date)] [spotifyd-${INSTANCE_ID}] Waiting 3 seconds for Avahi registration readiness..." >&2
sleep 3

echo "[$(date)] [spotifyd-${INSTANCE_ID}] Starting spotifyd with config: $CONFIG_PATH" >&2
exec /usr/local/bin/spotifyd --no-daemon --config-path "$CONFIG_PATH" "$@"
