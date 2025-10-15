# CLAUDE.md - Plum-Snapcast Development Guide

This file contains essential information for Claude to work effectively with the Plum-Snapcast codebase.

## Project Overview

**Plum-Snapcast** is a comprehensive multi-room audio streaming solution that combines a Snapcast server backend with a modern React/TypeScript frontend. The application enables synchronized audio playback across multiple devices/rooms with support for AirPlay, Spotify Connect, and direct streaming sources.

### Key Features
- **Multi-room audio synchronization**: Precise synchronization of audio playback across multiple client devices
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
- `snapcast` - Multi-room client-server audio player
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

## Project Structure

```
├── backend/
│   ├── config/              # Configuration templates
│   ├── scripts/             # Helper scripts (metadata processing, setup)
│   ├── .github/workflows/   # CI/CD workflows
│   ├── Dockerfile           # Container build definition
│   ├── setup.sh            # Container initialization script
│   └── supervisord.conf    # Process management configuration
├── frontend/
│   ├── components/         # React components
│   ├── services/           # API services (snapcastService, snapcastDataService)
│   ├── hooks/             # Custom React hooks (useAudioSync)
│   ├── App.tsx            # Main application component
│   ├── types.ts           # TypeScript type definitions
│   ├── vite.config.ts     # Vite configuration
│   └── package.json       # Frontend dependencies
├── .idea/                 # IDE configuration
├── README.md             # Project documentation
└── CREDITS.md           # Attribution information
```

## Core Models/Components

### Backend Components
- **Snapcast Server**: Core audio synchronization server managing streams, groups, and clients
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
     -p 1704-1705:1704-1705 \
     -p 1780:1780 \
     -p 1788:1788 \
     -p 3689:3689 \
     -p 5000:5000 \
     -p 6000-6009:6000-6009/udp \
     -p 5353:5353 \
     ghcr.io/firefrei/snapcast/server:latest
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
- `AIRPLAY_DEVICE_NAME`: Speaker name for AirPlay clients (default: `Snapcast`)
- `AIRPLAY_EXTRA_ARGS`: Additional source arguments (format: `&key=value`)

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

### Network Requirements
- **Layer 2 network**: AirPlay and Spotify Connect require broadcast support (mDNS/Avahi)
- **Routed networks**: May require mDNS repeater for cross-subnet discovery
- **Privileged ports**: Ports <1024 require `NET_BIND_SERVICE` capability or system-wide configuration

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
   - Backend runs without root privileges
   - Privileged port binding requires explicit capability grants
   - Never modify container to run as root

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
- `/etc/supervisord.conf` - Process management configuration

### Frontend Configuration
- `vite.config.ts` - Build configuration and path aliases
- CSS variables in `:root` - Theme colors and spacing
- `[data-theme]` and `[data-accent]` attributes - Dynamic theming

## Deployment

### Docker Deployment
**Production:**
```bash
docker pull ghcr.io/firefrei/snapcast/server:latest
docker run -d [ports and volumes] ghcr.io/firefrei/snapcast/server:latest
```

**Development:**
```bash
docker pull ghcr.io/firefrei/snapcast/server:dev
```

**AirPlay 2 Support:**
```bash
docker pull ghcr.io/firefrei/snapcast/server:latest-airplay2
```

### Frontend Deployment
```bash
cd frontend
npm run build
# Serve dist/ directory with static file server
```

### Volume Mounts (Backend)
- `/app/config/` - Configuration files (persistent)
- `/app/data/` - Runtime data (server.json, etc.)
- `/app/certs/` - TLS certificates (auto-generated if not provided)

### Environment-Specific Notes
- **Development**: Use `dev` tags for latest features (may be unstable)
- **Production**: Use `latest` tags for stable releases (built monthly)
- **Network**: Ensure mDNS/Avahi works across your network topology

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
supervisorctl status    # Check service status
supervisorctl restart   # Restart services
```

## Important Development Considerations

1. **Snapcast JSON-RPC Communication**: All backend communication uses JSON-RPC 2.0 over WebSocket. Request IDs must be tracked for response correlation.

2. **Stream Status Polling**: The frontend polls stream status every 5 seconds to stay synchronized. Consider this when debugging playback state issues.

3. **Client-to-Group Mapping**: Clients belong to groups, and groups are assigned streams. Always query the full server status to understand these relationships.

4. **AirPlay Metadata Extraction**: AirPlay metadata flows through `shairport-sync` → custom processing script → Snapcast stream properties. Format varies by source app.

5. **Multi-room Synchronization Accuracy**: Snapcast achieves sample-accurate synchronization. Don't introduce processing that might add latency or jitter.

6. **Container Network Mode**: For AirPlay/Spotify discovery, container typically needs `network_mode: host` or bridge with proper port forwarding.

7. **Certificate Management**: HTTPS certificates auto-generate as self-signed. For production, mount custom certificates or use a reverse proxy with proper TLS.

## Attribution and Credits

### Original Work
This project incorporates code from:
- **docker-snapcast**: https://github.com/firefrei/docker-snapcast by Matthias Frei
- **Snapcast**: https://github.com/badaix/snapcast by Johannes Pohl
- **Shairport-Sync**: https://github.com/mikebrady/shairport-sync by Mike Brady
- **Librespot**: https://github.com/librespot-org/librespot

### Our Modifications
- Custom AirPlay metadata processing script
- React/TypeScript frontend
- Enhanced Docker configuration
- WebSocket-based control interface
- Modern UI with theming support

See CREDITS.md for complete attribution information.

## Resources

- **Snapcast Documentation**: https://github.com/badaix/snapcast/blob/develop/doc/
- **Snapcast JSON-RPC API**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/
- **Docker Snapcast Repository**: https://github.com/firefrei/docker-snapcast
- **Project Repository**: [Your repository URL]
- **Issue Tracking**: [Your issue tracker URL]

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

### Check Stream Capabilities
```javascript
// In browser console
snapcastService.getStreamCapabilities('stream-id').then(console.log);
```

### View Container Logs
```bash
docker logs -f [container-name]
# Or within container:
supervisorctl tail -f snapserver
```

### Reset Configuration
1. Stop container
2. Remove volumes (or specific config files)
3. Restart container (will regenerate defaults)