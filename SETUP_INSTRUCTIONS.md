# Plum Snapcast Setup Instructions

## What's Been Created

I've set up a complete backend infrastructure based on the FireFrei Snapcast package on GitHub. Here's what you have:

### Directory Structure

```
plum-snapcast/
├── backend/                              # Snapcast server container
│   ├── Dockerfile                       # Multi-arch Alpine-based build
│   ├── .dockerignore                    # Build exclusions
│   ├── README.md                        # Backend documentation
│   ├── config/
│   │   ├── supervisord/
│   │   │   ├── supervisord.conf        # Main supervisor config
│   │   │   ├── snapcast.ini            # Snapcast services
│   │   │   └── snapclient.ini          # Snapclient audio output
│   │   └── shairport-sync.conf         # AirPlay configuration
│   └── scripts/
│       ├── setup.sh                     # Container initialization
│       └── process-airplay-metadata.sh  # Metadata handler
│
├── docker/                               # Deployment orchestration  
│   ├── docker-compose.yml               # Full stack definition
│   ├── .env.example                     # Configuration template
│   ├── build-and-push.sh                # Multi-arch build script
│   ├── deploy.sh                        # Quick deployment
│   └── README.md                        # Docker documentation
│
└── PROJECT_OVERVIEW.md                  # Complete project guide
```

## Quick Start Guide

### Step 1: Configure Environment

```bash
cd docker
cp .env.example .env
# Edit .env and set your DOCKER_USERNAME
nano .env
```

### Step 2: Build Multi-Architecture Images

The `build-and-push.sh` script builds for both amd64 and arm64:

```bash
cd docker
./build-and-push.sh
```

This will:
- Create a Docker buildx builder
- Build backend for linux/amd64 and linux/arm64
- Build frontend for linux/amd64 and linux/arm64  
- Push to Docker Hub with tags `latest` and date-based

### Step 3: Deploy

```bash
cd docker
./deploy.sh
```

Or manually:

```bash
docker-compose up -d
```

## What the Backend Includes

### Based on firefrei/docker-snapcast

The backend is a faithful recreation of the firefrei/docker-snapcast repository with:

✅ **Snapcast Server** - Multi-room audio synchronization  
✅ **Snapcast Client** - Integrated audio output for single-device setups  
✅ **AirPlay Support** - Via shairport-sync with metadata  
✅ **Spotify Connect** - Via librespot (optional)  
✅ **Supervisord** - Process management for all services  
✅ **Avahi** - mDNS service discovery  
✅ **HTTPS** - Automatic self-signed certificate generation  
✅ **Multi-arch** - Builds for amd64 and arm64  

### Key Features

1. **Multi-Architecture Builds**
   - linux/amd64 for x86_64 systems
   - linux/arm64 for Raspberry Pi 4/5

2. **Environment-Based Configuration**
   - All settings via environment variables
   - No manual config file editing needed

3. **Integrated Services**
   - All audio services in one container
   - Simplified deployment

4. **Audio Group Compatibility**
   - GID 29 matches Raspberry Pi audio group
   - Proper device permissions

## Docker Compose Configuration

The `docker-compose.yml` file orchestrates both backend and frontend:

- **Backend**: Uses `network_mode: host` for proper mDNS
- **Frontend**: Standard port mapping on 3000
- **Volumes**: Persistent config, data, and certificates
- **Health checks**: Both services monitored

## Build Scripts

### build-and-push.sh

Builds and pushes multi-architecture images:

```bash
#!/bin/bash
# Automatically builds for linux/amd64,linux/arm64
# Tags with 'latest' and date-based tags
# Pushes to Docker Hub
```

Features:
- Creates buildx builder if needed
- Builds both backend and frontend
- Tags with latest and YYYYMMDD
- Colored output for clarity

### deploy.sh

Quick deployment script:

```bash
#!/bin/bash
# Pulls latest images
# Stops existing containers
# Starts new containers
# Shows logs and status
```

## Configuration

All configuration is via `docker/.env`:

### Required
- `DOCKER_USERNAME` - Your Docker Hub username

### Common Settings
- `AIRPLAY_DEVICE_NAME` - Name in AirPlay menu (default: "Plum Audio")
- `FRONTEND_PORT` - Web UI port (default: 3000)
- `SNAPCLIENT_SOUNDCARD` - ALSA device (default: hw:Headphones)
- `TZ` - Timezone

### Optional Features
- `SPOTIFY_CONFIG_ENABLED` - Enable Spotify Connect (0 or 1)
- `SPOTIFY_ACCESS_TOKEN` - Spotify API token
- `HTTPS_ENABLED` - Enable HTTPS (default: 1)

See `.env.example` for complete list.

## Raspberry Pi Deployment

For Raspberry Pi, the setup handles:

1. **Audio Group** - GID 29 matches Pi's audio group
2. **Device Access** - Privileged mode for /dev/snd
3. **Network** - Host mode for AirPlay discovery

### One-Time Pi Setup

```bash
# Force 3.5mm audio
sudo raspi-config
# System Options → Audio → Force 3.5mm jack

# Deploy
cd docker
./deploy.sh
```

## Troubleshooting

### No Audio
```bash
# Check snapclient
docker exec plum-snapcast-server ps aux | grep snapclient

# View logs
docker-compose logs snapcast-server | grep snapclient

# Test device
docker exec plum-snapcast-server aplay -l
```

### AirPlay Not Visible
```bash
# Check avahi
docker exec plum-snapcast-server ps aux | grep avahi

# Restart
docker-compose restart snapcast-server
```

### Build Issues
```bash
# Clear cache
docker builder prune -a

# Rebuild
docker-compose build --no-cache
```

## Accessing Services

After deployment:

- **Frontend**: http://localhost:3000
- **Snapcast Web UI**: http://localhost:1780
- **AirPlay Device**: Look for "Plum Audio" in AirPlay menu

## Next Steps

1. Review the configuration in `docker/.env.example`
2. Build your images: `cd docker && ./build-and-push.sh`
3. Deploy: `./deploy.sh`
4. Test AirPlay from iPhone/Mac
5. Check web interface at http://localhost:3000

## Attribution

This backend is based on:
- [firefrei/docker-snapcast](https://github.com/firefrei/docker-snapcast) by Matthias Frei
- [Snapcast](https://github.com/badaix/snapcast) by Johannes Pohl
- [Shairport-Sync](https://github.com/mikebrady/shairport-sync) by Mike Brady
- [Librespot](https://github.com/librespot-org/librespot) by the Librespot team

## Support

For detailed information, see:
- `backend/README.md` - Backend specifics
- `docker/README.md` - Docker and deployment details
- `PROJECT_OVERVIEW.md` - Complete project architecture

---

**Important**: Your frontend should remain unchanged. These backend files integrate with your existing React frontend through the Snapcast WebSocket API on port 1704.
