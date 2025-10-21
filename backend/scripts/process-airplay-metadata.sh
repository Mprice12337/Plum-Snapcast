#!/bin/bash

# Process AirPlay metadata from shairport-sync
# This script reads metadata from the pipe and can be extended to process it

METADATA_PIPE="/tmp/shairport-sync-metadata"

if [ ! -p "$METADATA_PIPE" ]; then
    echo "Metadata pipe not found: $METADATA_PIPE"
    exit 1
fi

echo "Starting AirPlay metadata processor..."

while true; do
    if [ -p "$METADATA_PIPE" ]; then
        while read -r line; do
            # Process metadata line by line
            # You can extend this to parse and handle specific metadata
            echo "Metadata: $line"
        done < "$METADATA_PIPE"
    fi
    sleep 1
done
