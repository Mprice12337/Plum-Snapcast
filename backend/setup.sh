#!/bin/bash

# Prepare dbus-daemon environment
dbus-uuidgen --ensure

# Create metadata directories and pipes if they don't exist
mkdir -p /tmp/metadata
if [ ! -p /tmp/shairport-sync-metadata ]; then
    mkfifo /tmp/shairport-sync-metadata
    chmod 666 /tmp/shairport-sync-metadata
    mkdir -p /tmp/metadata/artwork
    chmod 777 /tmp/metadata/artwork
fi

#
# SETUP SHAIRPORT-SYNC CONFIGURATION
#
if [ "${AIRPLAY_CONFIG_ENABLED}" -eq 1 ]; then
    if [ "${BUILD_AIRPLAY_VERSION}" -eq 2 ]; then
        AIRPLAY_PORT="7000"
        echo "[SETUP] Configuring Shairport-Sync for Airplay 2..."
    else
        AIRPLAY_PORT="5000"
        echo "[SETUP] Configuring Shairport-Sync for Airplay classic/1..."
    fi

    # Always use pipe output to Snapcast
    echo "[SETUP] Configuring shairport-sync with PIPE output to Snapcast"

    # Create shairport-sync configuration from template
    echo "[SETUP] Generating shairport-sync config with device name: ${AIRPLAY_DEVICE_NAME}, port: ${AIRPLAY_PORT}"
    sed "s/%AIRPLAY_DEVICE_NAME%/${AIRPLAY_DEVICE_NAME}/g; s/%AIRPLAY_PORT%/${AIRPLAY_PORT}/g" \
        /app/config/shairport-sync.conf > /tmp/shairport-sync.conf

    cp /tmp/shairport-sync.conf /app/config/shairport-sync.conf
    rm -f /tmp/shairport-sync.conf

    echo "[SETUP] Shairport-sync configuration updated"
fi

#
# SETUP SNAPCAST
#

# SNAPCAST: Create default configuration for snapserver
SNAPCAST_CONFIG=""

if [ "${PIPE_CONFIG_ENABLED}" -eq 1 ]; then
    SNAPCAST_CONFIG="${SNAPCAST_CONFIG}source = pipe://${PIPE_PATH}?name=${PIPE_SOURCE_NAME}&mode=${PIPE_MODE}${PIPE_EXTRA_ARGS}\n"
fi

# NOTE: We do NOT add an airplay:// source here because shairport-sync outputs to the pipe
# and Snapcast reads from the pipe. The pipe source handles AirPlay audio.

if [ "${SPOTIFY_CONFIG_ENABLED}" -eq 1 ]; then
    if [ -z "${SPOTIFY_ACCESS_TOKEN}" ]; then
        echo "[SETUP]  Warning: Spotify access token is not set! Creating config without user account. Spotify Connect client will be discoverable on the local network only."
        SNAPCAST_CONFIG="${SNAPCAST_CONFIG}source = spotify:///librespot?name=${SPOTIFY_SOURCE_NAME}&devicename=${SPOTIFY_DEVICE_NAME}&bitrate=${SPOTIFY_BITRATE}${SPOTIFY_EXTRA_ARGS}\n"
    else
        SNAPCAST_CONFIG="${SNAPCAST_CONFIG}source = spotify:///librespot?name=${SPOTIFY_SOURCE_NAME}&access-token=${SPOTIFY_ACCESS_TOKEN}&devicename=${SPOTIFY_DEVICE_NAME}&bitrate=${SPOTIFY_BITRATE}${SPOTIFY_EXTRA_ARGS}\n"
    fi
fi

if [ "${META_CONFIG_ENABLED}" -eq 1 ]; then
    if [ -z "${META_SOURCES}" ]; then
        echo "[SETUP]  Error: Cannot create meta configuration! Sources are not set!"
    else
        SNAPCAST_CONFIG="${SNAPCAST_CONFIG}source = meta:///${META_SOURCES}?name=${META_SOURCE_NAME}${META_EXTRA_ARGS}\n"
    fi
fi

if [ ! -z "${SOURCE_CUSTOM}" ]; then
    SNAPCAST_CONFIG="${SNAPCAST_CONFIG}source = ${SOURCE_CUSTOM}\n"
fi

# Create snapserver configuration
if [ ! -f /app/config/snapserver.conf ]; then
    echo "[SETUP] Creating default snapserver configuration..."
    cat > /tmp/snapserver.conf << EOF
[http]
enabled = true
port = 1780

[tcp]
enabled = true
port = 1704

[stream]
$(echo -e "${SNAPCAST_CONFIG}")

[logging]
EOF
fi

#
# SETUP HTTPS
#
if [ "${HTTPS_ENABLED}" -eq 1 ]; then
    # Generate CA and certificates
    if [ "${SKIP_CERT_GENERATION}" -eq 0 ]; then
        /bin/bash /app/gen-certs.sh
    fi

    # Enable HTTPS in configuration
    sed -i 's|^#\?ssl_enabled =.*|ssl_enabled = true|' /tmp/snapserver.conf
    sed -i 's|^#\?certificate =.*|certificate = /app/certs/snapserver.crt|' /tmp/snapserver.conf
    sed -i 's|^#\?certificate_key =.*|certificate_key = /app/certs/snapserver.key|' /tmp/snapserver.conf
fi

# Copy created configuration to config directory, if not existent yet
cp -n /tmp/snapserver.conf /app/config/snapserver.conf
rm /tmp/snapserver.conf

#
# SETUP SHAIRPORT-SYNC AIRPLAY-2
#
if [ "${BUILD_AIRPLAY_VERSION}" -eq 2 ]; then
    NQPTP_SUPERVISORD_CONFIG="
[program:nqptp]
command=/usr/local/bin/nqptp
autostart=true
autorestart=true
startsecs=3
startretries=5
priority=21
"
    echo -e "${NQPTP_SUPERVISORD_CONFIG}" > /app/supervisord/nqptp.ini
fi

# Create necessary directories and pipes
mkdir -p /tmp
mkdir -p /app/data

# Create the audio pipe for snapcast
if [ ! -p /tmp/snapfifo ]; then
    mkfifo /tmp/snapfifo
    chmod 666 /tmp/snapfifo
fi

# Create metadata pipe
if [ ! -p /tmp/shairport-sync-metadata ]; then
    mkfifo /tmp/shairport-sync-metadata
    chmod 666 /tmp/shairport-sync-metadata
fi

echo "[SETUP] ✅ Setup complete"
exit 0