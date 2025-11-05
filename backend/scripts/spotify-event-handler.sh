#!/bin/bash
#
# Spotify Event Handler for Librespot
# This script is called by librespot via --onevent parameter
# It receives metadata via environment variables and writes it to a JSON file
#

METADATA_FILE="/tmp/spotify-metadata.json"
LOG_FILE="/var/log/supervisord/spotify-events.log"

# Log function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# Log the event
log "Received event: PLAYER_EVENT=${PLAYER_EVENT}"

# Process the event
case "${PLAYER_EVENT}" in
    start|load|change)
        # Track changed or started playing
        log "Track info: ${TITLE} - ${ARTIST} (${ALBUM})"

        # Write metadata to JSON file for control script to read
        cat > "${METADATA_FILE}.tmp" <<EOF
{
  "event": "${PLAYER_EVENT}",
  "title": "${TITLE}",
  "artist": "${ARTIST}",
  "album": "${ALBUM}",
  "album_artist": "${ALBUM_ARTIST}",
  "track_id": "${TRACK_ID}",
  "cover_url": "${COVER_URL}",
  "duration_ms": "${DURATION_MS}",
  "position_ms": "${POSITION_MS}",
  "timestamp": $(date +%s)
}
EOF
        # Atomic move to prevent partial reads
        mv "${METADATA_FILE}.tmp" "${METADATA_FILE}"
        chmod 666 "${METADATA_FILE}"
        log "Metadata written to ${METADATA_FILE}"
        ;;

    playing)
        log "Playback started"
        echo "{\"event\": \"playing\", \"timestamp\": $(date +%s)}" > "${METADATA_FILE}"
        chmod 666 "${METADATA_FILE}"
        ;;

    paused)
        log "Playback paused"
        echo "{\"event\": \"paused\", \"timestamp\": $(date +%s)}" > "${METADATA_FILE}"
        chmod 666 "${METADATA_FILE}"
        ;;

    stopped)
        log "Playback stopped"
        echo "{\"event\": \"stopped\", \"timestamp\": $(date +%s)}" > "${METADATA_FILE}"
        chmod 666 "${METADATA_FILE}"
        ;;

    volume_set)
        log "Volume changed to: ${VOLUME}"
        ;;

    *)
        log "Unknown event: ${PLAYER_EVENT}"
        ;;
esac

exit 0
