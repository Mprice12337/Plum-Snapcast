# Stage 1: Build base snapcast image with server and client
FROM alpine:edge AS snapcast-base

# Install snapcast server, client, and web interface
RUN apk add --no-cache snapcast-server snapcast-client \
    && wget -O /tmp/snapweb.zip https://github.com/badaix/snapweb/releases/latest/download/snapweb.zip \
    && unzip -o /tmp/snapweb.zip -d /usr/share/snapserver/snapweb/ \
    && rm /tmp/snapweb.zip

# Stage 2: Add AirPlay support via shairport-sync
FROM snapcast-base AS snapcast-airplay

# Install runtime dependencies for shairport-sync
RUN apk add --no-cache dbus popt openssl soxr avahi libconfig glib alsa-lib alsa-utils

# Install build dependencies and build shairport-sync from source
RUN apk add --no-cache --virtual .build-deps \
        git build-base autoconf automake libtool \
        popt-dev openssl-dev soxr-dev avahi-dev libconfig-dev \
        glib-dev alsa-lib-dev \
    && mkdir -p /app/build \
    && cd /app/build \
    && git clone --depth 1 --branch master https://github.com/mikebrady/shairport-sync.git \
    && cd shairport-sync \
    && autoreconf -fi \
    && ./configure \
        --prefix=/usr/local \
        --with-alsa \
        --with-soxr \
        --with-avahi \
        --with-ssl=openssl \
        --with-stdout \
        --with-pipe \
        --with-dbus-interface \
        --with-metadata \
        --sysconfdir=/etc \
    && make -j$(nproc) \
    && make install \
    && cd / \
    && rm -rf /app/build \
    && apk del .build-deps

# Stage 3: Add Spotify support (optional - we'll disable by default)
FROM snapcast-airplay AS snapcast-spotify

RUN apk add --no-cache --virtual .build-deps \
        git cargo build-base alsa-lib-dev protobuf-dev \
    && mkdir -p /app/build \
    && cd /app/build \
    && git clone --depth 1 --branch v0.5.0 https://github.com/librespot-org/librespot.git \
    && cd librespot \
    && cargo build --release --no-default-features --features alsa-backend \
    && cp target/release/librespot /usr/local/bin/ \
    && cd / \
    && rm -rf /app/build /root/.cargo \
    && apk del .build-deps

# Stage 4: Final image with all components
FROM snapcast-spotify AS final

# Set environment variables with defaults
ENV TZ="Etc/UTC"
ENV AIRPLAY_CONFIG_ENABLED="1"
ENV AIRPLAY_SOURCE_NAME="Airplay"
ENV AIRPLAY_DEVICE_NAME="Snapcast"
ENV SPOTIFY_CONFIG_ENABLED="0"
ENV SPOTIFY_SOURCE_NAME="Spotify"
ENV SPOTIFY_DEVICE_NAME="Snapcast"
ENV SPOTIFY_BITRATE="320"
ENV SPOTIFY_ACCESS_TOKEN=""
ENV PIPE_CONFIG_ENABLED="0"
ENV PIPE_SOURCE_NAME="Pipe"
ENV PIPE_PATH="/tmp/snapfifo"
ENV PIPE_MODE="create"
ENV META_CONFIG_ENABLED="0"
ENV META_SOURCE_NAME="Mix"
ENV META_SOURCES=""
ENV SOURCE_CUSTOM=""
ENV HTTPS_ENABLED="1"
ENV SKIP_CERT_GENERATION="0"
ENV CERT_SERVER_CN="snapserver"
ENV CERT_SERVER_DNS="snapserver snapserver.local"

# Snapclient configuration for local audio output
ENV SNAPCLIENT_ENABLED="1"
ENV SNAPCLIENT_HOST="localhost"
ENV SNAPCLIENT_SOUNDCARD="plughw:1,0"
ENV SNAPCLIENT_LATENCY="0"

# Supervisord configuration path (so supervisorctl knows where to find it)
ENV SUPERVISOR_CONF="/app/supervisord/supervisord.conf"

# Install supervisor and utilities
RUN apk add --no-cache supervisor tzdata curl bash openssl

# Create non-root user and required directories
RUN addgroup -g 1000 snapcast \
    && adduser -D -u 1000 -G snapcast -s /bin/sh snapcast \
    && mkdir -p /app/config /app/data /app/certs /tmp/metadata \
    && mkdir -p /app/supervisord /run/supervisord /var/log/supervisord \
    && mkdir -p /var/run/dbus \
    && chown -R snapcast:snapcast /app /tmp/metadata /var/log/supervisord /run/supervisord

# Copy supervisord main config
RUN cp /etc/supervisord.conf /app/supervisord/supervisord.conf \
    && sed -i 's|^files =.*|files = /app/supervisord/*.ini|g' /app/supervisord/supervisord.conf \
    && sed -i 's|/run/supervisord.sock|/run/supervisord/supervisord.sock|g' /app/supervisord/supervisord.conf \
    && ln -sf /app/supervisord/supervisord.conf /etc/supervisord.conf

# Copy configuration files
COPY --chown=snapcast:snapcast config/supervisord/*.ini /app/supervisord/
COPY --chown=snapcast:snapcast --chmod=0755 setup.sh gen-certs.sh healthcheck.sh /app/

USER snapcast:snapcast
WORKDIR /app

VOLUME ["/app/config", "/app/data", "/app/certs"]

# Expose ports
# Snapcast: 1704-1705 (control/audio), 1780 (HTTP), 1788 (HTTPS)
# AirPlay: 3689, 5000, 6000-6009/udp, 5353 (mDNS)
EXPOSE 1704-1705 1780 1788 3689 5000 6000-6009/udp 5353

HEALTHCHECK CMD ["/bin/sh", "/app/healthcheck.sh"]

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["set -e && /app/setup.sh && exec /usr/bin/supervisord -c /app/supervisord/supervisord.conf"]