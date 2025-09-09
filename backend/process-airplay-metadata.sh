#!/bin/bash

# AirPlay metadata processor for Snapcast
# This script reads metadata from shairport-sync and makes it available to Snapcast

METADATA_PIPE="/tmp/shairport-sync-metadata"
SNAPCAST_METADATA_FILE="/tmp/metadata/airplay_metadata.json"

# Initialize empty metadata
echo '{}' > "$SNAPCAST_METADATA_FILE"

# Function to decode base64 data
decode_base64() {
    echo "$1" | base64 -d 2>/dev/null || echo "$1"
}

# Function to process metadata
process_metadata() {
    local type="$1"
    local code="$2"
    local data="$3"

    case "$code" in
        "ssnc")
            case "$type" in
                "pbeg") echo "AirPlay session started" ;;
                "pend")
                    echo "AirPlay session ended"
                    echo '{}' > "$SNAPCAST_METADATA_FILE"
                    ;;
            esac
            ;;
        "core")
            case "$type" in
                "minm")
                    title=$(decode_base64 "$data")
                    jq --arg title "$title" '.title = $title' "$SNAPCAST_METADATA_FILE" > /tmp/metadata_temp.json
                    mv /tmp/metadata_temp.json "$SNAPCAST_METADATA_FILE"
                    echo "Updated title: $title"
                    ;;
                "asar")
                    artist=$(decode_base64 "$data")
                    jq --arg artist "$artist" '.artist = $artist' "$SNAPCAST_METADATA_FILE" > /tmp/metadata_temp.json
                    mv /tmp/metadata_temp.json "$SNAPCAST_METADATA_FILE"
                    echo "Updated artist: $artist"
                    ;;
                "asal")
                    album=$(decode_base64 "$data")
                    jq --arg album "$album" '.album = $album' "$SNAPCAST_METADATA_FILE" > /tmp/metadata_temp.json
                    mv /tmp/metadata_temp.json "$SNAPCAST_METADATA_FILE"
                    echo "Updated album: $album"
                    ;;
            esac
            ;;
        "ssnc")
            case "$type" in
                "PICT")
                    # Save cover art as base64 encoded image
                    echo "$data" | base64 -d > "/tmp/metadata/airplay_cover.jpg" 2>/dev/null
                    if [ -f "/tmp/metadata/airplay_cover.jpg" ]; then
                        jq '.artUrl = "/tmp/metadata/airplay_cover.jpg"' "$SNAPCAST_METADATA_FILE" > /tmp/metadata_temp.json
                        mv /tmp/metadata_temp.json "$SNAPCAST_METADATA_FILE"
                        echo "Updated cover art"
                    fi
                    ;;
            esac
            ;;
    esac
}

echo "Starting AirPlay metadata processor..."

# Main processing loop
while IFS= read -r line; do
    # Parse the metadata line format: <item><type>type</type><code>code</code><length>length</length><data encoding="base64">data</data></item>
    if [[ $line =~ \<item\>\<type\>(.*)\</type\>\<code\>(.*)\</code\>\<length\>[0-9]+\</length\>\<data\ encoding=\"base64\"\>(.*)\</data\>\</item\> ]]; then
        type="${BASH_REMATCH[1]}"
        code="${BASH_REMATCH[2]}"
        data="${BASH_REMATCH[3]}"

        process_metadata "$type" "$code" "$data"
    fi
done < "$METADATA_PIPE"