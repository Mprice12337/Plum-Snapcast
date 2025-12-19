#!/bin/bash
set -e

echo "Starting Plum Snapcast Server setup..."

# Ensure settings file exists (run migration if needed)
if [ ! -f /app/data/settings.json ]; then
    echo "Settings file not found. Running migration to create default settings..."
    if [ -f /app/scripts/migrate-env-to-settings.py ]; then
        python3 /app/scripts/migrate-env-to-settings.py 2>&1 | grep -v "^=" || true
    fi
fi

# Load settings from settings API/file
# This will set environment variables based on stored settings
# Falls back to existing env vars if settings file doesn't exist
if [ -f /app/scripts/get-settings.py ]; then
    echo "Loading settings from settings file..."
    eval "$(python3 /app/scripts/get-settings.py 2>/dev/null || true)"
fi

# Clean up any stale sockets/pids from previous runs
# Container runs its own D-Bus and Avahi (fully self-contained)
rm -rf /var/run/dbus/*
rm -rf /var/run/avahi-daemon/*

# Create required directories for container's D-Bus and Avahi
mkdir -p /var/run/dbus /var/run/avahi-daemon
chmod 755 /var/run/dbus /var/run/avahi-daemon

# Ensure FIFO pipes exist
if [ ! -p /tmp/snapfifo ]; then
    echo "Creating AirPlay FIFO pipe..."
    mkfifo /tmp/snapfifo
    chmod 666 /tmp/snapfifo
fi

if [ ! -p /tmp/none-fifo ]; then
    echo "Creating None stream FIFO pipe..."
    mkfifo /tmp/none-fifo
    chmod 666 /tmp/none-fifo
fi

if [ ! -p /tmp/shairport-sync-metadata ]; then
    echo "Creating AirPlay metadata pipe..."
    mkfifo /tmp/shairport-sync-metadata
    chmod 666 /tmp/shairport-sync-metadata
fi

if [ ! -p /tmp/spotifyfifo ]; then
    echo "Creating Spotify FIFO pipe..."
    mkfifo /tmp/spotifyfifo
    chmod 666 /tmp/spotifyfifo
fi

if [ ! -p /tmp/bluetooth-fifo ]; then
    echo "Creating Bluetooth FIFO pipe..."
    mkfifo /tmp/bluetooth-fifo
    chmod 666 /tmp/bluetooth-fifo
fi

if [ ! -p /tmp/dlna-fifo ]; then
    echo "Creating DLNA FIFO pipe..."
    mkfifo /tmp/dlna-fifo
    chmod 666 /tmp/dlna-fifo
fi

if [ ! -p /tmp/snapcast-fifos/plexamp-fifo ]; then
    echo "Creating Plexamp FIFO pipe in shared volume..."
    mkfifo /tmp/snapcast-fifos/plexamp-fifo
    chmod 666 /tmp/snapcast-fifos/plexamp-fifo
fi

# Create artwork cache directory for shairport-sync
echo "Creating artwork cache directory..."
mkdir -p /tmp/shairport-sync/.cache/coverart
chmod -R 777 /tmp/shairport-sync/.cache
echo "Artwork cache directory ready at /tmp/shairport-sync/.cache/coverart"

# Generate snapserver configuration if it doesn't exist
if [ ! -f /app/config/snapserver.conf ]; then
    echo "Generating snapserver.conf..."

    # Get unique name for none stream (from setting or hostname)
    NONE_STREAM_NAME="${NONE_STREAM_NAME:-$(hostname)}"
    NONE_STREAM_ID="none-${NONE_STREAM_NAME}"

    echo "Creating none stream: ${NONE_STREAM_ID}"

    cat > /app/config/snapserver.conf << SNAPCONF
[stream]
port = 1705
# None stream - placeholder for local announcements (e.g., Home Assistant)
# Uses unique name to avoid conflicts in federated setups
# Uses dedicated FIFO to avoid conflicts with dynamic streams (AirPlay, Spotify, etc.)
# Frontend filters out all "none-*" streams except the local one
source = pipe:///tmp/none-fifo?name=${NONE_STREAM_ID}&sampleformat=48000:16:2&codec=pcm

[http]
enabled = true
port = 1780
doc_root = /usr/share/snapserver/snapweb

[https]
enabled = ${HTTPS_ENABLED}
port = 1788
doc_root = /usr/share/snapserver/snapweb
cert_file = /app/certs/snapserver.crt
key_file = /app/certs/snapserver.key

[tcp]
enabled = true
port = 1704

[server]
datadir = /app/data
SNAPCONF

    # AirPlay source is now managed dynamically by stream-lifecycle-manager
    # The lifecycle manager will add/remove the stream based on client activity
    # This keeps AirPlay discoverable but only creates Snapcast stream when active
    if [ "${AIRPLAY_CONFIG_ENABLED}" = "1" ]; then
        echo "AirPlay stream managed dynamically by lifecycle manager"
    fi

    # Spotify source is now managed dynamically by spotify-stream-lifecycle-manager
    # The lifecycle manager will add/remove the stream based on playback state
    # This keeps Spotify Connect discoverable but only creates Snapcast stream when playing
    if [ "${SPOTIFY_CONFIG_ENABLED}" = "1" ]; then
        echo "Spotify stream managed dynamically by lifecycle manager"
    fi

    # Bluetooth source is now managed dynamically by bluetooth-stream-lifecycle-manager
    # The lifecycle manager will add/remove the stream based on device connections
    # This keeps Bluetooth discoverable but only creates Snapcast stream when devices connect
    if [ "${BLUETOOTH_CONFIG_ENABLED}" = "1" ]; then
        echo "Bluetooth stream managed dynamically by lifecycle manager"
    fi

    # DLNA source is now managed dynamically by dlna-stream-lifecycle-manager
    if [ "${DLNA_ENABLED}" = "1" ]; then
        echo "DLNA stream managed dynamically by lifecycle manager"
    fi

    # Plexamp source is now managed dynamically by plexamp-stream-lifecycle-manager
    # The lifecycle manager will add/remove the stream based on playback state
    # This keeps Plexamp available but only creates Snapcast stream when playing
    if [ "${PLEXAMP_ENABLED}" = "1" ]; then
        echo "Plexamp stream managed dynamically by lifecycle manager"
        # Enable autostart for the lifecycle manager
        sed -i 's/^autostart=false/autostart=true/' /app/supervisord/plexamp-stream-lifecycle-manager.ini
    else
        # Ensure autostart is disabled when Plexamp is not enabled
        sed -i 's/^autostart=true/autostart=false/' /app/supervisord/plexamp-stream-lifecycle-manager.ini
    fi
fi

# Note: ALSA configuration for Plexamp is handled in the separate Debian container

# Generate SSL certificates if needed
if [ "${HTTPS_ENABLED}" = "1" ] && [ "${SKIP_CERT_GENERATION}" != "1" ]; then
    if [ ! -f /app/certs/snapserver.crt ] || [ ! -f /app/certs/snapserver.key ]; then
        echo "Generating self-signed SSL certificate..."
        mkdir -p /app/certs
        openssl req -new -x509 -days 3650 -nodes \
            -out /app/certs/snapserver.crt \
            -keyout /app/certs/snapserver.key \
            -subj "/C=US/ST=State/L=City/O=Plum/CN=snapserver"
    fi
fi

# AirPlay Endpoint Configuration (always use multi-instance approach)
# Endpoints are configured via settings.json and parsed by get-settings.py
echo "Setting up AirPlay endpoints..."
bash /app/scripts/setup-airplay-multi-instance.sh

# Disable old single-instance AirPlay components (if they exist)
# Need to disable in BOTH snapcast.ini and snapclient.ini since both define the service
if [ -f /app/supervisord/snapcast.ini ]; then
    sed -i '/^\[program:shairport-sync\]/,/^$/s/^autostart=true/autostart=false/' /app/supervisord/snapcast.ini 2>/dev/null || true
    sed -i '/^\[program:stream-lifecycle-manager\]/,/^$/s/^autostart=true/autostart=false/' /app/supervisord/snapcast.ini 2>/dev/null || true
    echo "Disabled old single-instance AirPlay services in snapcast.ini"
fi
if [ -f /app/supervisord/snapclient.ini ]; then
    sed -i '/^\[program:shairport-sync\]/,/^$/s/^autostart=true/autostart=false/' /app/supervisord/snapclient.ini 2>/dev/null || true
    sed -i '/^\[program:stream-lifecycle-manager\]/,/^$/s/^autostart=true/autostart=false/' /app/supervisord/snapclient.ini 2>/dev/null || true
    echo "Disabled old single-instance AirPlay services in snapclient.ini"
fi

# Note: Federation API server always runs to provide Settings API
# Federation features (multi-server control) are enabled/disabled via settings
echo "Federation API server enabled (provides settings API)"

echo "Setup complete. Starting supervisord..."
exec /usr/bin/supervisord -c /app/supervisord/supervisord.conf
