FROM alpine:3.19

# Build arguments for multi-platform support
ARG TARGETPLATFORM
ARG BUILDPLATFORM

LABEL maintainer="Plum-Snapcast"
LABEL description="Snapcast server with AirPlay, Bluetooth, and Spotify support"

# Install runtime dependencies (ADDED python3 for metadata processor)
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
    bluez \
    bluez-alsa \
    util-linux

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
    ffmpeg-dev

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

# Build spotifyd from source with D-Bus MPRIS support
# spotifyd is a Spotify daemon built on librespot with working MPRIS support
# This provides both metadata and playback controls via D-Bus
# Use dynamic linking for system libraries (ALSA, OpenSSL, D-Bus)
RUN . $HOME/.cargo/env && \
    git clone --depth 1 https://github.com/Spotifyd/spotifyd.git && \
    cd spotifyd && \
    RUSTFLAGS="-C target-feature=-crt-static" \
    cargo build --release --no-default-features --features "alsa_backend,dbus_mpris" && \
    cp target/release/spotifyd /usr/local/bin/spotifyd && \
    chmod +x /usr/local/bin/spotifyd && \
    cd .. && \
    rm -rf spotifyd $HOME/.cargo $HOME/.rustup

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

# Configure Avahi
RUN mkdir -p /run/avahi-daemon /var/run/dbus /etc/avahi/services && \
    chmod 755 /run/avahi-daemon /var/run/dbus /etc/avahi/services

# FIXED: Copy configuration files
COPY config/avahi-daemon.conf /etc/avahi/avahi-daemon.conf
COPY config/spotify-connect.service /etc/avahi/services/
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
    /var/run/dbus \
    /var/run/avahi-daemon \
    /var/log/supervisord \
    /usr/share/snapserver/snapweb/coverart \
    && chown -R snapcast:snapcast /app \
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
# Metadata Debug Server: 8080 (HTTP)
EXPOSE 1704 1705 1780 1788 3689 5000 5353 6000-6009/udp 7000 8080

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