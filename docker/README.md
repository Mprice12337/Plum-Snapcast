# Plum Snapcast Docker Deployment

This directory contains Docker Compose configuration and deployment scripts for the Plum Snapcast project.

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env and set your DOCKER_USERNAME
nano .env
```

### 2. Deploy (using pre-built images)

```bash
./deploy.sh
```

### 3. Build and Push Your Own Images

```bash
./build-and-push.sh
```

## Files

- `docker-compose.yml`: Container orchestration configuration
- `.env.example`: Template for environment variables
- `build-and-push.sh`: Multi-architecture build and push script
- `deploy.sh`: Quick deployment script

## Environment Variables

See `.env.example` for all available configuration options.

### Required

- `DOCKER_USERNAME`: Your Docker Hub username

### Optional

- `TZ`: Timezone (default: America/Los_Angeles)
- `AIRPLAY_DEVICE_NAME`: Name for AirPlay device (default: Plum Audio)
- `FRONTEND_PORT`: Port for web interface (default: 3000)
- `SNAPCLIENT_SOUNDCARD`: ALSA audio device (default: hw:Headphones)
- `SPOTIFY_CONFIG_ENABLED`: Enable Spotify Connect (default: 0)
- `SPOTIFY_ACCESS_TOKEN`: Spotify API token (optional)

## Building Images

The `build-and-push.sh` script builds both backend and frontend for multiple architectures:

- `linux/amd64`: x86_64 systems
- `linux/arm64`: Raspberry Pi 4/5, Apple Silicon

```bash
cd docker
./build-and-push.sh
```

This will:
1. Create a Docker buildx builder (if needed)
2. Build both images for both architectures
3. Push to Docker Hub with tags:
   - `latest`
   - `YYYYMMDD` (date-based tag)

## Deploying

### On Development Machine

```bash
cd docker
docker-compose up -d
```

### On Raspberry Pi

```bash
cd docker
./deploy.sh
```

Or manually:

```bash
docker-compose pull
docker-compose up -d
```

## Accessing Services

After deployment:

- **Snapcast Web UI**: http://localhost:1780
- **Frontend**: http://localhost:3000 (or your configured `FRONTEND_PORT`)
- **AirPlay Device**: Look for "Plum Audio" (or your configured name) in AirPlay devices

## Troubleshooting

### View Logs

```bash
docker-compose logs -f
```

### View Specific Service Logs

```bash
docker-compose logs -f snapcast-server
docker-compose logs -f snapcast-frontend
```

### Restart Services

```bash
docker-compose restart
```

### Check Audio Devices (on host)

```bash
aplay -l
```

### Check Container Audio Access

```bash
docker exec plum-snapcast-server aplay -l
```

### Rebuild Containers

```bash
docker-compose down
docker-compose build
docker-compose up -d
```

## Network Configuration

The backend uses `network_mode: host` for proper mDNS broadcasting (required for AirPlay discovery). This means:

- Backend services are directly accessible on host ports
- No port mapping needed for backend
- Frontend still uses port mapping (default 3000:80)

## Volume Persistence

Data is persisted in named Docker volumes:

- `snapcast-config`: Server configuration files
- `snapcast-data`: Runtime data (server.json, etc.)
- `snapcast-certs`: SSL certificates

To backup:

```bash
docker run --rm -v snapcast-config:/data -v $(pwd):/backup alpine tar czf /backup/snapcast-backup.tar.gz /data
```

To restore:

```bash
docker run --rm -v snapcast-config:/data -v $(pwd):/backup alpine tar xzf /backup/snapcast-backup.tar.gz -C /
```

## Advanced Configuration

### Custom Snapserver Configuration

To provide your own `snapserver.conf`:

1. Create the file in `volumes/config/snapserver.conf`
2. Mount it in docker-compose.yml:
   ```yaml
   volumes:
     - ./volumes/config/snapserver.conf:/app/config/snapserver.conf:ro
   ```

### Enable Spotify Connect

1. Get access token: https://developer.spotify.com/documentation/web-playback-sdk/tutorials/getting-started
2. Set in `.env`:
   ```
   SPOTIFY_CONFIG_ENABLED=1
   SPOTIFY_ACCESS_TOKEN=your-token-here
   ```
3. Restart: `docker-compose restart`

## Multi-Architecture Support

The build script creates images for both amd64 and arm64:

- **amd64**: Regular PCs, Intel/AMD servers
- **arm64**: Raspberry Pi 4/5, Apple Silicon Macs

Docker will automatically pull the correct architecture for your platform.

## Contributing

When modifying:

1. Test locally: `docker-compose build && docker-compose up -d`
2. Build for all platforms: `./build-and-push.sh`
3. Test on target platform (e.g., Raspberry Pi)

## Links

- [Snapcast](https://github.com/badaix/snapcast)
- [firefrei/docker-snapcast](https://github.com/firefrei/docker-snapcast)
- [Docker Buildx](https://docs.docker.com/buildx/working-with-buildx/)
