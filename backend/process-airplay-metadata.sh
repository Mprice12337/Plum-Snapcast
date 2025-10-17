#!/bin/bash

METADATA_PIPE="/tmp/shairport-sync-metadata"
METADATA_DIR="/tmp/metadata"
SNAPCAST_API="http://localhost:1780/jsonrpc"

# Ensure metadata directory exists
mkdir -p "$METADATA_DIR"

echo "[INFO] Starting Airplay metadata processor"

# Function to update Snapcast with metadata
update_snapcast_metadata() {
    local key="$1"
    local value="$2"

    # Create JSON file for frontend
    jq -n --arg k "$key" --arg v "$value" \
       '.[$k] = $v' >> "$METADATA_DIR/current.json"

    echo "[METADATA] $key: $value"
}

# Function to handle volume changes
handle_volume() {
    local airplay_volume="$1"
    # Convert AirPlay volume (-30 to 0) to percentage (0 to 100)
    local percent=$(echo "scale=0; ($airplay_volume + 30) * 100 / 30" | bc)

    echo "[VOLUME] Setting to $percent%"

    # Update all clients via Snapcast API
    curl -s -X POST "$SNAPCAST_API" \
        -H "Content-Type: application/json" \
        -d "{
            \"id\": 1,
            \"jsonrpc\": \"2.0\",
            \"method\": \"Group.SetMute\",
            \"params\": {
                \"id\": \"default\",
                \"mute\": false
            }
        }"
}

# Main processing loop
if [ ! -p "$METADATA_PIPE" ]; then
    mkfifo "$METADATA_PIPE"
    chmod 666 "$METADATA_PIPE"
fi

# Use the metadata reader to parse the binary format
shairport-sync-metadata-reader < "$METADATA_PIPE" | while read -r line; do
    # Parse the line format: "key=value"
    if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"

        case "$key" in
            "Artist")
                update_snapcast_metadata "artist" "$value"
                ;;
            "Title")
                update_snapcast_metadata "title" "$value"
                ;;
            "Album")
                update_snapcast_metadata "album" "$value"
                ;;
            "Volume")
                handle_volume "$value"
                ;;
            "Picture")
                # Save album art if provided
                echo "$value" | base64 -d > "$METADATA_DIR/artwork.jpg" 2>/dev/null
                update_snapcast_metadata "artwork" "/tmp/metadata/artwork.jpg"
                ;;
        esac
    fi
done