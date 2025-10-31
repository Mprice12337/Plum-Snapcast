# CLAUDE.md - Plum-Snapcast Development Guide

This file contains essential information for Claude to work effectively with the Plum-Snapcast codebase.

## Project Overview

**Plum-Snapcast** is a comprehensive multi-room audio streaming solution that combines a Snapcast server backend with a modern React/TypeScript frontend. The application enables synchronized audio playback across multiple devices/rooms with support for AirPlay, Spotify Connect, and direct streaming sources.

### Key Features
- **Multi-room audio synchronization**: Precise synchronization of audio playback across multiple client devices
- **Hardware audio output**: Integrated snapclient outputs audio to Raspberry Pi 3.5mm jack
- **Modern web interface**: React-based UI for controlling audio streams, managing clients, and adjusting volume
- **Real-time control**: WebSocket-based communication for immediate feedback and control
- **Multiple audio sources**: Support for AirPlay (1 and 2), Spotify Connect, FIFO pipes, and custom sources
- **Metadata display**: Real-time display of currently playing tracks with album art
- **Volume management**: Individual and group volume control with mute functionality
- **Stream switching**: Easy switching between different audio sources

## Technology Stack

### Backend
- **Framework**: Docker container with Alpine Linux base
- **Audio Server**: Snapcast server (from Alpine edge repositories)
- **Audio Client**: Snapcast client (integrated, outputs to hardware)
- **Audio Sources**:
    - **Shairport-Sync**: AirPlay Classic/1 and AirPlay 2 support
    - **Librespot**: Spotify Connect client
    - **FIFO Pipes**: Direct audio input support
- **Process Management**: Supervisord for managing multiple processes
- **Service Discovery**: Avahi daemon for mDNS/DNS-SD
- **IPC**: D-Bus for inter-process communication
- **Security**: Built-in HTTPS support with automatic certificate generation
- **Architecture**: Rootless container for enhanced security

### Frontend
- **Framework/Library**: React 19.1.1
- **Language**: TypeScript 5.8.2
- **Build Tool**: Vite 6.2.0
- **State Management**: React hooks (useState, useEffect, useCallback)
- **CSS Framework**: Custom CSS with CSS variables for theming
- **Real-time Communication**: WebSocket (JSON-RPC 2.0 protocol)

### Key Dependencies

Backend (via Docker):
- `snapcast-server` - Multi-room server
- `snapcast-client` - Audio output client (integrated in same container)
- `shairport-sync` - AirPlay audio receiver
- `librespot` - Spotify Connect client
- `avahi` - Service discovery for network audio
- `dbus` - Inter-process communication
- `nqptp` - Network Time Protocol for AirPlay 2 (in airplay2 builds)
- `supervisord` - Process management

Frontend:
- `react@19.1.1` - UI framework
- `react-dom@19.1.1` - React DOM renderer
- `typescript@5.8.2` - Type safety
- `vite@6.2.0` - Build tool and dev server

## Audio Pipeline Architecture

The complete audio flow from source to speakers:

```
iOS/Mac Device (AirPlay) or Spotify App
              ↓
    shairport-sync / librespot
              ↓
       /tmp/snapfifo (FIFO pipe)
              ↓
         snapserver
    (distributes to clients)
              ↓
         snapclient
    (integrated in container)
              ↓
    ALSA hw:Headphones device
    (Raspberry Pi 3.5mm jack)
              ↓
      Speakers/Headphones
```

All services run in a single Docker container managed by supervisord for simplified deployment and management.

## Project Structure

```
├── backend/
├── frontend/
│   ├── components/                # React components
│   ├── services/                  # API services
│   ├── hooks/                     # Custom React hooks
│   ├── App.tsx                    # Main application
│   ├── types.ts                   # TypeScript definitions
│   └── vite.config.ts            # Vite configuration
├── docker/
├── scripts/
└── CLAUDE.md                     # This file
```

## Raspberry Pi Deployment

### One-Time Setup Requirements

When deploying to a new Raspberry Pi, these steps must be performed once:

#### 1. Docker Audio Permissions
Create a udev rule so Docker containers can access `/dev/snd`:

```bash
# Create the rule file
sudo nano /etc/udev/rules.d/99-audio-permissions.rules

# Add this single line:
SUBSYSTEM=="sound", MODE="0666"

# Save and apply
sudo udevadm control --reload-rules
sudo udevadm trigger
```

**Why this is needed**: The container's audio group (GID 18) doesn't match the host's audio device group (GID 29). The Dockerfile fixes the container's audio group to GID 29, but the host device permissions still need to allow access.

#### 2. Disable Host Avahi Services
Disable the host's Avahi daemon to avoid conflicts with the container's Avahi:

```bash
# Disable Avahi service and socket
sudo systemctl disable avahi-daemon.service
sudo systemctl disable avahi-daemon.socket
```

**Why this is needed**: The container runs its own Avahi daemon for AirPlay service discovery. Having both the host and container Avahi daemons running causes conflicts. The container's Avahi uses the host's D-Bus socket via a volume mount.

**Note on D-Bus**: The host's D-Bus service must remain enabled and running. It is socket-activated by default on Raspberry Pi OS and will start automatically. The container's Avahi daemon connects to the host's D-Bus socket at `/var/run/dbus/system_bus_socket` via the docker-compose volume mount.

#### 3. Reboot
```bash
sudo reboot
```

#### 4. Deploy Containers
```bash
cd ~/Plum-Snapcast/docker
docker-compose pull
docker-compose up -d
```

### Verification Steps

After deployment:

```bash
# Check all services are running
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status

# Expected output:
# dbus               RUNNING
# avahi              RUNNING
# shairport-sync     RUNNING
# snapserver         RUNNING
# snapclient         RUNNING   ← Audio output service
# airplay-metadata   RUNNING

# Verify audio devices are accessible
docker exec plum-snapcast-server aplay -l
# Should show: card 0: Headphones [bcm2835 Headphones]

# Test audio output
docker exec plum-snapcast-server speaker-test -c 2 -t wav -l 1 -D hw:Headphones

# Check snapclient is connected to server
docker logs plum-snapcast-server | grep "Hello from"
# Should show successful client connection
```

## Development Environment

### Setup - Backend (Docker)
1. **Docker Compose** (Recommended):
   ```bash
   cd backend
   docker-compose up -d
   ```

2. **Docker CLI**:
   ```bash
   docker run \
     --privileged \
     --network host \
     --device /dev/snd:/dev/snd \
     -v snapcast-data:/app/data \
     -v snapcast-config:/app/config \
     -e AIRPLAY_DEVICE_NAME="Plum Audio" \
     -e SNAPCLIENT_ENABLED=1 \
     your-dockerhub-username/plum-snapcast-server:latest
   ```

### Setup - Frontend
```bash
cd frontend
npm install
npm run dev
```

### Required Environment Variables (Backend)

#### AirPlay Configuration
- `AIRPLAY_CONFIG_ENABLED`: Enable AirPlay source (default: `1`)
- `AIRPLAY_SOURCE_NAME`: Display name in Snapcast (default: `Airplay`)
- `AIRPLAY_DEVICE_NAME`: Speaker name for AirPlay clients (default: `Plum Audio`)
- `AIRPLAY_EXTRA_ARGS`: Additional source arguments (format: `&key=value`)

#### Snapclient Audio Output
- `SNAPCLIENT_ENABLED`: Enable snapclient service (default: `1`)
- `SNAPCLIENT_HOST`: Snapserver address (default: `localhost`)
- `SNAPCLIENT_SOUNDCARD`: ALSA device name (default: `hw:Headphones`)
- `SNAPCLIENT_LATENCY`: PCM device latency in ms (default: `0`)

#### Spotify Configuration
- `SPOTIFY_CONFIG_ENABLED`: Enable Spotify Connect (default: `0`)
- `SPOTIFY_SOURCE_NAME`: Display name in Snapcast (default: `Spotify`)
- `SPOTIFY_ACCESS_TOKEN`: Spotify API access token (optional)
- `SPOTIFY_DEVICE_NAME`: Speaker name in Spotify app (default: `Snapcast`)
- `SPOTIFY_BITRATE`: Stream quality (default: `320`)
- `SPOTIFY_EXTRA_ARGS`: Additional source arguments

#### FIFO Pipe Configuration
- `PIPE_CONFIG_ENABLED`: Enable FIFO pipe source (default: `0`)
- `PIPE_SOURCE_NAME`: Display name in Snapcast (default: `Pipe`)
- `PIPE_PATH`: Path to FIFO pipe (default: `/tmp/snapfifo`)
- `PIPE_MODE`: `create` or `read` (default: `create`)

#### HTTPS Configuration
- `HTTPS_ENABLED`: Enable HTTPS (default: `1`)
- `SKIP_CERT_GENERATION`: Skip auto cert generation (default: `0`)
- `CERT_SERVER_CN`: Certificate common name (default: `snapserver`)
- `CERT_SERVER_DNS`: Space-separated DNS names (default: `snapserver snapserver.local`)

#### General
- `TZ`: Timezone (default: `Etc/UTC`)

### Frontend Environment Variables
- `GEMINI_API_KEY`: (if using AI features) API key for Gemini

## Core Models/Components

### Backend Components
- **Snapcast Server**: Core audio synchronization server managing streams, groups, and clients
- **Snapcast Client**: Audio output client (integrated in same container, outputs to hardware)
- **Shairport-Sync**: Receives AirPlay audio streams and outputs to Snapcast
- **Librespot**: Spotify Connect endpoint that streams to Snapcast
- **Supervisord**: Manages all services within the container
- **Avahi Daemon**: Broadcasts service availability on the network

### Frontend Components
- **App.tsx**: Main application component managing global state and layout
- **NowPlaying**: Displays current track metadata and album art
- **PlayerControls**: Play/pause, skip, volume controls
- **StreamSelector**: Switch between available audio sources
- **ClientManager**: Manage individual client devices
- **SyncedDevices**: Display devices synchronized to current stream
- **Settings**: Application settings and theme configuration

### Key Services
- **snapcastService.ts**: WebSocket communication with Snapcast server using JSON-RPC 2.0
    - Connection management
    - Volume control (client and group level)
    - Stream control (play, pause, next, previous)
    - Server status queries
    - Group and stream management
- **snapcastDataService.ts**: Data transformation and fallback handling
    - Metadata extraction from streams
    - Default data generation
    - Type conversions

### Core Data Types (types.ts)
- **Stream**: Audio source with metadata, playback state, and capabilities
- **Client**: Individual device/player with volume and connection status
- **Track**: Metadata for currently playing audio (title, artist, album, artwork)
- **Settings**: Application configuration (integrations, theme)

## Architecture Patterns

### WebSocket Communication (JSON-RPC 2.0)
The frontend communicates with Snapcast server using JSON-RPC 2.0 over WebSocket:
- **Request format**: `{ id: number, jsonrpc: "2.0", method: string, params?: object }`
- **Response format**: `{ id: number, jsonrpc: "2.0", result?: object, error?: object }`
- Connection is managed by `snapcastService` with automatic reconnection
- Callbacks handle asynchronous responses

### State Management
- React hooks for local component state
- Props drilling for shared state between components
- No external state management library (Redux, etc.)
- State updates trigger re-renders for real-time UI updates

### Audio Synchronization
- Custom `useAudioSync` hook manages progress tracking
- Updates every 1000ms when stream is playing
- Periodic sync with server (every 5 seconds) to verify playback state
- Client-side progress prediction for smooth UI updates

### Metadata Processing
- Backend: Custom script (`process-airplay-metadata.sh`) processes AirPlay metadata
- Frontend: `snapcastDataService` extracts metadata from various stream formats
- Fallback to default values when metadata unavailable
- Album art handling via data URLs or external URLs

## Network Architecture

### Port Mappings
**Snapcast Server:**
- `1704-1705`: Snapcast client connections
- `1780`: Snapcast HTTP/WebSocket control (legacy)
- `1788`: Snapcast HTTPS/WebSocket control

**AirPlay:**
- `3689`: AirPlay control
- `5000`: AirPlay Classic/1 streaming
- `6000-6009/udp`: AirPlay audio streaming
- `5353`: Avahi/mDNS for service discovery
- `7000`: AirPlay 2 streaming (airplay2 builds only)
- `319-320/udp`: NQPTP for AirPlay 2 (airplay2 builds only)

**Frontend:**
- `3000`: Web interface (via nginx in frontend container)

### Network Requirements
- **Layer 2 network**: AirPlay and Spotify Connect require broadcast support (mDNS/Avahi)
- **Routed networks**: May require mDNS repeater for cross-subnet discovery
- **Host networking**: Backend uses `network_mode: host` for optimal service discovery

## Important Notes for Development

1. **Attribution Required**: This project builds on firefrei/docker-snapcast. Always maintain proper attribution in CREDITS.md and respect upstream licensing.

2. **No localStorage in Artifacts**: The Claude.ai artifact environment does not support browser storage APIs. Always use React state (useState, useReducer) for data persistence.

3. **WebSocket Connection Management**:
    - Always check `isConnected` before sending requests
    - Handle connection failures gracefully with fallback UI
    - Implement reconnection logic for network interruptions

4. **Stream Capabilities**:
    - Not all streams support all controls (play, pause, seek, next, previous)
    - Always check `stream.properties` for available capabilities before enabling controls
    - Use `Stream.Control` method for playback commands

5. **Volume Control Patterns**:
    - Individual client volume via `Client.SetVolume`
    - No direct group volume API - adjust all clients in group individually
    - Track pre-mute volumes for proper mute/unmute behavior

6. **Metadata Handling**:
    - Metadata format varies by source (AirPlay vs Spotify vs Pipe)
    - Always provide fallback values (Unknown Track, Unknown Artist, etc.)
    - Album art may be base64 data URL or external URL

7. **TypeScript Best Practices**:
    - Use explicit types from `types.ts`
    - Avoid `any` type except in proven necessary cases
    - Leverage type checking for WebSocket message formats

8. **Rootless Container Security**:
    - Backend runs without root privileges (user: snapcast)
    - Audio group GID fixed to 29 to match Raspberry Pi host
    - Privileged mode required for /dev/snd device access

9. **Audio Device Access**:
    - Snapclient runs inside the same container as snapserver
    - Requires privileged mode AND proper /dev/snd permissions
    - Host must have udev rule: `SUBSYSTEM=="sound", MODE="0666"`
    - Container audio group must match host device group (GID 29)

## API Documentation

### Snapcast JSON-RPC API
- **Protocol**: WebSocket with JSON-RPC 2.0
- **Endpoint**: `ws://[host]:1780/jsonrpc` (HTTP) or `wss://[host]:1788/jsonrpc` (HTTPS)
- **Documentation**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/

### Key API Methods
- `Server.GetStatus` - Get complete server state (streams, groups, clients)
- `Client.SetVolume` - Set client volume and mute state
- `Group.SetStream` - Assign stream to group
- `Stream.Control` - Control stream playback (play, pause, next, etc.)
- `Server.GetRPCVersion` - Get API version

## Configuration

### Backend Configuration Files
- `/app/config/snapserver.conf` - Snapcast server configuration (auto-generated or custom)
- `/app/config/shairport-sync.conf` - AirPlay receiver configuration
- `/app/supervisord/supervisord.conf` - Main process management configuration
- `/app/supervisord/snapcast.ini` - Snapserver and related services
- `/app/supervisord/snapclient.ini` - Snapclient audio output configuration

### Frontend Configuration
- `vite.config.ts` - Build configuration and path aliases
- CSS variables in `:root` - Theme colors and spacing
- `[data-theme]` and `[data-accent]` attributes - Dynamic theming

## Deployment

### Building Images
```bash
# Build for multiple architectures (amd64 + arm64)
./scripts/build-and-push.sh

# This builds and pushes:
# - Backend: your-username/plum-snapcast-server:latest
# - Frontend: your-username/plum-snapcast-frontend:latest
```

### Deploying on Raspberry Pi
```bash
# One-time setup (see "Raspberry Pi Deployment" section above)
sudo scripts/setup-audio.sh
# Create udev rule for audio permissions
# Reboot

# Deploy/update containers
cd docker
docker-compose pull
docker-compose up -d
```

### Volume Mounts (Backend)
- `/app/config/` - Configuration files (persistent)
- `/app/data/` - Runtime data (server.json, etc.)
- `/app/certs/` - TLS certificates (auto-generated if not provided)
- `/tmp/` - FIFO pipes and metadata (ephemeral)

### Environment-Specific Notes
- **Development**: Use `dev` tags for latest features (may be unstable)
- **Production**: Use `latest` tags for stable releases
- **Network**: Container requires `network_mode: host` for service discovery
- **Privileges**: Container requires `privileged: true` for audio device access

## Troubleshooting

### No Audio Output
```bash
# Check snapclient status
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status snapclient

# Should show: RUNNING

# If FATAL or STOPPED, check logs:
docker logs plum-snapcast-server | grep snapclient

# Common issues:
# - "PCM device not found" → Check audio device permissions
# - "Device or resource busy" → Another process using /dev/snd
```

### Audio Device Not Accessible
```bash
# Verify devices visible in container
docker exec plum-snapcast-server aplay -l

# Should show Headphones card

# If empty, check host permissions:
ls -la /dev/snd/
# All files should be rw-rw-rw- (666)

# Fix permissions:
sudo chmod 666 /dev/snd/*
# And/or reapply udev rules:
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### AirPlay Device Not Visible
```bash
# Check avahi is running
docker exec plum-snapcast-server ps aux | grep avahi

# Scan for AirPlay services
avahi-browse -r _raop._tcp

# Restart if needed
docker-compose restart
```

### Audio Group Mismatch
```bash
# Check container's audio group
docker exec plum-snapcast-server id
# Should show: groups=29(audio),102(snapcast)

# Check device group ownership
ls -la /dev/snd/controlC0
# Should show: crw-rw-rw- 1 root 29 ...

# If GID mismatch, rebuild image with updated Dockerfile
```

## Code Quality

### Tools
- **TypeScript**: Built-in type checking
- **Formatting**: Prettier
- **Vite**: Fast builds and hot module replacement
- **Supervisor**: Process monitoring and auto-restart

### Commands
```bash
# Frontend
npm run dev          # Start dev server with HMR
npm run build        # Production build
npm run preview      # Preview production build

# Backend (in container)
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf restart snapclient
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapclient
```

## Important Development Considerations

1. **Snapcast JSON-RPC Communication**: All backend communication uses JSON-RPC 2.0 over WebSocket. Request IDs must be tracked for response correlation.

2. **Stream Status Polling**: The frontend polls stream status every 5 seconds to stay synchronized. Consider this when debugging playback state issues.

3. **Client-to-Group Mapping**: Clients belong to groups, and groups are assigned streams. Always query the full server status to understand these relationships.

4. **AirPlay Metadata Extraction**: AirPlay metadata flows through `shairport-sync` → custom processing script → Snapcast stream properties. Format varies by source app.

5. **AirPlay Album Artwork Workaround**: Snapcast's plugin system filters out custom metadata fields including `artUrl`. To work around this limitation:
   - The control script saves cover art to `/usr/share/snapserver/snapweb/coverart/{hash}.jpg`
   - It also writes `/usr/share/snapserver/snapweb/airplay-artwork.json` with the artwork URL
   - The frontend fetches this JSON file via nginx proxy at `/snapcast-api/airplay-artwork.json` to avoid CORS
   - The nginx proxy in the frontend container proxies `/snapcast-api/*` to `http://snapcast-host:1780/`
   - This requires the `extra_hosts: snapcast-host:host-gateway` setting in docker-compose.yml

6. **Multi-room Synchronization Accuracy**: Snapcast achieves sample-accurate synchronization. Don't introduce processing that might add latency or jitter.

7. **Container Network Mode**: For AirPlay/Spotify discovery, container uses `network_mode: host` for proper mDNS broadcast.

8. **Certificate Management**: HTTPS certificates auto-generate as self-signed. For production, mount custom certificates or use a reverse proxy with proper TLS.

9. **Integrated Snapclient**: Unlike typical Snapcast deployments, this project runs snapclient in the same container as snapserver for simplified single-device setup. This works well for Raspberry Pi deployments but limits multi-room expansion.

## Resources

- **Snapcast Documentation**: https://github.com/badaix/snapcast/blob/develop/doc/
- **Snapcast JSON-RPC API**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/
- **Docker Snapcast Repository**: https://github.com/firefrei/docker-snapcast
- **Shairport-Sync**: https://github.com/mikebrady/shairport-sync
- **Alpine Linux Packages**: https://pkgs.alpinelinux.org/

---

## Quick Reference: Common Tasks

### Add a New Audio Source
1. Enable in backend environment variables (e.g., `SPOTIFY_CONFIG_ENABLED=1`)
2. Restart backend container
3. Frontend will auto-detect new stream via `Server.GetStatus`

### Debug WebSocket Communication
```javascript
// In browser console
snapcastService.ws.addEventListener('message', (e) => console.log('WS:', e.data));
```

### View Container Logs
```bash
# All services
docker logs -f plum-snapcast-server

# Specific service
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapclient stdout

# Only snapclient errors
docker logs plum-snapcast-server 2>&1 | grep -i "snapclient\|error"
```

### Test Audio Pipeline
```bash
# 1. Test speaker directly
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1

# 2. Check snapclient is connected
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status

# 3. Play via AirPlay from iPhone/Mac
# Look for "Plum Audio" in AirPlay devices

# 4. Check web interface
# Open http://raspberrypi.local:3000
# Should show metadata and playback status
```

### Reset Configuration
1. Stop container: `docker-compose down`
2. Remove volumes: `docker volume rm docker_snapcast-config`
3. Restart: `docker-compose up -d`
4. Container will regenerate defaults

## Attribution and Credits

### Original Work
This project incorporates code from:
- **docker-snapcast**: https://github.com/firefrei/docker-snapcast by Matthias Frei
- **Snapcast**: https://github.com/badaix/snapcast by Johannes Pohl
- **Shairport-Sync**: https://github.com/mikebrady/shairport-sync by Mike Brady
- **Librespot**: https://github.com/librespot-org/librespot

### Our Modifications
- Integrated snapclient for hardware audio output
- Custom AirPlay metadata processing script
- React/TypeScript frontend
- Enhanced Docker configuration
- WebSocket-based control interface
- Modern UI with theming support
- Single-container architecture for simplified deployment

See CREDITS.md for complete attribution information.