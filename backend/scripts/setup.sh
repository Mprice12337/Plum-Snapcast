#!/bin/bash
set -e

echo "Starting Plum Snapcast Server setup..."

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

    # Add AirPlay source to [stream] section
    if [ "${AIRPLAY_CONFIG_ENABLED}" = "1" ]; then
        echo "Adding AirPlay source..."
        # Insert source after [stream] line with control script for metadata
        sed -i '/^\[stream\]/a source = pipe:///tmp/snapfifo?name='"${AIRPLAY_SOURCE_NAME}"'&sampleformat=44100:16:2&codec=pcm&controlscript=/app/scripts/airplay-control-script.py'"${AIRPLAY_EXTRA_ARGS}" /app/config/snapserver.conf
    fi

    # Add Spotify source to [stream] section
    if [ "${SPOTIFY_CONFIG_ENABLED}" = "1" ]; then
        echo "Adding Spotify source..."
        # Insert source after [stream] line with control script for metadata
        sed -i '/^\[stream\]/a source = pipe:///tmp/spotifyfifo?name='"${SPOTIFY_SOURCE_NAME}"'&sampleformat=44100:16:2&codec=pcm&controlscript=/app/scripts/spotify-control-script.py' /app/config/snapserver.conf
    fi

    # Add Bluetooth source to [stream] section
    if [ "${BLUETOOTH_ENABLED}" = "1" ]; then
        echo "Adding Bluetooth source..."
        # Insert source after [stream] line with control script for metadata
        # Bluetooth audio is typically 44.1kHz/16-bit stereo
        sed -i '/^\[stream\]/a source = pipe:///tmp/bluetooth-fifo?name='"${BLUETOOTH_SOURCE_NAME}"'&sampleformat=44100:16:2&codec=pcm&controlscript=/app/scripts/bluetooth-control-script.py' /app/config/snapserver.conf
    fi
fi

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

# Update shairport-sync device name
if [ -n "${AIRPLAY_DEVICE_NAME}" ]; then
    sed -i "/^general = {/,/^}/{s/name = \".*\";/name = \"${AIRPLAY_DEVICE_NAME}\";/}" /app/config/shairport-sync.conf
fi

echo "Setup complete. Starting supervisord..."
exec /usr/bin/supervisord -c /app/supervisord/supervisord.conf
