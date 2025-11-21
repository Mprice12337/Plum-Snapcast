FROM alpine:3.19

# Build arguments for multi-platform support
ARG TARGETPLATFORM
ARG BUILDPLATFORM

LABEL maintainer="Plum-Snapcast"
LABEL description="Snapcast server with AirPlay, Bluetooth, Spotify, DLNA/UPnP, and Plexamp support"

# Install runtime dependencies (python3 for metadata, nodejs for Plexamp, GStreamer for DLNA)
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
    py3-dbus \
    py3-gobject3 \
    py3-requests \
    bluez \
    bluez-alsa \
    util-linux \
    nodejs \
    npm \
    gstreamer \
    gst-plugins-base \
    gst-plugins-good \
    gst-plugins-bad \
    gst-plugins-ugly \
    gst-libav \
    libupnp

# Add edge repository and install snapcast
RUN echo "@edge http://dl-cdn.alpinelinux.org/alpine/edge/testing" >> /etc/apk/repositories && \
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

# Build shairport-sync with metadata and AirPlay support
RUN git clone --depth 1 --branch master https://github.com/mikebrady/shairport-sync.git && \
    cd shairport-sync && \
    autoreconf -fi && \
    ./configure \
        --sysconfdir=/etc \
        --with-alsa \
        --with-avahi \
        --with-ssl=openssl \
        --with-metadata \
        --with-dbus-interface \
        --with-stdout \
        --with-pipe \
        --with-apple-alac && \
    make -j$(nproc) && \
    make install && \
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

# Download and install Plexamp headless
# Plexamp requires Node.js 20+ and runs as a standalone application
WORKDIR /tmp
RUN PLEXAMP_VERSION=$(curl -s https://plexamp.plex.tv/headless/version.json | sed -n 's/.*"latestVersion":"\([^"]*\)".*/\1/p') && \
    echo "Detected Plexamp version: ${PLEXAMP_VERSION}" && \
    if [ -z "${PLEXAMP_VERSION}" ]; then echo "ERROR: Failed to detect Plexamp version"; exit 1; fi && \
    if [ "$(uname -m)" = "aarch64" ]; then \
        PLEXAMP_ARCH="arm64"; \
    else \
        PLEXAMP_ARCH="x64"; \
    fi && \
    echo "Downloading Plexamp-Linux-headless-v${PLEXAMP_VERSION}-${PLEXAMP_ARCH}.tar.bz2..." && \
    curl -fSL "https://plexamp.plex.tv/headless/Plexamp-Linux-headless-v${PLEXAMP_VERSION}-${PLEXAMP_ARCH}.tar.bz2" -o plexamp.tar.bz2 && \
    mkdir -p /opt/plexamp && \
    tar -xjf plexamp.tar.bz2 -C /opt/plexamp --strip-components=1 && \
    rm plexamp.tar.bz2 && \
    chmod +x /opt/plexamp/js/index.js && \
    echo "Plexamp v${PLEXAMP_VERSION} installed to /opt/plexamp"

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
    adduser -S -G messagebus -H -s /sbin/nologin messagebus 2>/dev/null || true

# Configure D-Bus machine-id (required for D-Bus to create socket)
RUN mkdir -p /var/lib/dbus && \
    dbus-uuidgen > /var/lib/dbus/machine-id

# Copy D-Bus policy files for shairport-sync and spotifyd
RUN mkdir -p /etc/dbus-1/system.d
COPY config/shairport-sync-dbus.conf /etc/dbus-1/system.d/
COPY config/spotifyd-dbus.conf /etc/dbus-1/system.d/

# Configure Avahi
RUN mkdir -p /run/avahi-daemon /var/run/dbus && \
    chmod 755 /run/avahi-daemon /var/run/dbus

# FIXED: Copy configuration files
COPY config/avahi-daemon.conf /etc/avahi/avahi-daemon.conf
COPY config/shairport-sync.conf /app/config/
COPY config/spotifyd.conf /app/config/


# Create required directories
# Note: /tmp/snapfifo is created by setup.sh as a FIFO pipe, not a directory
RUN mkdir -p \
    /app/config \
    /app/data \
    /app/certs \
    /app/scripts \
    /app/supervisord \
    /app/plexamp \
    /var/run/dbus \
    /var/run/avahi-daemon \
    /var/log/supervisord \
    /usr/share/snapserver/snapweb/coverart \
    && chown -R snapcast:snapcast /app \
    && chown -R snapcast:snapcast /opt/plexamp \
    && chmod 755 /var/run/dbus \
    && chmod 755 /var/run/avahi-daemon \
    && chmod 755 /var/log/supervisord \
    && chown -R snapcast:snapcast /usr/share/snapserver/snapweb \
    && chmod 755 /usr/share/snapserver/snapweb

# Copy configuration and scripts (copy all scripts at once)
COPY config/supervisord/ /app/supervisord/
COPY config/shairport-sync.conf /app/config/
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh /app/scripts/*.py 2>/dev/null || true && \
    chown -R snapcast:snapcast /app

# Expose ports
# Snapcast: 1704-1705 (control/stream), 1780 (HTTP), 1788 (HTTPS)
# Shairport-Sync: 3689, 5000, 5353, 6000-6009/udp, 7000
# Plexamp: 32500 (HTTP API and web UI)
# Metadata Debug Server: 8080 (HTTP)
EXPOSE 1704 1705 1780 1788 3689 5000 5353 6000-6009/udp 7000 8080 32500

# Set working directory
WORKDIR /app

# Environment variables with defaults
ENV TZ=Etc/UTC \
    AIRPLAY_CONFIG_ENABLED=1 \
    AIRPLAY_SOURCE_NAME=Airplay \
    AIRPLAY_DEVICE_NAME="Plum Audio" \
    SPOTIFY_CONFIG_ENABLED=0 \
    SPOTIFY_SOURCE_NAME=Spotify \
    SPOTIFY_DEVICE_NAME=Snapcast \
    SPOTIFY_BITRATE=320 \
    SPOTIFY_ACCESS_TOKEN="" \
    BLUETOOTH_ENABLED=0 \
    BLUETOOTH_SOURCE_NAME=Bluetooth \
    BLUETOOTH_DEVICE_NAME="Plum Audio" \
    BLUETOOTH_ADAPTER=hci0 \
    BLUETOOTH_DEVICE_PATH="" \
    BLUETOOTH_AUTO_PAIR=1 \
    BLUETOOTH_DISCOVERABLE=1 \
    DLNA_ENABLED=0 \
    DLNA_SOURCE_NAME=DLNA \
    DLNA_DEVICE_NAME="Plum Audio" \
    DLNA_UUID="" \
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
    CERT_SERVER_CN=snapserver \
    CERT_SERVER_DNS="snapserver snapserver.local" \
    SNAPCLIENT_ENABLED=1 \
    SNAPCLIENT_HOST=localhost \
    SNAPCLIENT_SOUNDCARD=hw:Headphones \
    SNAPCLIENT_LATENCY=0

# Volume mount points
VOLUME ["/app/config", "/app/data", "/app/certs"]

# Supervisord must run as root to manage services with different privilege levels
# Individual services will run as their respective users (snapcast, avahi, etc.)
# Start with setup script which will exec supervisord
CMD ["/bin/bash", "/app/scripts/setup.sh"]