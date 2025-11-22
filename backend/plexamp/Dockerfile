# Minimal Debian-based container for Plexamp headless
# This container runs alongside the Alpine Snapcast container to provide Plex music casting support
# Alpine cannot run Plexamp's pre-compiled native modules due to glibc/musl incompatibility

FROM debian:bookworm-slim

LABEL maintainer="Plum-Snapcast"
LABEL description="Plexamp headless for Plex music casting (Debian sidecar for Alpine Snapcast)"

# Install minimal dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        bzip2 \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 LTS from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends \
        nodejs \
        alsa-utils \
        libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install jq for version detection
RUN apt-get update && \
    apt-get install -y --no-install-recommends jq && \
    rm -rf /var/lib/apt/lists/*

# Create plexamp user (UID 1000 to match Alpine container)
RUN useradd -u 1000 -m -s /bin/bash plexamp

# Create directories
RUN mkdir -p /opt/plexamp /app/plexamp /tmp/plexamp && \
    chown -R plexamp:plexamp /opt/plexamp /app/plexamp /tmp/plexamp

# Download and install Plexamp headless
WORKDIR /tmp/plexamp
RUN PLEXAMP_VERSION=$(curl -s https://plexamp.plex.tv/headless/version.json | jq -r '.latestVersion') && \
    echo "Detected Plexamp version: ${PLEXAMP_VERSION}" && \
    if [ -z "${PLEXAMP_VERSION}" ] || [ "${PLEXAMP_VERSION}" = "null" ]; then \
        echo "ERROR: Failed to detect Plexamp version"; exit 1; \
    fi && \
    echo "Downloading Plexamp-Linux-headless-v${PLEXAMP_VERSION}.tar.bz2..." && \
    curl -fSL "https://plexamp.plex.tv/headless/Plexamp-Linux-headless-v${PLEXAMP_VERSION}.tar.bz2" -o plexamp.tar.bz2 && \
    mkdir -p /opt/plexamp && \
    tar -xjf plexamp.tar.bz2 -C /opt/plexamp --strip-components=1 && \
    rm plexamp.tar.bz2 && \
    chown -R plexamp:plexamp /opt/plexamp && \
    echo "Plexamp v${PLEXAMP_VERSION} installed to /opt/plexamp"

# Configure ALSA to redirect audio to FIFO pipe (shared with Alpine container)
RUN mkdir -p /etc/alsa && \
    echo 'pcm.!default {' > /etc/alsa/asound.conf && \
    echo '    type plug' >> /etc/alsa/asound.conf && \
    echo '    slave.pcm plexamp_fifo' >> /etc/alsa/asound.conf && \
    echo '}' >> /etc/alsa/asound.conf && \
    echo 'pcm.plexamp_fifo {' >> /etc/alsa/asound.conf && \
    echo '    type file' >> /etc/alsa/asound.conf && \
    echo '    slave.pcm null' >> /etc/alsa/asound.conf && \
    echo '    file "/tmp/snapcast-fifos/plexamp-fifo"' >> /etc/alsa/asound.conf && \
    echo '    format "raw"' >> /etc/alsa/asound.conf && \
    echo '}' >> /etc/alsa/asound.conf

# Expose Plexamp web UI and API
EXPOSE 32500

# Environment variables
ENV HOME=/app/plexamp \
    NODE_ENV=production \
    ALSA_CONFIG_PATH=/etc/alsa/asound.conf

# Switch to plexamp user
USER plexamp
WORKDIR /opt/plexamp

# Start Plexamp
CMD ["/usr/bin/node", "/opt/plexamp/js/index.js"]
