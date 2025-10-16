#!/bin/bash

# Metadata processing script for Shairport-Sync
# This script reads metadata from the pipe and processes it

METADATA_PIPE="/tmp/shairport-sync-metadata"
METADATA_SOCKET_PORT="5555"

echo "[INFO] Starting Airplay metadata processor"

# Function to process metadata from pipe
process_metadata_pipe() {
    echo "[INFO] Reading metadata from pipe: $METADATA_PIPE"
    while true; do
        if [ -p "$METADATA_PIPE" ]; then
            cat "$METADATA_PIPE" | while read -r line; do
                echo "[METADATA] $line"
                # Here you can add logic to parse and forward metadata
                # to your frontend or other services
            done
        else
            echo "[WARNING] Metadata pipe not found, creating..."
            mkfifo "$METADATA_PIPE" 2>/dev/null || true
            chmod 666 "$METADATA_PIPE" 2>/dev/null || true
        fi
        sleep 1
    done
}

# Function to listen for metadata on socket
process_metadata_socket() {
    echo "[INFO] Listening for metadata on socket port: $METADATA_SOCKET_PORT"
    nc -l -k -p "$METADATA_SOCKET_PORT" | while read -r line; do
        echo "[METADATA-SOCKET] $line"
        # Process socket metadata here
    done
}

# Start both metadata processors in background
process_metadata_pipe &
PIPE_PID=$!

process_metadata_socket &
SOCKET_PID=$!

# Wait for either process to exit
wait $PIPE_PID $SOCKET_PID

echo "[INFO] Metadata processor stopped"