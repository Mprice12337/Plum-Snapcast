#!/bin/bash
set -e

echo "[SETUP] Starting Snapcast + AirPlay + Snapclient configuration..."

# Initialize dbus
dbus-uuidgen --ensure

# Disable protected FIFOs if possible
if [ -w /proc/sys/fs/protected_fifos ]; then
    echo 0 > /proc/sys/fs/protected_fifos 2>/dev/null || true
fi

# Create required directories
mkdir -p /tmp /app/data /tmp/metadata /tmp/metadata/artwork
chmod 777 /tmp/metadata /tmp/metadata/artwork

#
# CONFIGURE SHAIRPORT-SYNC (AirPlay receiver)
#
if [ "${AIRPLAY_CONFIG_ENABLED}" -eq 1 ]; then
    echo "[SETUP] Configuring shairport-sync for AirPlay..."

    cat > /app/config/shairport-sync.conf << 'EOF'
general = {
    name = "${AIRPLAY_DEVICE_NAME}";
    output_backend = "pipe";
    mdns_backend = "avahi";
    port = 5000;
    udp_port_base = 6000;
    udp_port_range = 10;
    interpolation = "soxr";
    volume_range_db = 60;
    ignore_volume_control = "no";
};

sessioncontrol = {
    allow_session_interruption = "yes";
    session_timeout = 20;
};

metadata = {
    enabled = "yes";
    include_cover_art = "yes";
    pipe_name = "/tmp/shairport-sync-metadata";
    pipe_timeout = 5000;
};

diagnostics = {
    log_verbosity = 1;
};

pipe = {
    name = "/tmp/snapfifo";
    audio_backend_buffer_desired_length = 44100;
};
EOF

    # Replace environment variable
    sed -i "s/\${AIRPLAY_DEVICE_NAME}/${AIRPLAY_DEVICE_NAME}/g" /app/config/shairport-sync.conf

    echo "[SETUP] ✅ Shairport-sync configured (device: ${AIRPLAY_DEVICE_NAME})"
fi

#
# CREATE FIFO PIPES
#
if [ ! -p /tmp/snapfifo ]; then
    mkfifo /tmp/snapfifo
    chmod 666 /tmp/snapfifo
    echo "[SETUP] Created audio pipe: /tmp/snapfifo"
fi

if [ ! -p /tmp/shairport-sync-metadata ]; then
    mkfifo /tmp/shairport-sync-metadata
    chmod 666 /tmp/shairport-sync-metadata
    echo "[SETUP] Created metadata pipe: /tmp/shairport-sync-metadata"
fi

#
# GENERATE SNAPSERVER CONFIGURATION
#
if [ ! -f /app/config/snapserver.conf ]; then
    echo "[SETUP] Generating snapserver.conf..."

    # Build source configuration
    SOURCES=""

    # Add pipe source (for AirPlay)
    if [ "${PIPE_CONFIG_ENABLED}" -eq 1 ]; then
        SOURCES="${SOURCES}source = pipe://${PIPE_PATH}?name=${PIPE_SOURCE_NAME}&mode=${PIPE_MODE}&sampleformat=44100:16:2&codec=flac\n"
    fi

    # If AirPlay is enabled but pipe isn't explicitly configured, add it automatically
    if [ "${AIRPLAY_CONFIG_ENABLED}" -eq 1 ] && [ "${PIPE_CONFIG_ENABLED}" -ne 1 ]; then
        SOURCES="${SOURCES}source = pipe:///tmp/snapfifo?name=${AIRPLAY_SOURCE_NAME}&mode=create&sampleformat=44100:16:2&codec=flac\n"
    fi

    # Add Spotify source
    if [ "${SPOTIFY_CONFIG_ENABLED}" -eq 1 ]; then
        if [ -z "${SPOTIFY_ACCESS_TOKEN}" ]; then
            SOURCES="${SOURCES}source = spotify:///librespot?name=${SPOTIFY_SOURCE_NAME}&devicename=${SPOTIFY_DEVICE_NAME}&bitrate=${SPOTIFY_BITRATE}\n"
        else
            SOURCES="${SOURCES}source = spotify:///librespot?name=${SPOTIFY_SOURCE_NAME}&access-token=${SPOTIFY_ACCESS_TOKEN}&devicename=${SPOTIFY_DEVICE_NAME}&bitrate=${SPOTIFY_BITRATE}\n"
        fi
    fi

    # Add meta source
    if [ "${META_CONFIG_ENABLED}" -eq 1 ] && [ -n "${META_SOURCES}" ]; then
        SOURCES="${SOURCES}source = meta:///${META_SOURCES}?name=${META_SOURCE_NAME}\n"
    fi

    # Add custom source
    if [ -n "${SOURCE_CUSTOM}" ]; then
        SOURCES="${SOURCES}source = ${SOURCE_CUSTOM}\n"
    fi

    # Create snapserver.conf
    cat > /app/config/snapserver.conf << EOF
[http]
enabled = true
port = 1780

[tcp]
enabled = true
port = 1704

[stream]
$(echo -e "${SOURCES}")

[logging]
EOF

    echo "[SETUP] ✅ Snapserver configuration generated"
else
    echo "[SETUP] Using existing snapserver.conf"
fi

#
# CONFIGURE HTTPS
#
if [ "${HTTPS_ENABLED}" -eq 1 ]; then
    if [ "${SKIP_CERT_GENERATION}" -eq 0 ] && [ ! -f /app/certs/snapserver.crt ]; then
        echo "[SETUP] Generating SSL certificates..."
        /app/gen-certs.sh
    fi

    # Enable HTTPS in snapserver.conf if not already configured
    if ! grep -q "^ssl_enabled" /app/config/snapserver.conf; then
        cat >> /app/config/snapserver.conf << EOF

[http]
ssl_enabled = true
certificate = /app/certs/snapserver.crt
certificate_key = /app/certs/snapserver.key
EOF
    fi

    echo "[SETUP] ✅ HTTPS configured"
fi

echo "[SETUP] ✅ Configuration complete!"
echo "[SETUP] Starting services via supervisord..."