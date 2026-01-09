#!/bin/bash
# One-time script to restart snapserver after Avahi is fully initialized
# This ensures zeroconf advertising works on initial container startup

echo "[$(date)] Snapserver Avahi Restart Service: Waiting for Avahi to be ready..."

# Wait for Avahi to be fully operational (up to 90 seconds)
for i in {1..90}; do
    # Check if avahi-browse can discover services
    OUTPUT=$(timeout 1 avahi-browse -a -t 2>&1 || true)

    if echo "$OUTPUT" | grep -q "^[+=-]"; then
        echo "[$(date)] Avahi is ready and discovering services!"
        break
    fi

    sleep 1
done

# Extra delay to ensure Avahi service publishing is fully initialized
echo "[$(date)] Waiting additional 10 seconds for Avahi stability..."
sleep 10

# Restart snapserver to pick up Avahi
echo "[$(date)] Restarting snapserver to enable zeroconf advertising..."
supervisorctl -c /app/supervisord/supervisord.conf restart snapserver

echo "[$(date)] Snapserver restarted successfully. Zeroconf should now be active."

# Exit so supervisord doesn't restart this one-time service
exit 0
