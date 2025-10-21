# Plum Snapcast Backend

This backend is based on the [firefrei/docker-snapcast](https://github.com/firefrei/docker-snapcast) repository and provides a complete Snapcast server with AirPlay and Spotify support.

## Features

- **Snapcast Server**: Multi-room audio synchronization
- **Snapcast Client**: Integrated audio output (for single-device deployments)
- **AirPlay Support**: Stream from iOS/macOS devices via shairport-sync
- **Spotify Connect**: Stream from Spotify app via librespot
- **Supervisord**: Process management for all services
- **Avahi**: mDNS service discovery for AirPlay
- **HTTPS Support**: Automatic self-signed certificate generation

## Directory Structure

```
backend/
├── Dockerfile                      # Multi-arch container build
├── config/
│   ├── shairport-sync.conf        # AirPlay receiver configuration
│   └── supervisord/
│       ├── supervisord.conf       # Main supervisor config
│       ├── snapcast.ini           # Snapcast services
│       └── snapclient.ini         # Snapclient audio output
└── scripts/
    ├── setup.sh                   # Container startup script
    └── process-airplay-metadata.sh # AirPlay metadata handler
```

## Building

### Local Build
```bash
docker build -t plum-snapcast-server:latest .
```

### Multi-Architecture Build
```bash
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag your-username/plum-snapcast-server:latest \
    --push \
    .
```

## Configuration

All configuration is done via environment variables. See the parent `docker/docker-compose.yml` for available options.

### Key Environment Variables

- `AIRPLAY_CONFIG_ENABLED`: Enable AirPlay (default: 1)
- `AIRPLAY_DEVICE_NAME`: Name shown in AirPlay devices list
- `SPOTIFY_CONFIG_ENABLED`: Enable Spotify Connect (default: 0)
- `SNAPCLIENT_ENABLED`: Enable integrated audio output (default: 1)
- `SNAPCLIENT_SOUNDCARD`: ALSA device for audio output
- `HTTPS_ENABLED`: Enable HTTPS (default: 1)

## Ports

- `1704-1705`: Snapcast control and stream
- `1780`: HTTP web interface
- `1788`: HTTPS web interface
- `3689, 5000, 5353, 6000-6009`: AirPlay ports
- `7000`: AirPlay 2 (if enabled)

## Attribution

This backend is based on the excellent work by:
- **firefrei/docker-snapcast**: Matthias Frei (mf@frei.media)
- **Snapcast**: Johannes Pohl
- **Shairport-Sync**: Mike Brady
- **Librespot**: Librespot contributors

## License

Same as the original firefrei/docker-snapcast repository.
