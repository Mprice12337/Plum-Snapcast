#!/bin/bash
set -e

echo "Starting Plum Snapcast Server setup..."

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
    cat > /app/config/snapserver.conf << SNAPCONF
[stream]
port = 1705

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

    # Add Plexamp source to [stream] section
    # Note: Plexamp runs in separate Debian container, outputs to shared FIFO volume
    if [ "${PLEXAMP_ENABLED}" = "1" ]; then
        echo "Adding Plexamp source (sidecar container)..."
        # Insert source after [stream] line with control script for metadata
        # Plexamp outputs 44.1kHz/16-bit stereo (CD quality)
        sed -i '/^\[stream\]/a source = pipe:///tmp/snapcast-fifos/plexamp-fifo?name='"${PLEXAMP_SOURCE_NAME}"'&sampleformat=44100:16:2&codec=pcm&controlscript=/app/scripts/plexamp-control-script.py' /app/config/snapserver.conf
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

# Update shairport-sync device name and copy config to /etc
if [ -n "${AIRPLAY_DEVICE_NAME}" ]; then
    sed -i "/^general = {/,/^}/{s/name = \".*\";/name = \"${AIRPLAY_DEVICE_NAME}\";/}" /app/config/shairport-sync.conf
fi
# Copy shairport-sync config to /etc (even if name wasn't updated)
cp /app/config/shairport-sync.conf /etc/shairport-sync.conf

# Note: Federation API server always runs to provide Settings API
# Federation features (multi-server control) are enabled/disabled via settings
echo "Federation API server enabled (provides settings API)"

echo "Setup complete. Starting supervisord..."
exec /usr/bin/supervisord -c /app/supervisord/supervisord.conf
