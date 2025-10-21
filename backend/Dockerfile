FROM alpine:3.19

# Build arguments for multi-platform support
ARG TARGETPLATFORM
ARG BUILDPLATFORM

LABEL maintainer="Plum-Snapcast"
LABEL description="Snapcast server with AirPlay and Spotify support"

# Install runtime dependencies
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
    ffmpeg-libs

# Install build dependencies
RUN apk add --no-cache --virtual .build-deps \
    git \
    build-base \
    autoconf \
    automake \
    libtool \
    alsa-lib-dev \
    avahi-dev \
    libconfig-dev \
    libsndfile-dev \
    popt-dev \
    openssl-dev \
    libsodium-dev \
    libdaemon-dev \
    libplist-dev \
    glib-dev \
    dbus-dev \
    mbedtls-dev \
    soxr-dev \
    libgcrypt-dev \
    ffmpeg-dev \
    cargo \
    rust

# Install snapcast from Alpine edge repository
RUN echo "@edge http://dl-cdn.alpinelinux.org/alpine/edge/testing" >> /etc/apk/repositories && \
    apk add --no-cache snapcast-server@edge snapcast-client@edge

# Build shairport-sync with metadata and AirPlay support
WORKDIR /tmp
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

# Build librespot for Spotify Connect
RUN cargo install librespot --no-default-features --features "alsa-backend with-dns-sd" && \
    cp /root/.cargo/bin/librespot /usr/local/bin/

# Cleanup build dependencies
RUN apk del .build-deps && \
    rm -rf /root/.cargo /var/cache/apk/* /tmp/*

# Create snapcast user and group (GID 29 matches audio group on Raspberry Pi)
RUN addgroup -g 29 audio || true && \
    addgroup -g 1000 snapcast && \
    adduser -D -u 1000 -G snapcast -h /app snapcast && \
    addgroup snapcast audio

# Create required directories
RUN mkdir -p \
    /app/config \
    /app/data \
    /app/certs \
    /app/scripts \
    /app/supervisord \
    /tmp/snapfifo \
    /var/run/dbus \
    /var/run/avahi-daemon \
    && chown -R snapcast:snapcast /app /tmp/snapfifo

# Copy configuration and scripts
COPY config/supervisord/ /app/supervisord/
COPY config/shairport-sync.conf /app/config/
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh && \
    chown -R snapcast:snapcast /app

# Expose ports
# Snapcast: 1704-1705 (control/stream), 1780 (HTTP), 1788 (HTTPS)
# Shairport-Sync: 3689, 5000, 5353, 6000-6009/udp, 7000
EXPOSE 1704 1705 1780 1788 3689 5000 5353 6000-6009/udp 7000

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

# Run as snapcast user
USER snapcast

# Start with setup script
CMD ["/bin/bash", "/app/scripts/setup.sh"]
