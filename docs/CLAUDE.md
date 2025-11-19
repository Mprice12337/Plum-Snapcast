# CLAUDE.md - Plum-Snapcast

> **Purpose**: This file serves as your project's memory for Claude Code. It defines rules, workflows, and preferences that Claude will automatically follow when working on the Plum-Snapcast codebase.

## Project Overview

**Plum-Snapcast** is a comprehensive multi-room audio streaming solution that combines a Snapcast server backend with a modern React/TypeScript frontend. The application enables synchronized audio playback across multiple devices/rooms with support for AirPlay, Spotify Connect, and direct streaming sources.

### Key Features
- Multi-room audio synchronization with sample-accurate playback
- Hardware audio output via integrated snapclient (Raspberry Pi 3.5mm jack)
- Modern React-based web interface for controlling streams and managing clients
- Real-time WebSocket communication using JSON-RPC 2.0
- Multiple audio sources: AirPlay (1 and 2), Bluetooth (A2DP), Spotify Connect (Spotifyd), FIFO pipes
- Real-time metadata display with album artwork
- Individual and group volume control with mute functionality

### Project Context
- **Stage**: Production-ready, active development
- **Team Size**: Solo developer with AI assistance
- **Priority Focus**: Reliability, ease of deployment, audio quality
- **Attribution**: Built on firefrei/docker-snapcast foundation

---

## Claude Code Preferences

### Workflow Mode
- **Default Model**: Sonnet for daily work / Opus for complex architectural planning
- **Planning Strategy**: Plan for complex multi-step tasks, direct implementation for simple changes
- **Testing Approach**: Write tests for critical audio pipeline and WebSocket code
- **Auto-Accept**: Disabled - always review before committing

### Communication Style
- **Verbosity**: Concise - explain major changes, skip obvious details
- **Progress Updates**: Yes, keep me informed of multi-step processes
- **Error Handling**: Try to resolve, then explain if blocked

### Task Management
- **To-Do Lists**: Auto-generate for complex tasks
- **Subagents**: Use for exploration and parallel work
- **Research**: Proactive web search when encountering unfamiliar technologies

---

## Technology Stack

### Backend
- **Framework**: Docker container with Alpine Linux base
- **Audio Server**: Snapcast server (from Alpine edge repositories)
- **Audio Client**: Snapcast client (integrated in same container)
- **Audio Sources**:
  - **Shairport-Sync**: AirPlay Classic/1 and AirPlay 2 support
  - **BlueZ + bluez-alsa**: Bluetooth A2DP audio reception
  - **Spotifyd**: Spotify Connect client with D-Bus MPRIS support
  - **FIFO Pipes**: Direct audio input support
- **Process Management**: Supervisord for managing multiple processes
- **Service Discovery**: Avahi daemon for mDNS/DNS-SD
- **IPC**: D-Bus for inter-process communication (uses host's D-Bus socket)
- **Security**: HTTPS support with automatic certificate generation
- **Architecture**: Rootless container (user: snapcast, UID 1000, GID 29 for audio)

### Frontend
- **Framework/Library**: React 19.1.1
- **Language**: TypeScript 5.8.2
- **Build Tool**: Vite 6.2.0
- **State Management**: React hooks (useState, useEffect, useCallback)
- **CSS Framework**: Custom CSS with CSS variables for theming
- **Real-time Communication**: WebSocket (JSON-RPC 2.0 protocol)

### Infrastructure
- **Containerization**: Docker multi-architecture builds (amd64, arm64)
- **Container Registry**: Docker Hub
- **Target Platform**: Raspberry Pi (3 or newer) with Raspberry Pi OS Lite (64-bit)
- **Networking**: Host networking mode for mDNS/Avahi support

### Key Dependencies

Backend (via Docker):
- `snapcast-server` - Multi-room audio synchronization server
- `snapcast-client` - Audio output client (integrated, outputs to hw:Headphones)
- `shairport-sync` - AirPlay audio receiver with metadata support
- `bluez` - Linux Bluetooth stack for device pairing and control
- `bluez-alsa` - Bluetooth audio (A2DP) via ALSA integration
- `py3-dbus` - Python D-Bus bindings for Bluetooth metadata extraction
- `spotifyd` - Spotify Connect client (built from source with MPRIS support)
- `avahi` - Service discovery for network audio (mDNS/DNS-SD)
- `dbus` - Inter-process communication (container uses host's D-Bus socket)
- `nqptp` - Network Time Protocol for AirPlay 2 (airplay2 builds only)
- `supervisord` - Process management and auto-restart

Frontend:
- `react@19.1.1` - UI framework with latest features
- `react-dom@19.1.1` - React DOM renderer
- `typescript@5.8.2` - Type safety and tooling
- `vite@6.2.0` - Fast build tool and dev server with HMR

---

## Project Structure

```
├── _resources/                   # Development references (NOT in git)
│   ├── architecture.md           # Architecture template
│   ├── CLAUDE.md                 # CLAUDE.md template
│   ├── DEV-SETUP.md             # Dev setup template
│   ├── QUICK-REFERENCE.md       # Quick reference template
│   └── PROJECT-STRUCTURE-EXAMPLE.md  # Structure template
├── docs/                         # Project documentation
│   ├── ARCHITECTURE.md           # System architecture and design decisions
│   ├── CLAUDE.md                 # This file (symlinked to root)
│   ├── DEV-SETUP.md             # Development environment setup
│   ├── QUICK-REFERENCE.md       # Quick reference guide
│   └── original/                 # Original documentation (archived)
│       ├── CLAUDE.md
│       ├── CREDITS.md
│       ├── PROJECT_OVERVIEW.md
│       └── SETUP_INSTRUCTIONS.md
├── backend/
│   ├── Dockerfile               # Multi-stage, multi-arch backend build
│   ├── config/                  # Configuration files
│   │   ├── shairport-sync.conf  # AirPlay receiver config
│   │   └── snapserver.conf.template  # Snapcast server config template
│   ├── scripts/                 # Backend scripts
│   │   ├── entrypoint.sh        # Container startup script
│   │   ├── generate-config.sh   # Config file generator
│   │   └── process-airplay-metadata.sh  # AirPlay metadata processor
│   └── supervisord/             # Process management configs
│       ├── supervisord.conf     # Main supervisord configuration
│       ├── snapcast.ini         # Snapserver process config
│       ├── snapclient.ini       # Snapclient process config
│       ├── shairport-sync.ini   # AirPlay process config
│       └── avahi.ini            # Avahi daemon config
├── frontend/
│   ├── src/
│   │   ├── components/          # React components
│   │   │   ├── NowPlaying.tsx
│   │   │   ├── PlayerControls.tsx
│   │   │   ├── StreamSelector.tsx
│   │   │   ├── ClientManager.tsx
│   │   │   └── Settings.tsx
│   │   ├── services/            # API services
│   │   │   ├── snapcastService.ts      # WebSocket JSON-RPC client
│   │   │   └── snapcastDataService.ts  # Data transformation
│   │   ├── hooks/               # Custom React hooks
│   │   │   └── useAudioSync.ts  # Audio progress tracking
│   │   ├── App.tsx              # Main application component
│   │   ├── types.ts             # TypeScript type definitions
│   │   └── main.tsx             # Application entry point
│   ├── public/                  # Static assets
│   ├── vite.config.ts          # Vite build configuration
│   ├── tsconfig.json           # TypeScript configuration
│   ├── package.json            # Frontend dependencies
│   └── Dockerfile              # Frontend nginx container
├── docker/
│   ├── docker-compose.yml      # Multi-container orchestration
│   ├── .env.example            # Environment variables template
│   └── build-and-push.sh       # Multi-arch build script
├── scripts/
│   └── setup-audio.sh          # One-time Raspberry Pi audio setup
├── README.md                   # Main project documentation
├── CLAUDE.md                   # Symlink to docs/CLAUDE.md
└── .gitignore                  # Includes _resources/
```

### Special Directories

#### `_resources/` (Not in Git)
**Purpose**: Development reference materials for both human developers and AI assistants

**Contains**:
- Documentation templates (architecture.md, CLAUDE.md, etc.)
- Example configuration snippets
- Research documents and technical notes
- Design diagrams and mockups
- Meeting notes and planning documents

**Important**:
- This folder is **NEVER committed to git**
- Add `_resources/` to `.gitignore`
- Perfect for temporary research, examples, or AI prompts

#### `docs/` (Documentation Repository)
**Purpose**: All project documentation except README.md

**Required Files**:
- **`ARCHITECTURE.md`**: System architecture, design patterns, technical decisions
- **`CLAUDE.md`**: Claude Code configuration (symlinked to root for auto-detection)
- **`DEV-SETUP.md`**: Development environment setup instructions
- **`QUICK-REFERENCE.md`**: Common commands and quick reference
- **`original/`**: Archive of previous documentation versions

### Key Directories
- **backend/**: Docker container with Alpine Linux, Snapcast, Shairport-Sync, Spotifyd
- **frontend/**: React/TypeScript web application with Vite build system
- **docker/**: Docker Compose orchestration and build scripts
- **scripts/**: Helper scripts for deployment and setup

---

## Core Architecture

### Audio Pipeline Architecture

The complete audio flow from source to speakers:

```
iOS/Mac Device (AirPlay), Bluetooth Phone, or Spotify App
              ↓
    shairport-sync / bluealsa / spotifyd
    (receives audio stream)
              ↓
       /tmp/snapfifo or /tmp/bluetooth-fifo (FIFO pipe)
    (audio transport layer)
              ↓
         snapserver
    (distributes to clients with sync)
              ↓
         snapclient
    (integrated in same container)
              ↓
    ALSA hw:Headphones device
    (Raspberry Pi 3.5mm jack)
              ↓
      Speakers/Headphones
```

All services run in a single Docker container managed by supervisord for simplified deployment.

### Primary Models/Components

**Backend Components:**
- **Snapcast Server**: Core audio synchronization server managing streams, groups, and clients
- **Snapcast Client**: Audio output client (integrated in same container, outputs to hardware)
- **Shairport-Sync**: Receives AirPlay audio streams and outputs to Snapcast via FIFO
- **BlueZ + bluez-alsa**: Bluetooth stack for A2DP audio reception and ALSA integration
- **Spotifyd**: Spotify Connect endpoint with D-Bus MPRIS for metadata and playback control
- **Supervisord**: Manages all services within the container with auto-restart
- **Avahi Daemon**: Broadcasts AirPlay/Spotify services on the network via mDNS
- **D-Bus**: Inter-process communication (system bus for MPRIS integration)

**Frontend Components:**
- **App.tsx**: Main application component managing global state and layout
- **NowPlaying**: Displays current track metadata and album art
- **PlayerControls**: Play/pause, skip, volume controls
- **StreamSelector**: Switch between available audio sources
- **ClientManager**: Manage individual client devices
- **Settings**: Application settings and theme configuration

**Key Services:**
- **snapcastService.ts**: WebSocket communication with Snapcast server
  - Connection management with auto-reconnect
  - Volume control (client and group level)
  - Stream control (play, pause, next, previous)
  - Server status queries (Server.GetStatus)
  - Group and stream management
- **snapcastDataService.ts**: Data transformation and fallback handling
  - Metadata extraction from streams
  - Default data generation for missing metadata
  - Type conversions and normalization

### Design Patterns Used
- **Container Architecture**: Single container with multiple supervised processes
- **JSON-RPC over WebSocket**: Standard protocol for all Snapcast communication
- **FIFO Pipes**: Audio transport from sources (shairport-sync, spotifyd) to snapserver
- **Host D-Bus + Container Avahi**: Critical pattern - host provides D-Bus socket, container runs Avahi
- **React Component Composition**: Modular UI with props drilling for state
- **Custom Hooks**: useAudioSync for progress tracking with client-side prediction

### Data Flow
User action → React component → snapcastService (WebSocket JSON-RPC) → Snapcast server → Audio output via snapclient → Speakers

**Metadata Flow:**
AirPlay/Bluetooth/Spotify → Shairport-Sync/BlueZ D-Bus/Spotifyd MPRIS → Custom control script → Snapcast stream properties → WebSocket → Frontend → UI display

---

## Development Workflow

### Git Strategy
- **Main Branch**: `main` (protected, production-ready)
- **Development Branch**: Feature branches from `main`
- **Branch Naming**: `feature/*`, `bugfix/*`, `docs/*`, `refactor/*`
- **Commit Convention**: Conventional Commits format

#### Git Best Practices
- **Always use `git pull --rebase`** to maintain linear history
- Avoid merge commits when syncing with remote
- Keep commits atomic and well-described
- Sign commits if GPG configured
- Never force push to main/master

#### Commit Message Format
```
<type>: <short description>

<optional detailed description>

<optional footer with breaking changes or issue references>
```

**Types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`

**Examples:**
- `feat: Add album artwork support to AirPlay metadata`
- `fix: Correct audio device permissions in Dockerfile`
- `docs: Update ARCHITECTURE.md with D-Bus/Avahi pattern`
- `refactor: Simplify WebSocket connection logic`

### Code Review Process
- Solo project - self-review before committing
- Test changes locally before pushing
- Verify Docker builds succeed on both amd64 and arm64
- Test on actual Raspberry Pi hardware when possible

---

## Testing Strategy

### Test Framework
- **Unit Tests**: Not currently implemented
- **Integration Tests**: Manual testing on Raspberry Pi
- **E2E Tests**: Manual testing via web interface and AirPlay
- **Test Coverage Goal**: Focus on critical audio pipeline functionality

### Testing Commands
```bash
# Frontend development testing
cd frontend
npm run dev                      # Start dev server with HMR
npm run build                    # Production build to verify no errors

# Backend testing (in container)
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
docker exec plum-snapcast-server aplay -l  # Verify audio devices
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1

# Full integration test
# 1. Deploy to Raspberry Pi
# 2. Open web interface
# 3. Play audio via AirPlay from iPhone/Mac
# 4. Verify metadata displays correctly
# 5. Test volume control
# 6. Test stream switching
```

### Testing Preferences
- **TDD**: Optional - use for complex WebSocket logic
- **Test Generation**: Collaborative - Claude suggests tests, developer reviews
- **Coverage Requirements**: Critical paths (WebSocket communication, audio pipeline setup)

---

## Code Quality Standards

### Linting & Formatting
- **Linter**: ESLint for TypeScript (frontend)
- **Formatter**: Prettier for TypeScript (frontend)
- **Pre-commit Hooks**: Not currently configured
- **Shell Scripts**: Follow shellcheck recommendations

### Commands
```bash
# Frontend
cd frontend
npm run lint                     # Run ESLint
npm run format                   # Format with Prettier

# Backend shell scripts
shellcheck backend/scripts/*.sh
```

### Style Guidelines
- **Indentation**: 2 spaces for TypeScript/JavaScript, 4 spaces for shell scripts
- **Line Length**: 120 characters max
- **Naming Conventions**:
  - Files & Directories: `PascalCase` for components (e.g., `NowPlaying.tsx`), `camelCase` for services (e.g., `snapcastService.ts`)
  - Variables: `camelCase` for TypeScript (e.g., `currentStream`, `isPlaying`)
  - Functions: `camelCase` (e.g., `getServerStatus`, `setClientVolume`)
  - React Components: `PascalCase` (e.g., `NowPlaying`, `PlayerControls`)
  - Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_VOLUME`, `WEBSOCKET_URL`)
  - Environment Variables: `UPPER_SNAKE_CASE` (e.g., `AIRPLAY_DEVICE_NAME`, `SNAPCLIENT_SOUNDCARD`)
- **File Naming**:
  - React components: `PascalCase.tsx` (e.g., `NowPlaying.tsx`)
  - Services: `camelCase.ts` (e.g., `snapcastService.ts`)
  - Types: `types.ts` or `ComponentName.types.ts`
  - Configs: `lowercase-with-dashes` (e.g., `vite.config.ts`, `docker-compose.yml`)

---

## Environment Setup

### Required Environment Variables

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

#### Bluetooth Configuration
- `BLUETOOTH_ENABLED`: Enable Bluetooth A2DP source (default: `0`)
- `BLUETOOTH_SOURCE_NAME`: Display name in Snapcast (default: `Bluetooth`)
- `BLUETOOTH_DEVICE_NAME`: Speaker name for Bluetooth pairing (default: `Plum Audio`)
- `BLUETOOTH_ADAPTER`: Bluetooth adapter to use (default: `hci0`)
- `BLUETOOTH_DEVICE_PATH`: Custom Bluetooth device path (optional, e.g., `/dev/hci0` for USB adapter)
- `BLUETOOTH_AUTO_PAIR`: Auto-accept pairing requests (default: `1`)
- `BLUETOOTH_DISCOVERABLE`: Make device discoverable for pairing (default: `1`)

**Bluetooth Feature Notes:**
- **Pairing**: Auto-accept mode only. Modern devices (iOS 8+, Android 6+) use SSP (Secure Simple Pairing) and do not support legacy PIN codes.
- **Metadata**: Title, artist, and album are provided via AVRCP (Audio/Video Remote Control Profile).
- **Album Art**: Currently not available. AVRCP 1.6+ supports album art via BIP (Bluetooth Image Profile), but requires BlueZ 5.81+ with experimental features enabled. Alpine Linux currently packages BlueZ 5.70. See "Bluetooth Limitations" in Important Notes for details.
- **Media Controls**: Play, pause, skip (next/previous) supported via AVRCP MediaPlayer1 D-Bus interface.

#### Spotify Configuration
- `SPOTIFY_CONFIG_ENABLED`: Enable Spotify Connect (default: `0`)
- `SPOTIFY_SOURCE_NAME`: Display name in Snapcast (default: `Spotify`)
- `SPOTIFY_DEVICE_NAME`: Speaker name in Spotify app (default: `Plum Audio`)
- `SPOTIFY_BITRATE`: Stream quality - 96, 160, or 320 (default: `320`)

**Spotify Implementation Notes:**
- **Spotifyd vs Librespot**: Uses spotifyd (built on librespot) for working D-Bus MPRIS support
- **Avahi Integration**: Patched to use `with-avahi` feature to avoid port 5353 conflicts with container's Avahi daemon
- **D-Bus Permissions**: Permissive policy allows snapcast user to register instance-based service names (e.g., `org.mpris.MediaPlayer2.spotifyd.instance35`)
- **Lazy Player Detection**: Control script auto-detects spotifyd when it registers on D-Bus (handles startup timing)
- **Metadata & Controls**: Full playback control (play/pause/next/previous) and metadata (title, artist, album, artwork) via MPRIS
- **Album Artwork**: Downloaded from Spotify CDN and cached to `/usr/share/snapserver/snapweb/coverart/`

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
- `FRONTEND_PORT`: Web interface port (default: `3000`)

### Frontend Environment Variables
- `VITE_SNAPCAST_HOST`: Snapcast server hostname (for dev mode, default: `localhost`)
- `VITE_SNAPCAST_PORT`: Snapcast WebSocket port (default: `1788` for HTTPS)

---

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
- `5353/udp`: Avahi/mDNS for service discovery
- `7000`: AirPlay 2 streaming (airplay2 builds only)
- `319-320/udp`: NQPTP for AirPlay 2 (airplay2 builds only)

**Frontend:**
- `3000`: Web interface (default, configurable via `FRONTEND_PORT`)

### Network Requirements
- **Layer 2 network**: AirPlay and Spotify Connect require broadcast support (mDNS/Avahi)
- **Routed networks**: May require mDNS repeater for cross-subnet discovery
- **Host networking**: Backend uses `network_mode: host` for optimal service discovery
- **No VLANs**: mDNS broadcasts don't cross VLAN boundaries without repeater

---

## Docker Configuration

### Images Used
- **Base Image**: `alpine:latest` (minimal Linux distribution)
- **Multi-stage Builds**: Yes - separate build and runtime stages
- **Target Architectures**: linux/amd64, linux/arm64

### Container Architecture Pattern

**Critical Architecture: Self-Contained Container**

This project uses a fully self-contained container architecture:

1. **Container**: Runs its own D-Bus daemon AND Avahi daemon
   - Container D-Bus: Managed by supervisord for internal IPC
   - Container Avahi: Handles mDNS service discovery for AirPlay/Spotify/Bluetooth
   - All services self-contained within container

2. **Host System**: Minimal requirements
   - Docker engine
   - Audio device access (/dev/snd)
   - Host Avahi must be disabled (container runs its own)
   - No host D-Bus configuration required
   - No host OS version dependencies

3. **Why This Pattern**:
   - Complete Docker isolation - truly portable container
   - Works across different host OS versions (Debian 12, 13, etc.)
   - Eliminates race conditions from host/container service interactions
   - No host system modification required beyond Docker installation
   - True "build once, run anywhere" Docker design

### Volume Mounts (Backend)
```yaml
volumes:
  - snapcast-config:/app/config       # Configuration files (persistent)
  - snapcast-data:/app/data           # Runtime data (persistent)
  - snapcast-certs:/app/certs         # TLS certificates (persistent)
  # No host mounts required - container is self-contained
```

### Docker Commands
```bash
# Build multi-architecture images
cd docker
bash build-and-push.sh               # Build and push both amd64 and arm64

# Build with --no-cache
bash build-and-push.sh --no-cache

# Local development
docker compose up -d                 # Start containers
docker compose down                  # Stop containers
docker compose logs -f               # View logs
docker compose restart               # Restart all services

# Container inspection
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
docker exec plum-snapcast-server sh  # Shell access
docker logs plum-snapcast-server     # View container logs
```

---

## API Documentation

### Snapcast JSON-RPC API
- **Protocol**: WebSocket with JSON-RPC 2.0
- **Endpoint**: `ws://[host]:1780/jsonrpc` (HTTP) or `wss://[host]:1788/jsonrpc` (HTTPS)
- **Documentation**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/

### Key API Methods
```typescript
// Get complete server state
Server.GetStatus() → { server: { streams: [], groups: [] } }

// Control client volume
Client.SetVolume({ id: string, volume: { percent: number, muted: boolean } })

// Assign stream to group
Group.SetStream({ id: string, stream_id: string })

// Control stream playback
Stream.Control({ id: string, command: "play" | "pause" | "next" | "previous" })

// Get API version
Server.GetRPCVersion() → { major: number, minor: number, patch: number }
```

### Request/Response Format
```javascript
// Request
{
  "id": 123,
  "jsonrpc": "2.0",
  "method": "Server.GetStatus",
  "params": {}
}

// Response
{
  "id": 123,
  "jsonrpc": "2.0",
  "result": {
    "server": {
      "groups": [...],
      "streams": [...],
      "server": {...}
    }
  }
}
```

---

## Coding Conventions

### General Principles
1. **Keep it simple**: Prefer straightforward solutions over clever ones
2. **Audio quality first**: Never compromise on audio pipeline reliability
3. **Document the why**: Explain architectural decisions in comments
4. **Fail gracefully**: Handle errors without crashing services
5. **Test on hardware**: Always verify changes on actual Raspberry Pi

### Project-Specific Rules

1. **D-Bus/Avahi Pattern**: Container runs its own D-Bus and Avahi (self-contained)
   ```yaml
   # CORRECT: No host mounts required
   volumes:
     - snapcast-config:/app/config
     - snapcast-data:/app/data
     - snapcast-certs:/app/certs

   # Container manages D-Bus and Avahi via supervisord
   # Services start automatically with proper priorities
   ```

2. **Audio Group GID**: Always set audio group to GID 29 (Raspberry Pi standard)
   ```dockerfile
   # In Dockerfile
   RUN addgroup -g 29 audio && \
       adduser -D -u 1000 -G audio snapcast
   ```

3. **Snapclient Integration**: Snapclient runs in same container as snapserver
   ```ini
   # supervisord/snapclient.ini
   [program:snapclient]
   command=/usr/bin/snapclient -h localhost --soundcard hw:Headphones
   ```

4. **Attribution Required**: Maintain proper attribution in CREDITS.md
   - Original work by firefrei/docker-snapcast
   - Snapcast by badaix
   - Shairport-Sync by mikebrady

### Error Handling
- **Backend**: Services should auto-restart via supervisord on failure
- **Frontend**: Display error messages in UI, don't crash application
- **WebSocket**: Implement automatic reconnection with exponential backoff
- **Logging**: Use supervisord logs (`/config/supervisord.log`) for all service output

### Performance Considerations
- **Audio Latency**: Minimize processing between source and snapserver (no transcoding)
- **WebSocket Updates**: Poll server status every 5 seconds, not more frequently
- **Frontend Rendering**: Use React.memo for expensive components (album artwork)
- **Docker Image Size**: Use Alpine Linux and multi-stage builds to minimize size

---

## Common Tasks

### Adding a New Audio Source

1. **Create configuration generator** in `backend/scripts/generate-config.sh`:
   ```bash
   if [ "$NEW_SOURCE_ENABLED" = "1" ]; then
     # Add source config to snapserver.conf
   fi
   ```

2. **Add supervisord config** (if needed):
   ```ini
   # supervisord/new-source.ini
   [program:new-source]
   command=/usr/bin/new-source-binary --args
   ```

3. **Update environment variables** in `docker/.env.example`

4. **Test end-to-end**:
   - Build image
   - Deploy to Raspberry Pi
   - Verify source appears in web interface

### Debugging

**Logs Location:**
```bash
# Container logs
docker logs plum-snapcast-server

# Specific service logs via supervisord
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapclient
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f shairport-sync

# All supervisord logs
docker exec plum-snapcast-server cat /var/log/supervisor/supervisord.log
```

**Debug Mode:**
```bash
# Enable verbose logging for shairport-sync
docker exec plum-snapcast-server /usr/local/bin/shairport-sync --configfile=/app/config/shairport-sync.conf -vvv

# Check WebSocket communication in browser
# Browser console:
snapcastService.ws.addEventListener('message', (e) => console.log('WS:', e.data));
```

**Common Issues:**
- **No audio output**: Check audio device permissions with `docker exec plum-snapcast-server aplay -l`
- **AirPlay not visible**: Verify Avahi is running and host Avahi is disabled
- **Bluetooth not pairing**: Check `docker exec plum-snapcast-server bluetoothctl show` and verify `BLUETOOTH_DISCOVERABLE=1`
- **Bluetooth no audio**: Verify bluealsa service is running with `docker exec plum-snapcast-server supervisorctl status bluealsa`
- **D-Bus errors**: Ensure host D-Bus socket is mounted and accessible
- **Audio group mismatch**: Verify container audio group is GID 29

---

## Deployment

### Environments
- **Development**: Local machine with Docker Desktop (macOS/Linux/Windows)
- **Production**: Raspberry Pi (3 or newer) with Raspberry Pi OS Lite (64-bit)

### Deployment Process

#### One-Time Raspberry Pi Setup

1. **Install Docker**:
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   # Log out and back in
   ```

2. **Configure Audio Permissions**:
   ```bash
   echo 'SUBSYSTEM=="sound", MODE="0666"' | sudo tee /etc/udev/rules.d/99-audio-permissions.rules
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

3. **Disable Host Avahi**:
   ```bash
   sudo systemctl disable avahi-daemon.service
   sudo systemctl disable avahi-daemon.socket
   # Host D-Bus stays enabled (socket-activated)
   ```

4. **Clone and Deploy**:
   ```bash
   git clone <repo-url> ~/Plum-Snapcast
   cd ~/Plum-Snapcast/docker
   cp .env.example .env
   nano .env  # Edit if needed
   docker compose pull
   docker compose up -d
   ```

5. **Reboot**:
   ```bash
   sudo reboot
   ```

#### Updating Existing Deployment

```bash
cd ~/Plum-Snapcast/docker
git pull
docker compose pull
docker compose up -d
```

### CI/CD Pipeline
- **Manual Process**: Build locally, push to Docker Hub
- **Build Script**: `docker/build-and-push.sh` handles multi-architecture builds
- **Deployment Triggers**: Manual pull on Raspberry Pi after image push
- **Rollback**: Use previous image tag in docker-compose.yml

---

## Important Notes for Development

1. **Attribution Required**: This project builds on firefrei/docker-snapcast. Always maintain proper attribution in CREDITS.md and respect upstream licensing.

2. **Critical Architecture Pattern**:
   - Container is fully self-contained with its own D-Bus and Avahi
   - No host system configuration required (except Docker and audio device access)
   - Container works identically across different host OS versions
   - D-Bus and Avahi managed by supervisord with proper startup priorities

3. **WebSocket Connection Management**:
   - Always check `isConnected` before sending requests
   - Handle connection failures gracefully with fallback UI
   - Implement reconnection logic for network interruptions

4. **Stream Capabilities**:
   - Not all streams support all controls (play, pause, seek, next, previous)
   - Always check `stream.properties` for available capabilities
   - Use `Stream.Control` method for playback commands

5. **Volume Control Patterns**:
   - Individual client volume via `Client.SetVolume`
   - No direct group volume API - adjust all clients in group individually
   - Track pre-mute volumes for proper mute/unmute behavior

6. **Metadata Handling**:
   - Metadata format varies by source (AirPlay pipe vs Spotify MPRIS vs Bluetooth AVRCP vs Pipe)
   - Always provide fallback values (Unknown Track, Unknown Artist, etc.)
   - Album art may be base64 data URL or external URL
   - Bluetooth streams currently do not provide album art (requires BlueZ 5.81+, see note #11)

7. **TypeScript Best Practices**:
   - Use explicit types from `types.ts`
   - Avoid `any` type except when necessary (WebSocket message parsing)
   - Leverage type checking for WebSocket message formats

8. **Rootless Container Security**:
   - Backend runs without root privileges (user: snapcast, UID 1000)
   - Audio group GID fixed to 29 to match Raspberry Pi host
   - Privileged mode required for /dev/snd device access

9. **Audio Device Access**:
   - Snapclient runs inside same container as snapserver
   - Requires privileged mode AND proper /dev/snd permissions
   - Host must have udev rule: `SUBSYSTEM=="sound", MODE="0666"`
   - Container audio group must match host device group (GID 29)

10. **Multi-room Considerations**:
    - This deployment integrates snapclient for single-device setup
    - For true multi-room, deploy additional snapclient-only containers
    - All clients must be on same Layer 2 network for mDNS discovery

11. **Bluetooth Limitations and Future Enhancements**:
    - **Album Art Not Available**: AVRCP 1.6+ supports album art via BIP (Bluetooth Image Profile), but implementation requires:
      - BlueZ 5.81+ (Alpine currently ships 5.70)
      - Experimental D-Bus interfaces enabled (bluetoothd with `-E` flag)
      - OBEX client implementation to download 200x200 JPEG thumbnails
      - Query `ObexPort` property from MediaPlayer1 interface
      - Download image via OBEX protocol and convert to data URL
    - **Implementation Path** (when BlueZ 5.81+ becomes available in Alpine):
      1. Modify `bluetooth-init.sh` to start bluetoothd with experimental flag
      2. Update `bluetooth-control-script.py` to detect BIP support
      3. Query MediaPlayer1 `ObexPort` property when track changes
      4. Implement OBEX image download using Python `dbus` bindings
      5. Convert downloaded image to base64 data URL
      6. Add image to metadata response sent to Snapcast
    - **Why Album Art Works for AirPlay but Not Bluetooth**:
      - AirPlay uses custom metadata protocol (shairport-sync pipe) with embedded artwork
      - Bluetooth AVRCP 1.5 only provides text metadata (title, artist, album)
      - AVRCP 1.6 BIP requires separate OBEX connection to retrieve artwork
    - **Modern Device Support**: iOS 13+, Android 12+ support AVRCP 1.6 album art

---

## Resources & References

- **Repository**: [Your GitHub/GitLab URL]
- **Snapcast Documentation**: https://github.com/badaix/snapcast
- **Snapcast JSON-RPC API**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/
- **Docker Snapcast**: https://github.com/firefrei/docker-snapcast
- **Shairport-Sync**: https://github.com/mikebrady/shairport-sync
- **Spotifyd**: https://github.com/Spotifyd/spotifyd
- **Librespot**: https://github.com/librespot-org/librespot (foundation for spotifyd)
- **Alpine Linux Packages**: https://pkgs.alpinelinux.org/

---

## Quick Reference

### Most Common Commands

```bash
# Development
cd frontend && npm run dev                # Start frontend dev server
cd frontend && npm run build              # Build frontend for production

# Testing
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
docker exec plum-snapcast-server aplay -l # Verify audio devices
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1

# Docker
docker logs plum-snapcast-server                    # View container logs
docker exec -it plum-snapcast-server sh             # Access container shell
docker compose up -d                                 # Start containers
docker compose down                                  # Stop containers
docker compose restart                               # Restart all services

# Build and Deploy
cd docker && bash build-and-push.sh                 # Build multi-arch images
cd docker && docker compose pull && docker compose up -d  # Update deployment

# Debugging
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapclient
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f shairport-sync
docker logs plum-snapcast-server 2>&1 | grep -i "error\|fail"
```

### File Locations
- **Backend Config**: `/app/config/` (in container) - Maps to `snapcast-config` volume
- **Backend Data**: `/app/data/` (in container) - Maps to `snapcast-data` volume
- **Logs**: Accessible via `docker logs plum-snapcast-server` or supervisorctl tail
- **Frontend Build**: `frontend/dist/` (after `npm run build`)
- **Documentation**: `/docs/` folder (all docs except README.md)
- **ARCHITECTURE.md**: `/docs/ARCHITECTURE.md` (system architecture)
- **CLAUDE.md**: `/docs/CLAUDE.md` (symlinked to root)
- **Reference Materials**: `/_resources/` (NOT in git - for dev use only)

### Troubleshooting Audio Issues

```bash
# Check all services running
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status

# Expected output:
# avahi              RUNNING
# shairport-sync     RUNNING
# snapclient         RUNNING
# snapserver         RUNNING

# If snapclient is FATAL:
docker logs plum-snapcast-server | grep snapclient

# Check audio devices accessible
docker exec plum-snapcast-server aplay -l
# Should show: card 0: Headphones [bcm2835 Headphones]

# Test speaker output
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1

# Fix audio permissions on host
sudo chmod 666 /dev/snd/*
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Troubleshooting AirPlay Discovery

```bash
# Check Avahi is running
docker exec plum-snapcast-server ps aux | grep avahi

# Verify host Avahi is disabled
sudo systemctl status avahi-daemon.service
# Should show: disabled

# Check D-Bus socket accessible
docker exec plum-snapcast-server test -S /var/run/dbus/system_bus_socket && echo "OK" || echo "FAIL"

# Scan for AirPlay services (from another machine)
avahi-browse -r _raop._tcp

# Restart services
docker compose restart
```

---

## Notes for Maintaining This File

**When to Update**:
- Major architectural changes (also update ARCHITECTURE.md)
- New audio source added
- Changes to Docker configuration or deployment process
- Updates to environment variables
- New development workflows or conventions
- Security policy changes

**What Not to Include**:
- Temporary development notes (use `_resources/` instead)
- Duplicate information from README.md or ARCHITECTURE.md
- Overly detailed API specs (link to external docs)
- Version-specific bugs (use issue tracker)

**Tips**:
- Keep examples up-to-date with actual code
- Document WHY decisions were made, not just WHAT
- Test all command examples before adding them
- Remove outdated sections immediately
- Store draft updates in `_resources/` before committing
- Keep ARCHITECTURE.md in sync with major changes documented here
