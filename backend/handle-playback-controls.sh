#!/bin/bash

# Monitor D-Bus for playback control events
dbus-monitor --session "type='signal',interface='org.gnome.ShairportSync'" | \
while read -r line; do
    if [[ "$line" =~ "member=RemoteCommand" ]]; then
        read -r command_line
        if [[ "$command_line" =~ "string \"(.*)\"" ]]; then
            command="${BASH_REMATCH[1]}"

            case "$command" in
                "play")
                    echo "[CONTROL] Play command received"
                    curl -s -X POST "http://localhost:1780/jsonrpc" \
                        -d '{"jsonrpc":"2.0","method":"Stream.Control","params":{"id":"Airplay","command":"play"},"id":1}'
                    ;;
                "pause")
                    echo "[CONTROL] Pause command received"
                    curl -s -X POST "http://localhost:1780/jsonrpc" \
                        -d '{"jsonrpc":"2.0","method":"Stream.Control","params":{"id":"Airplay","command":"pause"},"id":1}'
                    ;;
                "nextitem")
                    echo "[CONTROL] Next track command received"
                    curl -s -X POST "http://localhost:1780/jsonrpc" \
                        -d '{"jsonrpc":"2.0","method":"Stream.Control","params":{"id":"Airplay","command":"next"},"id":1}'
                    ;;
                "previtem")
                    echo "[CONTROL] Previous track command received"
                    curl -s -X POST "http://localhost:1780/jsonrpc" \
                        -d '{"jsonrpc":"2.0","method":"Stream.Control","params":{"id":"Airplay","command":"previous"},"id":1}'
                    ;;
            esac
        fi
    fi
done