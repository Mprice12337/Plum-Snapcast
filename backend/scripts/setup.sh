#!/bin/bash
set -e

echo "Starting Plum Snapcast Server setup..."

# Wait for D-Bus socket
echo "Waiting for D-Bus..."
timeout=30
while [ ! -S /var/run/dbus/system_bus_socket ] && [ $timeout -gt 0 ]; do
    sleep 1
    ((timeout--))
done

# Test Avahi is working
echo "Testing Avahi daemon..."
timeout 5 avahi-browse -at || echo "Avahi initial browse failed (this is normal)"

# Ensure shairport-sync can write to the FIFO
chmod 666 /tmp/snapfifo 2>/dev/null || true
chmod 666 /tmp/shairport-sync-metadata 2>/dev/null || true

# Fix D-Bus socket permissions to ensure all services can communicate
echo "Fixing D-Bus socket permissions..."
if [ -S /var/run/dbus/system_bus_socket ]; then
    chmod 666 /var/run/dbus/system_bus_socket 2>/dev/null || true
    chown messagebus:messagebus /var/run/dbus/system_bus_socket 2>/dev/null || true
fi

# Ensure avahi-daemon directory has correct permissions
mkdir -p /var/run/avahi-daemon
chown avahi:avahi /var/run/avahi-daemon
chmod 755 /var/run/avahi-daemon

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

    # Add sources based on environment variables
    if [ "${AIRPLAY_CONFIG_ENABLED}" = "1" ]; then
        echo "Adding AirPlay source..."
        echo "source = pipe:///tmp/snapfifo?name=${AIRPLAY_SOURCE_NAME}&sampleformat=44100:16:2&codec=pcm${AIRPLAY_EXTRA_ARGS}" >> /app/config/snapserver.conf
    fi

    if [ "${SPOTIFY_CONFIG_ENABLED}" = "1" ]; then
        echo "Adding Spotify source..."
        echo "source = librespot:///librespot?name=${SPOTIFY_SOURCE_NAME}&devicename=${SPOTIFY_DEVICE_NAME}&bitrate=${SPOTIFY_BITRATE}${SPOTIFY_EXTRA_ARGS}" >> /app/config/snapserver.conf
    fi

    if [ "${PIPE_CONFIG_ENABLED}" = "1" ]; then
        echo "Adding FIFO pipe source..."
        echo "source = pipe://${PIPE_PATH}?name=${PIPE_SOURCE_NAME}&mode=${PIPE_MODE}${PIPE_EXTRA_ARGS}" >> /app/config/snapserver.conf
    fi

    if [ "${META_CONFIG_ENABLED}" = "1" ] && [ -n "${META_SOURCES}" ]; then
        echo "Adding meta source..."
        echo "source = meta:///${META_SOURCES}?name=${META_SOURCE_NAME}${META_EXTRA_ARGS}" >> /app/config/snapserver.conf
    fi

    if [ -n "${SOURCE_CUSTOM}" ]; then
        echo "Adding custom source..."
        echo "source = ${SOURCE_CUSTOM}" >> /app/config/snapserver.conf
    fi
fi

# Generate SSL certificates if they don't exist
if [ "${HTTPS_ENABLED}" = "1" ] && [ "${SKIP_CERT_GENERATION}" != "1" ]; then
    if [ ! -f /app/certs/snapserver.crt ] || [ ! -f /app/certs/snapserver.key ]; then
        echo "Generating self-signed SSL certificate..."
        mkdir -p /app/certs
        
        # Generate CA
        openssl req -new -x509 -days 3650 -nodes \
            -out /app/certs/ca.crt \
            -keyout /app/certs/ca.key \
            -subj "/C=US/ST=State/L=City/O=Plum/CN=Plum-CA"
        
        # Generate server certificate
        openssl req -new -nodes \
            -out /app/certs/snapserver.csr \
            -keyout /app/certs/snapserver.key \
            -subj "/C=US/ST=State/L=City/O=Plum/CN=${CERT_SERVER_CN}"
        
        # Create SAN config
        cat > /app/certs/san.cnf << SANCONF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req

[req_distinguished_name]

[v3_req]
subjectAltName = @alt_names

[alt_names]
SANCONF
        
        # Add DNS names
        i=1
        for dns in ${CERT_SERVER_DNS}; do
            echo "DNS.${i} = ${dns}" >> /app/certs/san.cnf
            ((i++))
        done
        
        # Sign certificate
        openssl x509 -req -days 3650 \
            -in /app/certs/snapserver.csr \
            -CA /app/certs/ca.crt \
            -CAkey /app/certs/ca.key \
            -CAcreateserial \
            -out /app/certs/snapserver.crt \
            -extensions v3_req \
            -extfile /app/certs/san.cnf
        
        echo "SSL certificate generated successfully"
    fi
fi

# Update shairport-sync device name if specified
if [ -n "${AIRPLAY_DEVICE_NAME}" ]; then
    sed -i "s/name = \".*\";/name = \"${AIRPLAY_DEVICE_NAME}\";/" /app/config/shairport-sync.conf
fi

# Create FIFO pipe if needed
if [ "${PIPE_CONFIG_ENABLED}" = "1" ] && [ "${PIPE_MODE}" = "create" ]; then
    if [ ! -p "${PIPE_PATH}" ]; then
        echo "Creating FIFO pipe at ${PIPE_PATH}..."
        mkfifo "${PIPE_PATH}"
    fi
fi

# Ensure AirPlay FIFO exists
if [ ! -p /tmp/snapfifo ]; then
    echo "Creating AirPlay FIFO pipe..."
    mkfifo /tmp/snapfifo
fi

# Ensure metadata pipe exists
if [ ! -p /tmp/shairport-sync-metadata ]; then
    echo "Creating metadata pipe..."
    mkfifo /tmp/shairport-sync-metadata
fi

echo "Setup complete. Starting supervisord..."
exec /usr/bin/supervisord -c /app/supervisord/supervisord.conf
