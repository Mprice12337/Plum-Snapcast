# Plum Snapcast - Complete Multi-Room Audio System

A complete multi-room audio streaming solution combining Snapcast server/client with a modern React frontend, AirPlay support, and optional Spotify Connect.

## Project Structure

```
plum-snapcast/
├── backend/                    # Snapcast server container
│   ├── Dockerfile             # Multi-arch Alpine-based image
│   ├── config/
│   │   ├── supervisord/       # Process management configs
│   │   └── shairport-sync.conf
│   └── scripts/
│       ├── setup.sh          # Container initialization
│       └── process-airplay-metadata.sh
├── frontend/                  # React/TypeScript web interface
│   ├── Dockerfile            # Nginx-based static hosting
│   └── src/                  # React application
├── docker/                   # Deployment orchestration
│   ├── docker-compose.yml   # Container definitions
│   ├── .env.example         # Configuration template
│   ├── build-and-push.sh    # Multi-arch build script
│   ├── deploy.sh            # Quick deployment script
│   └── README.md
└── scripts/                  # Additional tools (if any)
```

## Features

### Backend (Based on firefrei/docker-snapcast)
- ✅ Snapcast server for synchronized multi-room audio
- ✅ Integrated Snapcast client for audio output
- ✅ AirPlay 1/2 support via shairport-sync
- ✅ Spotify Connect via librespot (optional)
- ✅ HTTPS with automatic certificate generation
- ✅ Supervisord process management
- ✅ Multi-architecture support (amd64, arm64)

### Frontend
- ✅ Modern React/TypeScript interface
- ✅ Real-time Snapcast control
- ✅ Client and group management
- ✅ Volume controls
- ✅ Stream visualization
- ✅ Responsive design

## Quick Start

### Prerequisites

- Docker and Docker Compose
- For building: Docker Buildx (included in Docker Desktop)
- For audio output: ALSA-compatible audio device

### 1. Configure Environment

```bash
cd docker
cp .env.example .env
# Edit .env and set your DOCKER_USERNAME
nano .env
```

### 2. Deploy

**Option A: Use pre-built images** (recommended)
```bash
cd docker
./deploy.sh
```

**Option B: Build your own images**
```bash
cd docker
./build-and-push.sh
./deploy.sh
```

### 3. Access

- **Web Interface**: http://localhost:3000
- **Snapcast Web UI**: http://localhost:1780
- **AirPlay Device**: Look for "Plum Audio" in your device's AirPlay menu

## Building for Multiple Architectures

The project supports building for both amd64 (x86_64) and arm64 (Raspberry Pi, Apple Silicon):

```bash
cd docker
./build-and-push.sh
```

This script:
1. Creates a Docker buildx builder instance
2. Builds both backend and frontend for linux/amd64 and linux/arm64
3. Pushes images to Docker Hub with tags:
   - `latest` (rolling)
   - `YYYYMMDD` (date-based)

## Deployment Targets

### Development Machine (amd64)
```bash
cd docker
docker-compose up -d
```

### Raspberry Pi (arm64)
```bash
cd docker
./deploy.sh
```

### Custom Deployment
```bash
# Pull specific architecture
docker pull --platform linux/arm64 your-username/plum-snapcast-server:latest

# Or use docker-compose with pre-built images
cd docker
docker-compose pull
docker-compose up -d
```

## Configuration

All configuration is done through environment variables in `docker/.env`:

### Core Settings
- `DOCKER_USERNAME`: Your Docker Hub username (required for build)
- `TZ`: Timezone (default: America/Los_Angeles)
- `FRONTEND_PORT`: Web interface port (default: 3000)

### Audio Settings
- `AIRPLAY_DEVICE_NAME`: Name shown in AirPlay menu (default: "Plum Audio")
- `SNAPCLIENT_SOUNDCARD`: ALSA audio device (default: hw:Headphones)
- `SNAPCLIENT_LATENCY`: Audio latency in ms (default: 0)

### Optional Features
- `SPOTIFY_CONFIG_ENABLED`: Enable Spotify Connect (0 or 1)
- `SPOTIFY_DEVICE_NAME`: Name in Spotify app
- `SPOTIFY_ACCESS_TOKEN`: Spotify API token

See `docker/.env.example` for complete list.

## Raspberry Pi Setup

### One-Time Audio Configuration

The backend is configured to work with Raspberry Pi's audio output. If you're deploying on a Pi:

1. **Force 3.5mm audio output**:
   ```bash
   sudo raspi-config
   # System Options → Audio → Force 3.5mm jack
   ```

2. **Set audio permissions** (already handled in Dockerfile, but verify):
   ```bash
   # Check audio device ownership
   ls -l /dev/snd/
   # Should show group 29 (audio)
   ```

3. **Deploy**:
   ```bash
   cd docker
   ./deploy.sh
   ```

## Troubleshooting

### No Audio Output

```bash
# Check if snapclient is running
docker exec plum-snapcast-server ps aux | grep snapclient

# View snapclient logs
docker-compose logs snapcast-server | grep snapclient

# Test audio device access
docker exec plum-snapcast-server aplay -l
```

### AirPlay Device Not Visible

```bash
# Check avahi is running
docker exec plum-snapcast-server ps aux | grep avahi

# Restart services
docker-compose restart snapcast-server
```

### Container Won't Start

```bash
# View full logs
docker-compose logs snapcast-server

# Check audio device permissions on host
ls -la /dev/snd/

# Ensure privileged mode is enabled in docker-compose.yml
```

### Build Errors

```bash
# Clear Docker cache
docker builder prune -a

# Rebuild without cache
docker-compose build --no-cache

# Check buildx
docker buildx version
docker buildx ls
```

## Architecture

### Container Communication

```
┌─────────────────────────────────────────────────────────┐
│                    Host Network                          │
│                                                          │
│  ┌──────────────────────────────────────────────┐      │
│  │  Backend Container (network_mode: host)      │      │
│  │  ┌────────────┐  ┌─────────────┐             │      │
│  │  │  Snapcast  │  │  Shairport  │             │      │
│  │  │  Server    │←─│  -Sync      │             │      │
│  │  │ :1704-1705 │  │  (AirPlay)  │             │      │
│  │  └─────┬──────┘  └─────────────┘             │      │
│  │        │                                       │      │
│  │        │         ┌─────────────┐             │      │
│  │        └────────→│  Snapclient │──→ 🔊       │      │
│  │                  │  (Audio Out)│             │      │
│  │                  └─────────────┘             │      │
│  └──────────────────────────────────────────────┘      │
│                                                          │
│  ┌──────────────────────────────────────────────┐      │
│  │  Frontend Container                          │      │
│  │  Nginx serving React app on :3000           │      │
│  │  WebSocket to Snapcast :1704                │      │
│  └──────────────────────────────────────────────┘      │
│                                                          │
└─────────────────────────────────────────────────────────┘
              │                                    │
         AirPlay from                        Browser access
         iOS/macOS                           http://localhost:3000
```

### Audio Flow

```
AirPlay Device → Shairport-Sync → FIFO Pipe → Snapcast Server
                                                      ↓
                                              Snapcast Client → Speaker
```

## Development

### Making Changes

1. **Backend changes**:
   ```bash
   cd backend
   # Edit files...
   cd ../docker
   docker-compose build snapcast-server
   docker-compose up -d snapcast-server
   ```

2. **Frontend changes**:
   ```bash
   cd frontend
   # Edit files...
   cd ../docker
   docker-compose build snapcast-frontend
   docker-compose up -d snapcast-frontend
   ```

3. **Test locally**, then push:
   ```bash
   cd docker
   ./build-and-push.sh
   ```

## Attribution

This project builds upon:

- **[firefrei/docker-snapcast](https://github.com/firefrei/docker-snapcast)** by Matthias Frei
  - Backend architecture and configuration
  - Supervisord setup
  - Multi-service Docker container design

- **[Snapcast](https://github.com/badaix/snapcast)** by Johannes Pohl
  - Core synchronization technology

- **[Shairport-Sync](https://github.com/mikebrady/shairport-sync)** by Mike Brady
  - AirPlay receiver implementation

- **[Librespot](https://github.com/librespot-org/librespot)**
  - Spotify Connect client

## License

- Frontend: [Your License]
- Backend modifications: Same as firefrei/docker-snapcast
- Components: Respective original licenses

## Support

For issues:
1. Check logs: `docker-compose logs -f`
2. Review troubleshooting section above
3. Check original repos for component-specific issues:
   - [Snapcast Issues](https://github.com/badaix/snapcast/issues)
   - [firefrei/docker-snapcast Issues](https://github.com/firefrei/docker-snapcast/issues)

## Roadmap

- [ ] Additional streaming sources (Line-in, Bluetooth)
- [ ] Advanced frontend features (EQ, room correction)
- [ ] Home Assistant integration
- [ ] Kubernetes deployment manifests
- [ ] Automated testing
