FROM alpine:3.19

# Build arguments for multi-platform support
ARG TARGETPLATFORM
ARG BUILDPLATFORM

LABEL maintainer="Plum-Snapcast"
LABEL description="Snapcast server with AirPlay, Bluetooth, Spotify, and DLNA/UPnP support"

# Install runtime dependencies (python3 for metadata, GStreamer for DLNA, Flask for federation)
RUN apk add --no-cache \
    bash \
    avahi \
    avahi-tools \
    dbus \
    supervisor \
    curl \
    openssl \
    tzdata \
    alsa-lib \
    libconfig \
    libsndfile \
    popt \
    libsodium \
    libdaemon \
    libplist \
    glib \
    mbedtls \
    soxr \
    libgcrypt \
    libuuid \
    ffmpeg-libs \
    python3 \
    py3-pip \
    py3-paho-mqtt \
    py3-dbus \
    py3-gobject3 \
    py3-requests \
    py3-flask \
    py3-flask-cors \
    mosquitto \
    mosquitto-clients \
    bluez \
    bluez-alsa \
    util-linux \
    gstreamer \
    gst-plugins-base \
    gst-plugins-good \
    gst-plugins-bad \
    gst-plugins-ugly \
    gst-libav \
    libupnp \
    sudo

# Install Python packages for federation service and lifecycle manager
RUN pip3 install --no-cache-dir --break-system-packages websockets websocket-client

# Add edge repository and install snapcast (latest: 0.34.0 in community repo)
RUN echo "@edge http://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories && \
    apk update && \
    apk add --no-cache \
        snapcast-server@edge \
        snapcast-client@edge \
        alsa-utils  # Add this for aplay/speaker-test

# Install build dependencies
RUN apk add --no-cache --virtual .build-deps \
    git \
    build-base \
    autoconf \
    automake \
    libtool \
    pkgconfig \
    alsa-lib-dev \
    avahi-dev \
    libconfig-dev \
    libsndfile-dev \
    popt-dev \
    openssl-dev \
    openssl-libs-static \
    libsodium-dev \
    libdaemon-dev \
    libplist-dev \
    glib-dev \
    dbus-dev \
    mbedtls-dev \
    soxr-dev \
    libgcrypt-dev \
    ffmpeg-dev \
    mosquitto-dev \
    # DLNA/UPnP build dependencies
    gstreamer-dev \
    gst-plugins-base-dev \
    libupnp-dev

# Build Apple ALAC library first (required for shairport-sync)
WORKDIR /tmp
RUN git clone --depth 1 https://github.com/mikebrady/alac.git && \
    cd alac && \
    autoreconf -fi && \
    ./configure && \
    make -j$(nproc) && \
    make install && \
    cd .. && \
    rm -rf alac

# Build shairport-sync with metadata, MQTT, D-Bus/MPRIS, and AirPlay support
RUN git clone --depth 1 --branch master https://github.com/mikebrady/shairport-sync.git && \
    cd shairport-sync && \
    autoreconf -fi && \
    ./configure \
        --sysconfdir=/etc \
        --with-alsa \
        --with-avahi \
        --with-ssl=openssl \
        --with-metadata \
        --with-mqtt-client \
        --with-dbus-interface \
        --with-mpris-interface \
        --with-stdout \
        --with-pipe \
        --with-apple-alac && \
    make -j$(nproc) && \
    make install && \
    rm -f /etc/dbus-1/system.d/shairport-sync-mpris.conf && \
    cd .. && \
    rm -rf shairport-sync

# Install Rust for building librespot
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal && \
    . $HOME/.cargo/env && \
    rustup target add $(uname -m)-unknown-linux-musl 2>/dev/null || true

# Build spotifyd from source with D-Bus MPRIS support and Avahi integration
# spotifyd is a Spotify daemon built on librespot with working MPRIS support
# This provides both metadata and playback controls via D-Bus
# Patch to use Avahi for discovery instead of libmdns (avoids port 5353 conflict)
# Use dynamic linking for system libraries (ALSA, OpenSSL, D-Bus)
RUN . $HOME/.cargo/env && \
    git clone --depth 1 https://github.com/Spotifyd/spotifyd.git && \
    cd spotifyd && \
    # Patch Cargo.toml to enable with-avahi feature on librespot-discovery
    sed -i 's/librespot-discovery = "0.8.0"/librespot-discovery = { version = "0.8.0", default-features = false, features = ["with-avahi"] }/' Cargo.toml && \
    RUSTFLAGS="-C target-feature=-crt-static" \
    cargo build --release --no-default-features --features "alsa_backend,dbus_mpris" && \
    cp target/release/spotifyd /usr/local/bin/spotifyd && \
    chmod +x /usr/local/bin/spotifyd && \
    cd .. && \
    rm -rf spotifyd $HOME/.cargo $HOME/.rustup

# Build gmrender-resurrect for DLNA/UPnP support
# This provides a UPnP/DLNA media renderer that integrates with Snapcast via FIFO pipe
# Uses GStreamer for audio processing with network discovery via Avahi
RUN git clone --depth 1 https://github.com/hzeller/gmrender-resurrect.git && \
    cd gmrender-resurrect && \
    autoreconf -fi && \
    ./configure \
        --prefix=/usr/local \
        --with-build-date="$(date '+%Y-%m-%d')" && \
    make -j$(nproc) && \
    make install && \
    cd .. && \
    rm -rf gmrender-resurrect

# Cleanup build dependencies and temporary files
# Use --force-broken-world because we have packages from @edge that aren't in the cache
RUN apk del --force-broken-world .build-deps && \
    rm -rf /var/cache/apk/* /tmp/*

# Fix the world file to only include packages we want to keep
RUN apk fix

# Configure users and groups
# Create all required system users
RUN deluser snapcast 2>/dev/null || true && \
    delgroup snapcast 2>/dev/null || true && \
    addgroup -g 1000 snapcast && \
    adduser -D -u 1000 -G snapcast -h /app snapcast && \
    addgroup snapcast audio && \
    addgroup -S messagebus 2>/dev/null || true && \
    adduser -S -G messagebus -H -s /sbin/nologin messagebus 2>/dev/null || true && \
    addgroup -S mosquitto 2>/dev/null || true && \
    adduser -S -G mosquitto -H -s /sbin/nologin mosquitto 2>/dev/null || true

# Configure sudo for snapcast user (needed for API to manage endpoints)
# Allow snapcast to run setup scripts and supervisorctl without password
RUN echo "snapcast ALL=(ALL) NOPASSWD: /bin/bash /app/scripts/setup-airplay-multi-instance.sh" >> /etc/sudoers.d/snapcast && \
    echo "snapcast ALL=(ALL) NOPASSWD: /bin/bash /app/scripts/setup-spotify-multi-instance.sh" >> /etc/sudoers.d/snapcast && \
    echo "snapcast ALL=(ALL) NOPASSWD: /usr/bin/supervisorctl" >> /etc/sudoers.d/snapcast && \
    chmod 0440 /etc/sudoers.d/snapcast

# Configure D-Bus machine-id (required for D-Bus to create socket)
RUN mkdir -p /var/lib/dbus && \
    dbus-uuidgen > /var/lib/dbus/machine-id

# Copy D-Bus policy files for shairport-sync and spotifyd
RUN mkdir -p /etc/dbus-1/system.d
COPY config/shairport-sync-dbus.conf /etc/dbus-1/system.d/
COPY config/spotifyd-dbus.conf /etc/dbus-1/system.d/

# Copy BlueZ configuration for "Just Works" pairing support (iOS devices)
RUN mkdir -p /etc/bluetooth
COPY config/main.conf /etc/bluetooth/main.conf

# Configure Avahi
RUN mkdir -p /run/avahi-daemon /var/run/dbus /etc/avahi/services && \
    chmod 755 /run/avahi-daemon /var/run/dbus

# FIXED: Copy configuration files
COPY config/avahi-daemon.conf /etc/avahi/avahi-daemon.conf
COPY config/plum-snapcast.service /etc/avahi/services/
COPY config/shairport-sync.conf /app/config/
COPY config/shairport-sync.conf.template /app/config/
COPY config/spotifyd.conf /app/config/
COPY config/spotifyd.conf.template /app/config/
COPY config/mosquitto.conf /app/config/
COPY config/asoundrc /etc/asound.conf

# Make avahi config writable by snapcast user (for hostname updates via settings API)
RUN chown snapcast:snapcast /etc/avahi/avahi-daemon.conf && \
    chmod 644 /etc/avahi/avahi-daemon.conf

# Make ALSA config readable by all users (enables dmix for multiple snapclients)
RUN chmod 644 /etc/asound.conf

# Make mosquitto config readable by mosquitto user
RUN chmod 644 /app/config/mosquitto.conf


# Create required directories
# Note: /tmp/snapfifo is created by setup.sh as a FIFO pipe, not a directory
RUN mkdir -p \
    /app/config \
    /app/data \
    /app/certs \
    /app/scripts \
    /app/supervisord \
    /tmp/snapcast-fifos \
    /var/run/dbus \
    /var/run/avahi-daemon \
    /var/log/supervisord \
    /usr/share/snapserver/snapweb/coverart \
    /var/lib/bluetooth \
    && chown -R snapcast:snapcast /app \
    && chown -R snapcast:snapcast /tmp/snapcast-fifos \
    && chmod 755 /var/run/dbus \
    && chmod 755 /var/run/avahi-daemon \
    && chmod 755 /var/log/supervisord \
    && chown -R snapcast:snapcast /usr/share/snapserver/snapweb \
    && chmod 755 /usr/share/snapserver/snapweb \
    && chmod 700 /var/lib/bluetooth

# Copy configuration and scripts (copy all scripts at once)
COPY config/supervisord/ /app/supervisord/
COPY config/shairport-sync.conf /app/config/
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh /app/scripts/*.py 2>/dev/null || true && \
    chown -R snapcast:snapcast /app

# Copy control scripts to Snapserver plug-ins directory (required for dynamic stream management)
RUN cp /app/scripts/airplay-control-script.py /usr/share/snapserver/plug-ins/ && \
    cp /app/scripts/bluetooth-control-script.py /usr/share/snapserver/plug-ins/ && \
    cp /app/scripts/spotify-control-script.py /usr/share/snapserver/plug-ins/ && \
    cp /app/scripts/dlna-control-script.py /usr/share/snapserver/plug-ins/ && \
    cp /app/scripts/plexamp-control-script.py /usr/share/snapserver/plug-ins/ && \
    chmod +x /usr/share/snapserver/plug-ins/airplay-control-script.py && \
    chmod +x /usr/share/snapserver/plug-ins/bluetooth-control-script.py && \
    chmod +x /usr/share/snapserver/plug-ins/spotify-control-script.py && \
    chmod +x /usr/share/snapserver/plug-ins/dlna-control-script.py && \
    chmod +x /usr/share/snapserver/plug-ins/plexamp-control-script.py

# Replace snapweb index.html with redirect to port 3000
# This preserves API/WebSocket functionality on /jsonrpc while redirecting browsers to our React GUI
COPY config/redirect-index.html /usr/share/snapserver/snapweb/index.html
RUN chown snapcast:snapcast /usr/share/snapserver/snapweb/index.html && \
    chmod 644 /usr/share/snapserver/snapweb/index.html

# Expose ports
# Snapcast: 1704-1705 (control/stream), 1780 (HTTP), 1788 (HTTPS)
# AirPlay Endpoints: 5050-5059 (up to 10 endpoints), 3689, 5353, 6001-6100/udp
# Federation API: 5001 (HTTP REST API)
# Metadata Debug Server: 8080 (HTTP)
# Note: Plexamp runs in separate container (port 32500)
EXPOSE 1704 1705 1780 1788 3689 5001 5050-5059 5353 6001-6100/udp 8080

# Set working directory
WORKDIR /app

# Environment variables with defaults
# Note: Integration settings (AirPlay, Bluetooth, Spotify, DLNA, Federation)
# are managed via web UI and stored in settings.json. Only infrastructure
# settings, Plexamp (separate container), and Snapclient (hardware) remain here.
ENV TZ=Etc/UTC \
    PLEXAMP_ENABLED=0 \
    PLEXAMP_SOURCE_NAME=Plexamp \
    PLEXAMP_CLAIM_TOKEN="" \
    PLEXAMP_SERVER_NAME="Plum Audio" \
    PIPE_CONFIG_ENABLED=0 \
    PIPE_SOURCE_NAME=Pipe \
    PIPE_PATH=/tmp/snapfifo \
    PIPE_MODE=create \
    META_CONFIG_ENABLED=0 \
    META_SOURCE_NAME=Mix \
    META_SOURCES="" \
    HTTPS_ENABLED=1 \
    SKIP_CERT_GENERATION=0 \
    SNAPCLIENT_ENABLED=1 \
    SNAPCLIENT_HOST=localhost \
    SNAPCLIENT_SOUNDCARD=hw:Headphones \
    SNAPCLIENT_LATENCY=0 \
    FEDERATION_API_PORT=5000

# Volume mount points
VOLUME ["/app/config", "/app/data", "/app/certs"]

# Supervisord must run as root to manage services with different privilege levels
# Individual services will run as their respective users (snapcast, avahi, etc.)
# Start with setup script which will exec supervisord
CMD ["/bin/bash", "/app/scripts/setup.sh"]