#!/bin/bash
set -e

echo "Starting Plum Snapcast Server setup..."

# Clean up any stale sockets/pids
rm -f /var/run/dbus/pid /var/run/dbus/system_bus_socket
rm -rf /var/run/avahi-daemon/*

# Create required directories
mkdir -p /var/run/dbus /var/run/avahi-daemon
chmod 755 /var/run/dbus /var/run/avahi-daemon

# Ensure FIFO pipes exist
if [ ! -p /tmp/snapfifo ]; then
    echo "Creating AirPlay FIFO pipe..."
    mkfifo /tmp/snapfifo
    chmod 666 /tmp/snapfifo
fi

if [ ! -p /tmp/shairport-sync-metadata ]; then
    echo "Creating metadata pipe..."
    mkfifo /tmp/shairport-sync-metadata
    chmod 666 /tmp/shairport-sync-metadata
fi

# Generate snapserver configuration if it doesn't exist
if [ ! -f /app/config/snapserver.conf ]; then
    echo "Generating snapserver.conf..."
    cat > /app/config/snapserver.conf << 'SNAPCONF'
[stream]

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

    # Add AirPlay source
    if [ "${AIRPLAY_CONFIG_ENABLED}" = "1" ]; then
        echo "Adding AirPlay source..."
        echo "source = pipe:///tmp/snapfifo?name=${AIRPLAY_SOURCE_NAME}&sampleformat=44100:16:2&codec=pcm${AIRPLAY_EXTRA_ARGS}" >> /app/config/snapserver.conf
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
    sed -i "s/name = \".*\";/name = \"${AIRPLAY_DEVICE_NAME}\";/" /app/config/shairport-sync.conf
fi

echo "Setup complete. Starting supervisord..."
exec /usr/bin/supervisord -c /app/supervisord/supervisord.conf