#!/bin/bash

echo "[SETUP] Starting minimal AirPlay + Snapcast configuration..."

# Prepare dbus-daemon environment
dbus-uuidgen --ensure

# Disable protected FIFOs to allow pipe writes in /tmp
if [ -w /proc/sys/fs/protected_fifos ]; then
    echo 0 > /proc/sys/fs/protected_fifos 2>/dev/null || true
fi

#
# SETUP SHAIRPORT-SYNC CONFIGURATION (AirPlay 1 for simplicity)
#
if [ "${AIRPLAY_CONFIG_ENABLED}" -eq 1 ]; then
    echo "[SETUP] Configuring Shairport-Sync for AirPlay 1..."

    # Always use AirPlay 1 (port 5000) for maximum compatibility
    AIRPLAY_PORT="5000"

    # Create minimal shairport-sync configuration
    cat > /app/config/shairport-sync.conf << EOF
general = {
    name = "${AIRPLAY_DEVICE_NAME}";
    output_backend = "pipe";
    mdns_backend = "avahi";
    port = ${AIRPLAY_PORT};
    udp_port_base = 6000;
    udp_port_range = 10;
    interpolation = "basic";  // Minimal CPU usage
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
    log_verbosity = 1;  // Minimal logging
};

pipe = {
    name = "/tmp/snapfifo";
    audio_backend_buffer_desired_length = 44100;  // 1 second buffer at 44.1kHz
};
EOF

    echo "[SETUP] ✅ Shairport-sync configured for device: ${AIRPLAY_DEVICE_NAME}"
fi

#
# SETUP SNAPCAST SERVER CONFIGURATION
#

if [ ! -f /app/config/snapserver.conf ]; then
    echo "[SETUP] Creating minimal snapserver configuration..."

    # Create the FIFO pipe that will receive audio from shairport-sync
    # CRITICAL: Use 44100:16:2 sample format to match AirPlay output
    PIPE_SOURCE="source = pipe:///tmp/snapfifo?name=AirPlay&mode=create&sampleformat=44100:16:2&codec=flac"

    cat > /app/config/snapserver.conf << EOF
[http]
enabled = true
port = 1780

[tcp]
enabled = true
port = 1704

[stream]
${PIPE_SOURCE}

[logging]
EOF

    #
    # SETUP HTTPS if enabled
    #
    if [ "${HTTPS_ENABLED}" -eq 1 ]; then
        # Generate certificates if they don't exist
        if [ "${SKIP_CERT_GENERATION}" -eq 0 ]; then
            /bin/bash /app/gen-certs.sh
        fi

        # Enable HTTPS in configuration
        sed -i 's|^#\?ssl_enabled =.*|ssl_enabled = true|' /app/config/snapserver.conf
        sed -i 's|^#\?certificate =.*|certificate = /app/certs/snapserver.crt|' /app/config/snapserver.conf
        sed -i 's|^#\?certificate_key =.*|certificate_key = /app/certs/snapserver.key|' /app/config/snapserver.conf

        echo "[SETUP] ✅ HTTPS enabled"
    fi

    echo "[SETUP] ✅ Snapserver configured with AirPlay source at 44.1kHz"
else
    echo "[SETUP] Using existing snapserver.conf"
fi

#
# CREATE NECESSARY PIPES AND DIRECTORIES
#
mkdir -p /tmp
mkdir -p /app/data
mkdir -p /tmp/metadata

# Create the audio pipe for snapcast (snapserver will create it, but we ensure it exists)
if [ ! -p /tmp/snapfifo ]; then
    mkfifo /tmp/snapfifo
    chmod 666 /tmp/snapfifo
fi

# Create metadata pipe for shairport-sync
if [ ! -p /tmp/shairport-sync-metadata ]; then
    mkfifo /tmp/shairport-sync-metadata
    chmod 666 /tmp/shairport-sync-metadata
    mkdir -p /tmp/metadata/artwork
    chmod 777 /tmp/metadata/artwork
fi

echo "[SETUP] ✅ All pipes and directories created"
echo "[SETUP] ✅ Setup complete - starting services via supervisord"
exit 0