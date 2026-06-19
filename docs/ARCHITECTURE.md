# Architecture Overview

This document provides a comprehensive understanding of the Plum-Snapcast codebase architecture, enabling efficient navigation and effective contribution from day one. This document is actively maintained as the codebase evolves.

## 1. Project Structure

The project follows a clean separation of concerns with distinct directories for backend services, frontend application, Docker orchestration, documentation, and development resources.

```
Plum-Snapcast/
├── backend/                    # Snapcast server container (Alpine Linux)
│   ├── Dockerfile              # Multi-arch build configuration
│   ├── README.md              # Backend-specific documentation
│   ├── plexamp/               # Plexamp sidecar container (Debian)
│   │   ├── Dockerfile         # Debian-based container for Plexamp headless
│   │   └── README.md          # Plexamp setup documentation
│   ├── config/                # Service configurations
│   │   ├── supervisord/       # Process management configs
│   │   │   ├── supervisord.conf     # Main supervisor config
│   │   │   ├── snapcast.ini         # Snapcast services config
│   │   │   └── snapclient.ini       # Audio output client config
│   │   └── shairport-sync.conf      # AirPlay receiver config
│   └── scripts/               # Container initialization scripts
│       ├── setup.sh           # Container startup script
│       ├── stream-lifecycle-manager.py         # AirPlay lifecycle manager
│       ├── bluetooth-stream-lifecycle-manager.py  # Bluetooth lifecycle manager
│       ├── spotify-stream-lifecycle-manager.py    # Spotify lifecycle manager
│       ├── dlna-stream-lifecycle-manager.py       # DLNA lifecycle manager
│       ├── plexamp-stream-lifecycle-manager.py    # Plexamp lifecycle manager
│       ├── fifo-keeper.sh                      # AirPlay FIFO keeper
│       ├── bluetooth-fifo-keeper.sh            # Bluetooth FIFO keeper
│       ├── spotify-fifo-keeper.sh              # Spotify FIFO keeper
│       ├── dlna-fifo-keeper.sh                 # DLNA FIFO keeper
│       ├── airplay-control-script.py  # AirPlay metadata & control handler
│       ├── plexamp-control-script.py  # Plexamp metadata & control handler
│       └── federation/                # Multi-server federation
│           ├── api.py                 # REST API endpoints
│           ├── router.py              # Cross-server routing logic
│           ├── service.py             # Federation service orchestration
│           ├── discovery.py           # Avahi/mDNS server discovery
│           ├── websocket_manager.py   # WebSocket connections to servers
│           └── remote_snapclient_manager.py  # Remote snapclient lifecycle
├── frontend/                  # React/TypeScript web interface
│   ├── Dockerfile            # Nginx-based frontend container
│   ├── App.tsx               # Main application component
│   ├── index.tsx             # Application entry point
│   ├── components/           # Reusable UI components
│   │   ├── ClientManager/    # Client device management
│   │   ├── NowPlaying/       # Current track display
│   │   ├── PlayerControls/   # Playback controls
│   │   ├── Settings/         # Application settings
│   │   ├── StreamSelector/   # Audio source switching
│   │   └── SyncedDevices/    # Synchronized device display
│   ├── services/             # API and data services
│   │   ├── snapcastService.ts        # WebSocket communication
│   │   ├── snapcastDataService.ts    # Data transformation
│   │   └── federationService.ts      # Multi-server federation API
│   └── hooks/                # Custom React hooks
│       └── useAudioSync.ts   # Audio synchronization hook
├── docker/                   # Deployment orchestration
│   ├── docker-compose.yml   # Full stack definition
│   ├── .env.example         # Configuration template
│   ├── build-and-push.sh    # Multi-arch build script
│   ├── deploy.sh            # Quick deployment script
│   └── full-diagnostics.sh  # System diagnostic tool
├── docs/                    # Project documentation
│   ├── ARCHITECTURE.md      # This file
│   ├── CLAUDE.md            # Claude Code configuration
│   ├── DEV-SETUP.md         # Developer setup guide
│   └── QUICK-REFERENCE.md   # Quick reference guide
├── _resources/              # Development references (NOT in git)
│   ├── archived-docs/       # Historical implementation docs
│   ├── Examples/            # Code samples, API responses
│   ├── Research/            # Research docs, comparisons
│   ├── Assets/              # Design files, mockups
│   └── Notes/               # Meeting notes, scratchpad
├── scripts/                 # Utility scripts
├── README.md                # Main project overview
└── package.json             # Root-level dependencies
```

## 2. High-Level System Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                         Host Network                                    │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  Backend Container (Alpine, network_mode: host)              │     │
│  │  ┌────────────┐  ┌─────────────┐  ┌──────────────┐         │     │
│  │  │  Snapcast  │  │  Shairport  │  │   Librespot  │         │     │
│  │  │  Server    │←─│  -Sync      │  │   (Spotify)  │         │     │
│  │  │:1704-1705  │  │  (AirPlay)  │  │              │         │     │
│  │  └─────┬──────┘  └─────────────┘  └──────────────┘         │     │
│  │        │   ↑                                                 │     │
│  │        │   └── FIFO pipes (audio streams)                   │     │
│  │        │         ┌──────────────┐                           │     │
│  │        └────────→│  Snapclient  │──→ 🔊 Audio Output       │     │
│  │                  │  (Integrated)│                           │     │
│  │                  └──────────────┘                           │     │
│  │                                                              │     │
│  │  ┌─────────────┐  ┌─────────────┐                          │     │
│  │  │   Avahi     │  │    D-Bus    │                          │     │
│  │  │  (mDNS)     │  │   System    │                          │     │
│  │  └─────────────┘  └─────────────┘                          │     │
│  │                                                              │     │
│  │  Managed by Supervisord                                     │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                              ↑  ↑                                      │
│                              │  │                                      │
│                     (metadata)  (audio FIFO)                           │
│                              │  │                                      │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  Plexamp Container (Debian, optional)                        │     │
│  │  ┌──────────────┐        ┌───────────────────┐             │     │
│  │  │  Plexamp     │───────→│  ALSA → FIFO      │─────────────┘     │
│  │  │  Headless    │        │  (S16_LE/44.1kHz) │                    │
│  │  │  :32500      │        └───────────────────┘                    │
│  │  └──────────────┘                                                 │
│  │  Shared volumes: plexamp-data, snapcast-fifos                     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  Frontend Container                                          │     │
│  │  Nginx serving React app on :3000                           │     │
│  │  WebSocket client connects to :1704                         │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
     ↑               ↑                                ↑
AirPlay from    Spotify App                     Browser access
iOS/macOS       Plex App                   http://localhost:3000
```

## 3. Core Components

### 3.1. Frontend (Web Application)

**Name**: Plum-Snapcast Web Interface

**Description**: Modern React/TypeScript application providing real-time control and visualization of the Snapcast multi-room audio system. Users can manage audio streams, control individual clients, adjust volumes, and view currently playing metadata through an intuitive web interface.

**Technologies**:
- React 19.1.1
- TypeScript 5.8.2
- Vite 6.2.0 (build tool)
- WebSocket (for real-time communication)
- Custom CSS with CSS variables for theming

**Deployment**: Docker container with Nginx serving static files

**Key Features**:
- Real-time audio synchronization visualization
- Client and group management
- Volume control (individual and group)
- Stream switching
- Now playing metadata display with album art
- Responsive design

### 3.2. Backend Services

#### 3.2.1. Snapcast Server

**Name**: Multi-Room Audio Synchronization Server

**Description**: Core service handling synchronized audio streaming across multiple client devices. Manages audio streams from various sources (AirPlay, Spotify, FIFO pipes), distributes audio to connected clients with sample-accurate synchronization, and provides JSON-RPC 2.0 API for control.

**Technologies**:
- Snapcast 0.27+ (from Alpine edge repositories)
- Alpine Linux 3.19+
- Supervisord for process management
- JSON-RPC 2.0 over WebSocket

**Deployment**: Docker container with `network_mode: host` for optimal mDNS support

**Ports**:
- 1704-1705: Client connections
- 1780: HTTP/WebSocket control (legacy)
- 1788: HTTPS/WebSocket control

#### 3.2.2. Snapcast Client (Integrated)

**Name**: Audio Output Client

**Description**: Integrated audio client that outputs synchronized audio to the local hardware device. Unlike typical Snapcast deployments where clients run on separate devices, this implementation includes a client in the same container for simplified single-device deployments (perfect for Raspberry Pi).

**Technologies**:
- Snapcast client
- ALSA for audio output
- Configured for hw:Headphones (Raspberry Pi 3.5mm jack)

**Deployment**: Same container as Snapcast server, managed by Supervisord

#### 3.2.3. Shairport-Sync (AirPlay Receiver)

**Name**: AirPlay Audio Receiver (Multi-Instance)

**Description**: Receives AirPlay and AirPlay 2 audio streams from iOS/macOS devices and pipes them into Snapcast for synchronized multi-room playback. Supports up to 10 simultaneous AirPlay endpoints, each with unique device names and ports.

**Multi-Instance Architecture**:
- Each endpoint runs a separate shairport-sync instance
- Instances have unique ports, FIFO pipes, metadata pipes, and lifecycle managers
- Control script wrapper pattern (`airplay-control-script-{id}.py`) works around Snapcast's no-arguments limitation
- Endpoint management via REST API (`/api/airplay/endpoints`)
- Stream names: "AirPlay - [deviceName]"

**Technologies**:
- Shairport-Sync (latest from Alpine repositories)
- MQTT for real-time metadata and control (distinguishes pause from disconnect)
- D-Bus for playback controls (endpoint 1 only to avoid conflicts)
- Avahi for mDNS service discovery
- Python control script with instance-specific wrappers

**Deployment**: Managed by Supervisord, dynamically configured via `generate-airplay-supervisord-config.py`

**Ports (per endpoint, N = endpoint ID)**:
- 5050-5059: AirPlay Classic/1 streaming (5050 + N - 1)
- 3689, 5353/udp: mDNS service discovery
- UDP 6001-6100: RTP/timing ports (6001 + (N-1) × 10 base)
- 319-320/udp: NQPTP for AirPlay 2

#### 3.2.4. Spotifyd (Spotify Connect)

**Name**: Spotify Connect Endpoint

**Description**: Optional service that makes the system appear as a Spotify Connect device, allowing users to cast audio from the Spotify app directly to the multi-room audio system.

**Technologies**:
- Spotifyd (uses D-Bus MPRIS for metadata, unlike librespot)
- Patched with-avahi to avoid port conflicts
- Configured to output to Snapcast FIFO pipe
- Album art cached to `/usr/share/snapserver/snapweb/coverart/`

**Deployment**: Optional, enabled via Settings → Integrations in web UI

#### 3.2.5. Plexamp (Plex Music Casting)

**Name**: Plexamp Headless Endpoint

**Description**: Optional service that makes the system appear as a Plexamp player, allowing users to cast music from Plex Media Server to the multi-room audio system. Requires Plex Pass subscription.

**Technologies**:
- Plexamp headless (Node.js application)
- Debian container (separate from Alpine backend due to glibc requirements)
- ALSA audio redirection to shared FIFO pipe
- JSON file monitoring for metadata (PlayQueue.json)
- HTTP API for playback controls

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│ Debian Container (plum-plexamp)                             │
│  ┌──────────────┐        ┌─────────────────────────────┐   │
│  │  Plexamp     │───────→│  ALSA (asound.conf)         │   │
│  │  Headless    │        │  ┌────────────────────────┐ │   │
│  │  :32500      │        │  │ plug → convert         │ │   │
│  │              │        │  │   (S16_LE/44.1kHz/2ch) │ │   │
│  │              │        │  │ → file → FIFO          │ │   │
│  │              │        │  └────────────────────────┘ │   │
│  └──────────────┘        └─────────────────────────────┘   │
│         │                                 │                 │
│         │                                 │                 │
│    (State files)                    (Audio data)            │
│         ↓                                 ↓                 │
│  ┌─────────────────┐           ┌─────────────────────┐    │
│  │ plexamp-data    │           │ snapcast-fifos      │    │
│  │ volume          │           │ volume              │    │
│  └─────────────────┘           └─────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
           │                               │
           │ (read-only mount)             │ (shared mount)
           ↓                               ↓
┌─────────────────────────────────────────────────────────────┐
│ Alpine Container (plum-snapcast-server)                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ plexamp-control-script.py                            │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │ 1. Monitor PlayQueue.json (every 2s)           │  │  │
│  │  │ 2. Extract metadata (title/artist/album/art)   │  │  │
│  │  │ 3. Download artwork from Plex server           │  │  │
│  │  │ 4. Handle playback controls via HTTP API       │  │  │
│  │  │    - http://127.0.0.1:32500/player/playback/*  │  │  │
│  │  │ 5. Send updates to Snapcast via JSON-RPC       │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                 │
│                           ↓                                 │
│                  ┌─────────────────┐                        │
│                  │  Snapcast       │                        │
│                  │  Server         │                        │
│                  │  :1704-1705     │                        │
│                  └─────────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

**Key Design Decisions**:
1. **Two-Container Architecture**: Plexamp requires glibc (Debian), while core services use musl (Alpine)
2. **JSON File Monitoring**: More reliable than HTTP API polling for real-time metadata
3. **Shared Volumes**: Audio FIFO and state files shared between containers
4. **ALSA Format Conversion**: Explicit S16_LE/44.1kHz/stereo conversion prevents audio distortion
5. **HTTP API for Controls**: Play/pause/next/previous commands via Plexamp's HTTP endpoints

**Control API Endpoints**:
- `GET http://127.0.0.1:32500/player/playback/play` - Resume playback
- `GET http://127.0.0.1:32500/player/playback/pause` - Pause playback
- `GET http://127.0.0.1:32500/player/playback/skipNext` - Skip to next track
- `GET http://127.0.0.1:32500/player/playback/skipPrevious` - Skip to previous track

**Metadata Sources**:
- `PlayQueue.json` - Current track, playback state, position
- `@Plexamp:resources` - Plex server URI for artwork downloads

**Deployment**: Optional, enabled via Docker Compose profile (`--profile plexamp`)

#### 3.2.6. Service Discovery (Avahi + D-Bus)

**Name**: Network Service Discovery

**Description**: Enables automatic device discovery on the local network. Avahi broadcasts the AirPlay service via mDNS, making the device visible in AirPlay menus without manual configuration.

**Technologies**:
- Avahi daemon (runs in container)
- D-Bus system bus (from host, mounted into container)

**Critical Architecture**:
- **Host**: Provides D-Bus socket at `/var/run/dbus/system_bus_socket`
- **Container**: Runs Avahi, connects to host's D-Bus
- **Host Avahi**: MUST be disabled to avoid conflicts

**Deployment**: Managed by Supervisord

## 4. Data Stores

### 4.1. Server Configuration

**Name**: Persistent Configuration Storage

**Type**: Volume-mounted filesystem (`/app/config`)

**Purpose**: Stores Snapcast server configuration, shairport-sync configuration, supervisord logs, and runtime state

**Key Files**:
- `snapserver.conf` - Snapcast server configuration
- `shairport-sync.conf` - AirPlay receiver configuration
- `supervisord.log` - Process management logs
- `server.json` - Runtime server state

### 4.2. Temporary Audio Pipes

**Name**: FIFO Pipes for Audio Streaming

**Type**: Named pipes in `/tmp`

**Purpose**: Intermediate audio transport between audio sources (AirPlay, Spotify) and Snapcast server

**Key Pipes**:
- `/tmp/snapfifo` - Default FIFO for audio input

### 4.3. Metadata Storage

**Name**: Album Artwork and Metadata Cache

**Type**: Temporary files in `/tmp`

**Purpose**: Stores album artwork from AirPlay for encoding and transmission to frontend

**Key Directories**:
- `/tmp/shairport-sync/.cache/coverart/` - Artwork cache written by shairport-sync
  - Contains `cover-{timestamp}.jpg` files
  - Automatically created by `setup.sh` on container startup
  - Read by Python control script to load artwork
  - Requires proper permissions (777) for write access

**Important Notes**:
- Cache directory **must exist** before shairport-sync starts, or artwork will fail silently
- Control script tracks last loaded file to prevent duplicates
- Artwork is base64-encoded and sent via Snapcast stream properties
- Cache files are ephemeral (cleared on container restart)

## 5. External Integrations / APIs

**Service Name**: Snapcast JSON-RPC 2.0 API

**Purpose**: Control interface for managing streams, clients, groups, and playback

**Integration Method**: WebSocket with JSON-RPC 2.0 protocol

**Key Methods**:
- `Server.GetStatus` - Retrieve complete server state
- `Client.SetVolume` - Adjust client volume
- `Group.SetStream` - Assign stream to group
- `Stream.Control` - Control stream playback

**Documentation**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/

### 5.2. REST APIs (Flask)

The backend exposes several REST APIs for configuration and control. All APIs are proxied through nginx on the frontend port.

#### Settings API
- **Base URL**: `/api/settings`
- **Implementation**: `backend/scripts/settings_api.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/settings` | Get current settings |
| POST | `/api/settings` | Update settings (partial or full) |

#### Integrations API
- **Base URL**: `/api/integrations`
- **Implementation**: `backend/scripts/integrations_api.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/integrations/{service}/enable` | Enable integration |
| POST | `/api/integrations/{service}/disable` | Disable integration |
| POST | `/api/integrations/{service}/device-name` | Update device name |
| GET | `/api/integrations/{service}/status` | Get integration status |

Services: `airplay`, `bluetooth`, `spotify`, `dlna`

#### AirPlay Endpoints API
- **Base URL**: `/api/airplay/endpoints`
- **Implementation**: `backend/scripts/airplay_endpoints_api.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/airplay/endpoints` | List all AirPlay endpoints |
| POST | `/api/airplay/endpoints` | Add new endpoint |
| PUT | `/api/airplay/endpoints/:id` | Update endpoint |
| DELETE | `/api/airplay/endpoints/:id` | Remove endpoint |

**Endpoint Object**:
```json
{
  "id": "1",
  "enabled": true,
  "deviceName": "Living Room",
  "port": 5050,
  "udpPortBase": 6001
}
```

#### Spotify Endpoints API
- **Base URL**: `/api/integrations/spotify/endpoints`
- **Implementation**: `backend/scripts/spotify_endpoints_api.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/integrations/spotify/endpoints` | List all Spotify endpoints |
| POST | `/api/integrations/spotify/endpoints` | Add new endpoint |
| PUT | `/api/integrations/spotify/endpoints/:id` | Update endpoint |
| DELETE | `/api/integrations/spotify/endpoints/:id` | Remove endpoint |

**Endpoint Object**:
```json
{
  "id": "1",
  "enabled": true,
  "deviceName": "Living Room",
  "zeroconfPort": 5354
}
```

#### DLNA Endpoints API
- **Base URL**: `/api/integrations/dlna/endpoints`
- **Implementation**: `backend/scripts/dlna_endpoints_api.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/integrations/dlna/endpoints` | List all DLNA endpoints |
| POST | `/api/integrations/dlna/endpoints` | Add new endpoint |
| PUT | `/api/integrations/dlna/endpoints/:id` | Update endpoint |
| DELETE | `/api/integrations/dlna/endpoints/:id` | Remove endpoint |

**Endpoint Object**:
```json
{
  "id": "1",
  "enabled": true,
  "deviceName": "Living Room",
  "port": 49494,
  "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Audio Configuration API
- **Base URL**: `/api/audio`
- **Implementation**: `backend/scripts/audio_api.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/audio/devices/output` | List all ALSA playback devices |
| GET | `/api/audio/output/current` | Get currently configured output |
| POST | `/api/audio/output/device` | Set output device |
| POST | `/api/audio/output/test` | Test output device |
| GET | `/api/audio/devices/input` | List all ALSA capture devices |
| POST | `/api/audio/input/device` | Add/update input device |
| DELETE | `/api/audio/input/device/:hw_id` | Remove input device |

**Hardware Mixer Support**:

Audio devices automatically detect available ALSA hardware mixers (e.g., "Digital", "PCM", "Master") when listing output devices. The system uses device-type-specific priority lists to select the best mixer:

- **HAT devices**: Digital → PCM → Master
- **USB devices**: PCM → Speaker → Master
- **Built-in Headphones**: Headphone → PCM
- **Built-in HDMI**: HDMI

When a device with hardware mixer is selected, the mixer configuration is saved to `settings.json` and applied to both local and remote snapclients. This enables proper volume control via hardware mixers instead of software-only mixing.

**Device Format Conversion**: When hardware mixer is enabled, the system automatically converts direct device access (`hw:X,Y`) to dmix format (`default:CARD=name`) to enable both mixer access (card-level) and device sharing between multiple snapclients.

**Response Object** (from `/api/audio/devices/output`):
```json
{
  "hw_id": "hw:3,0",
  "friendly_name": "snd_rpi_hifiberry_dacplus (HAT)",
  "type": "HAT",
  "mixer": {
    "type": "hardware",
    "device": "hw:3",
    "name": "Digital",
    "index": "0"
  }
}
```

#### Playback Position API
- **Base URL**: `/api/playback` (via Federation API port 5001)
- **Implementation**: `backend/scripts/playback_api.py`
- **Purpose**: Real-time position tracking without audio stuttering

**Problem**: Snapcast's `Plugin.Stream.Player.Properties` notifications cause audio stuttering when position updates are pushed frequently.

**Solution**: Independent position tracking with server-side interpolation:
1. Control scripts POST position updates on actual changes (track start, seek, pause)
2. Server interpolates position between updates using dual timestamps
3. Frontend polls for interpolated position every 2 seconds
4. No impact on Snapcast audio pipeline

**Dual-Timestamp Architecture**:
- `last_update`: Updated on every heartbeat (prevents staleness detection)
- `position_timestamp`: Updated only when position changes >500ms (enables interpolation)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/playback/:stream_id` | Update position (from control scripts) |
| GET | `/api/playback/:stream_id` | Get position for specific stream |
| GET | `/api/playback` | Get position for all streams |
| DELETE | `/api/playback/:stream_id` | Remove position data |

**Response Object**:
```json
{
  "stream_id": "AirPlay - Living Room",
  "position": 45000,
  "duration": 180000,
  "playback_status": "playing",
  "interpolated_position": 47000,
  "last_update": 1735600000.0,
  "position_timestamp": 1735600000.0,
  "age_seconds": 2.0,
  "is_stale": false
}
```

#### Federation API

**Port**: 5001 (internal only)
**File**: `backend/scripts/federation/api.py`
**Purpose**: Multi-server federation with cross-server routing

The Federation API provides a unified control plane for multiple Snapcast servers, enabling:
- **Unified View**: See all streams and clients from all servers in one interface
- **Cross-Server Control**: Control volume and playback for clients on any server
- **Cross-Server Routing**: Route any client to any stream across the federation

**Key Endpoints**:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/federation/servers` | List all discovered servers and connection status |
| GET | `/api/federation/status` | Aggregated streams and clients from all servers |
| GET | `/api/federation/active-endpoint` | Get currently active output client and stream |
| POST | `/api/federation/route` | Route a client to a stream (cross-server capable) |
| POST | `/api/federation/volume` | Set client volume on any server |
| POST | `/api/federation/control` | Send playback control commands to streams |

**Architecture**:
- **Discovery**: Avahi/mDNS discovers `_snapcast-http._tcp` services on the network
- **WebSocket Connections**: Persistent JSON-RPC 2.0 connections to each discovered server
- **Remote Snapclients**: Each server runs snapclients connected to remote servers for cross-server audio
- **Endpoint Lockout**: Only one output client is active at a time across the entire federation

**Cross-Server Routing Flow**:
```
User selects remote stream
        ↓
Frontend calls POST /api/federation/route
        ↓
FederationRouter.route_client()
        ↓
1. Deactivate all active endpoints (route to none)
2. Find remote snapclient on target server
3. Route remote snapclient to desired stream
4. Also route local output client on target server
        ↓
Audio plays from remote server through local hardware
```

**ID Format**:
- Federated IDs use `server-{ip}-{local-id}` format (e.g., `server-192-168-7-122-spotify1`)
- Local IDs are the original Snapcast IDs (e.g., `spotify1`)
- The router parses and translates between formats automatically

**Client Deduplication**:
Remote snapclients (connected to a master) appear on both the local and remote server. The federation API deduplicates them using the raw `hostID` field (`_get_raw_client_id`) so they show as a single logical client in the unified view.

#### Auto-Switch Service

**File**: `backend/scripts/auto-switch-service.py`
**Supervisord**: `backend/config/supervisord/auto-switch.ini`
**Purpose**: Automatically routes the local snapclient to a master unit when the master is active, and back to local when the master goes idle.

**Modes**:

| Mode | Behaviour |
|------|-----------|
| **Local-activity** | When a source connects to this unit and the output is idle, switch to that stream (default on) |
| **Slave (follow master)** | When a configured master starts playing and this unit is idle, join the master's stream |

**Fast-switch architecture (slave mode)**:

The key problem with a naive "restart snapclient on master-active" approach is that `snapclient` takes several seconds to connect and buffer audio, creating an audible gap. The service avoids this by keeping the local snapclient **permanently connected** to the master in a *pre-connected* state:

```
Slave snapclient → master snapserver → none stream (silent)
                                            ↓
                               Master goes active (AirPlay, etc.)
                                            ↓
                   Snapcast group assignment updated: none → master stream
                                            ↓
                          Audio plays instantly (no reconnect needed)
```

The group assignment is a lightweight JSON-RPC call to snapserver — no process restart, no ALSA reinitialisation. Switching latency drops from ~5–20 s to under 1 s.

**State machine**:
- `IDLE`: Not following. Monitors master WebSocket for activity.
- `PRE_CONNECTED`: Snapclient is connected to master's `none` stream, ready to switch instantly.
- `FOLLOWING`: Snapclient routed to master's active audio stream.

**Hysteresis**: A 5 s idle timer prevents reversion to local during momentary gaps (e.g. track changes). Local connections always take priority and cause an immediate revert to local mode.

**Configuration** (Settings → Playback):
- `autoSwitch.localActivity` — toggle local-activity mode
- `autoSwitch.slave.enabled` — toggle slave mode
- `autoSwitch.slave.masterHost` — master hostname or IP
- `autoSwitch.slave.masterWsPort` — master WebSocket port (default: 1780)
- `autoSwitch.slave.masterStreamPort` — master stream port (default: 1704)

#### AirPlay Notification Stutter Fixes

**File**: `backend/scripts/airplay-control-script.py`

**Upstream root cause (known, unfixed Snapcast bug).** Each `Plugin.Stream.Player.Properties` notification sent to snapserver triggers `onResync()` on all connected snapclients, producing a ~50–120 ms audio gap. This is not specific to our setup — it is a confirmed, reproducible Snapcast issue with no upstream fix:

- [snapcast/snapcast#1351](https://github.com/snapcast/snapcast/issues/1351) — "Stuttering when pushing properties data to SnapServer through a plugin." The reporter isolated the stutter to the Properties push *itself* (querying the backend without forwarding to snapserver produces no stutter), and it occurs at *any* frequency (tested 1 s → 10 min). A high `onResync` followed by two audible stutters.
- [snapcast/snapcast#1318](https://github.com/snapcast/snapcast/issues/1318) — shairport-sync-through-snapserver stuttering with `onResync` ~once/sec; worsens on quiet passages.
- [badaix/snapcast#433](https://github.com/badaix/snapcast/issues/433) — generic `onResync` audio dropout.

**Consequence:** we cannot make an individual Properties push cheap — we can only reduce *how many* we send. The control script therefore applies five guards to minimise unnecessary notifications:

| Guard | Where | What it fixes |
|-------|-------|---------------|
| **Volume debounce** (500 ms) | `DBusControl._fire_volume_change` | iOS sends many D-Bus Volume signals while dragging the slider; collapsed to one notification |
| **Track-change pause guard** (2 s) | `SnapcastControlScript.send_playback_state_update` | `playing→paused→playing` from a track change generates spurious resyncs; the guard holds the pause and cancels if `playing` arrives within 2 s |
| **Resume suppression** | `SnapcastControlScript.send_playback_state_update` | when the pause guard cancels (track change), the held pause was never sent — so re-sending `playing` is a net `playing→playing` no-op. Tracked via `_last_sent_playback_state`; suppressed to avoid a mid-track resync on skip |
| **Metadata debounce** (400 ms) | `SnapcastControlScript.send_metadata_update` | shairport-sync emits title/artist/album/art as separate pipe items; debounce collapses the burst into one notification |
| **Metadata content-dedup** | `SnapcastControlScript._fire_metadata_update` | shairport-sync resends the same metadata bundle every ~200–350 ms; dedup suppresses sends where `(status, title, artist, album)` is unchanged since last notification |

Additionally, `send_playback_state_update` only fires when playback status or volume **actually changes** — no periodic heartbeat resends that would cause repeated resyncs during paused/scrubbing states.

**Residual limits (not fixable from the control script):**
- **Different-song skip** still incurs exactly one Properties push — the new title/art legitimately has to reach the UI — so one `onResync` blip remains per #1351. The only way to eliminate it is to deliver metadata out-of-band through our own API (as already done for position in `playback_api.py`) and stop pushing it through Snapcast Properties entirely. Deferred (larger frontend+backend change).
- **AirPlay buffer-flush gap.** On a mid-track skip, shairport-sync issues a `Play stream FLUSH` (discards the buffered audio), goes briefly silent, then refills the FIFO with the new track. This silence→refill is a physical discontinuity at the `shairport-sync → FIFO → snapserver → snapclient` audio layer — inherent to the AirPlay protocol, present even with zero notifications, and not addressable by the control script or by snapserver buffering.

## 6. Deployment & Infrastructure

**Cloud Provider**: Self-hosted (Raspberry Pi or x86_64 servers)

**Key Services Used**:
- Docker 20.10+
- Docker Compose 2.0+
- Multi-architecture images (amd64, arm64)

**CI/CD Pipeline**: Manual builds using `build-and-push.sh` script

**Container Registry**: Docker Hub (public images)

**Monitoring & Logging**:
- Supervisord logs: `/app/config/supervisord.log`
- Docker logs: `docker logs plum-snapcast-server`
- Debug mode: Enable via `DEBUG=true` environment variable

**Network Architecture**:
- Backend: `network_mode: host` for mDNS/Avahi support
- Frontend: Standard bridge network with port mapping

## 7. Security Considerations

**Authentication**:
- Built-in HTTPS support with self-signed certificates
- Optional external authentication via reverse proxy
- No authentication required for local network access

**Authorization**:
- Full control access via WebSocket API (no role-based access)
- Designed for trusted local networks only

**Data Encryption**:
- TLS in transit (HTTPS/WSS) optional via environment variable
- No encryption at rest (configuration files in plaintext)

**Key Security Tools/Practices**:
- Rootless container execution (user: snapcast)
- Minimal attack surface (Alpine Linux base)
- No exposed SSH or shell access by default
- Regular base image updates recommended

**Security Considerations**:
- **Not designed for public internet exposure**
- Intended for trusted home networks only
- Consider using a reverse proxy (Nginx, Traefik) with proper authentication for remote access
- Audio device access requires privileged mode (security trade-off for functionality)

## 8. Development & Testing Environment

**Local Setup Instructions**: See [DEV-SETUP.md](DEV-SETUP.md)

**Testing Frameworks**:
- Frontend: Vite's built-in test runner (optional)
- Backend: Manual testing and system validation

**Code Quality Tools**:
- TypeScript for type safety
- ESLint (frontend, optional)
- Prettier (frontend, optional)

**Development Workflow**:
1. Make changes in `backend/` or `frontend/`
2. Build locally: `docker build -t test-image .`
3. Test with docker-compose: `docker-compose up -d`
4. Verify functionality
5. Build multi-arch images: `./docker/build-and-push.sh`
6. Deploy to target devices: `./docker/deploy.sh`

## 9. Future Considerations / Roadmap

- **Migrate to multi-container architecture**: Separate snapclient from snapserver for true multi-room capability
- **Add authentication layer**: Implement user authentication for remote access
- **Implement Home Assistant integration**: MQTT or REST API bridge
- **Add Bluetooth source**: Support for Bluetooth audio input
- **Implement equalization**: Per-room EQ and sound profiles
- **Add playlist management**: Support for stored playlists and presets
- **Performance optimization**: Reduce latency, optimize metadata processing
- **Enhanced artwork handling**: Better album art resolution and caching

## 10. Project Identification

**Project Name**: Plum-Snapcast

**Repository URL**: [Insert Repository URL]

**Primary Contact/Team**: [Insert Contact]

**Original Attribution**:
- Based on: firefrei/docker-snapcast by Matthias Frei
- Snapcast: https://github.com/badaix/snapcast by Johannes Pohl
- Shairport-Sync: https://github.com/mikebrady/shairport-sync by Mike Brady

**Date of Last Update**: 2025-12-15

## 11. Glossary / Acronyms

**Snapcast**: Multi-room audio synchronization protocol and server

**AirPlay**: Apple's proprietary wireless audio streaming protocol

**mDNS**: Multicast DNS - Protocol for service discovery on local networks

**Avahi**: Open-source implementation of mDNS/DNS-SD

**D-Bus**: Inter-process communication (IPC) system for Linux

**FIFO**: First-In-First-Out pipe - Named pipe for audio transport

**JSON-RPC**: Remote procedure call protocol using JSON

**Supervisord**: Process control system for Unix-like operating systems

**ALSA**: Advanced Linux Sound Architecture - Linux audio framework

**Librespot**: Open-source Spotify Connect client

**WSS**: WebSocket Secure - WebSocket protocol over TLS

**PUID/PGID**: Process User ID / Process Group ID (Docker user mapping)

**UMASK**: User file-creation mode mask (Unix file permissions)

## 12. Audio Pipeline Flow

Understanding the complete audio path is essential for debugging and optimization:

```
┌─────────────────┐
│  Audio Source   │
│  (iOS/Mac/PC)   │
└────────┬────────┘
         │
         ├──── AirPlay Protocol ────────┐
         │                               ↓
         │                    ┌──────────────────┐
         │                    │  Shairport-Sync  │
         │                    │  Receives AirPlay│
         │                    └────────┬─────────┘
         │                             │
         └──── Spotify Connect ────┐   │
                                   ↓   ↓
                            ┌─────────────────┐
                            │  /tmp/snapfifo  │
                            │  (FIFO Pipe)    │
                            └────────┬────────┘
                                     │
                                     ↓
                            ┌─────────────────┐
                            │  Snapcast       │
                            │  Server         │
                            │  (Synchronizes) │
                            └────────┬────────┘
                                     │
                                     ├─→ Network clients (separate devices)
                                     │
                                     ├─→ Local snapclient (integrated)
                                     │   │
                                     │   ↓
                                     │   ALSA hw:Headphones
                                     │   │
                                     │   ↓
                                     │   🔊 Raspberry Pi 3.5mm Jack
                                     │   │
                                     │   ↓
                                     └──→ Speakers/Headphones
```

### Audio Synchronization

Snapcast achieves **sample-accurate** synchronization across all clients:
1. Server timestamps each audio chunk
2. Clients buffer audio and play at the exact timestamp
3. Network latency is compensated automatically
4. Typical sync accuracy: < 1ms between clients

### Metadata Flow

```
AirPlay Device (iOS/macOS)
     │
     ├─→ Cover Art → Shairport-Sync → /tmp/shairport-sync/.cache/coverart/cover-XXXXX.jpg
     │                                                        │
     │                                                        ↓
     └─→ Track Info → Shairport-Sync → Metadata Pipe (/tmp/shairport-sync-metadata)
                                                        │
                                                        ↓
                                        airplay-control-script.py (Python)
                                                        │
                                        ┌───────────────┼───────────────┐
                                        │               │               │
                                    Read Cache      Parse Metadata   Track State
                                        │               │               │
                                        ├───────────────┴───────────────┤
                                        │                               │
                                    Base64 Encode                   Bundle Data
                                        │                               │
                                        └───────────┬───────────────────┘
                                                    ↓
                                        Snapcast Stream Properties
                                        (artUrl, title, artist, album, playbackStatus)
                                                    │
                                                    ↓
                                        WebSocket → Frontend (React)
                                                    │
                                                    ↓
                                            User sees Now Playing
                                            (with album artwork)
```

**Event Timeline** (pause-then-skip scenario):
1. User pauses playback → `pfls` event → State: Paused
2. User skips track → `mper` event (new track ID) → Clear metadata
3. `mdst`...`mden` bundle → Title/Artist/Album arrive
4. Playback resumes → `prsm` event → State: Playing
5. AirPlay sends artwork → `pcst`...`pcen` bundle → Artwork loaded (1-10s delay)
6. Frontend retry mechanism finds artwork → Display updates

## 13. Dynamic Stream Lifecycle Management

**Purpose**: Dynamically create and remove Snapcast streams based on integration activity, reducing resource usage and UI clutter while maintaining service discoverability.

### 13.1. Overview

All audio integrations (AirPlay, Bluetooth, Spotify, DLNA, Plexamp) use a dynamic stream lifecycle framework that creates Snapcast streams only when the integration is actively playing audio.

**Key Principles**:
- **Always Discoverable**: Audio services run continuously (AirPlay visible, Bluetooth pairable, etc.)
- **Dynamic Streams**: Snapcast streams created only when active, removed after idle timeout
- **FIFO Management**: FIFO keepers prevent audio service blocking when no stream exists
- **Resource Efficiency**: Control scripts spawn only when streams exist, automatic cleanup

### 13.2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Audio Source (iOS/Android/Desktop)                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Audio Service (shairport-sync/bluealsa/spotifyd/etc.)      │
│  - Runs continuously (always discoverable)                  │
│  - Outputs to FIFO pipe                                     │
│  - Sends metadata to metadata pipe/D-Bus                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
┌────────────────┐      ┌────────────────────┐
│  FIFO Keeper   │      │  Stream Lifecycle  │
│  (idle state)  │      │  Manager           │
│                │◄─────┤                    │
│  Reads FIFO to │      │  Monitors:         │
│  prevent block │      │  - Metadata        │
└────────────────┘      │  - Events/D-Bus    │
                        │  - Activity        │
                        └────────┬───────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
  CREATE STREAM            MONITOR STATE            DELETE STREAM
  - Stream.AddStream       - Activity events        - Stream.RemoveStream
  - Launch control         - Client count           - Kill control
    script                 - Idle timeout             script
        │                        │                        │
        └────────────────────────┼────────────────────────┘
                                 ▼
                        ┌─────────────────┐
                        │  Snapcast       │
                        │  Server         │
                        │  (distributes)  │
                        └─────────────────┘
```

### 13.3. State Machine

Each integration transitions through three states:

```
┌──────────┐
│   IDLE   │ (No stream, FIFO keeper active, service discoverable)
└─────┬────┘
      │
      │ Activity detected (metadata, connection, playback start)
      ▼
┌──────────┐
│  ACTIVE  │ (Stream exists, control script running, audio flowing)
└─────┬────┘
      │
      │ Idle detected (timeout after disconnect/pause/stop)
      ▼
┌──────────┐
│ REMOVING │ (Cleanup in progress, kill control script)
└─────┬────┘
      │
      │ Cleanup complete
      ▼
┌──────────┐
│   IDLE   │
└──────────┘
```

### 13.4. Components

#### Lifecycle Managers
Each integration has a dedicated lifecycle manager script:

- **`stream-lifecycle-manager.py`** (AirPlay): Monitors shairport-sync metadata pipe for `pbeg`/`pend` events
- **`bluetooth-stream-lifecycle-manager.py`** (Bluetooth): Monitors BlueZ D-Bus for A2DP device connections
- **`spotify-stream-lifecycle-manager.py`** (Spotify): Monitors spotifyd D-Bus MPRIS for playback state changes
- **`dlna-stream-lifecycle-manager.py`** (DLNA): Monitors gmrender-resurrect playback state
- **`plexamp-stream-lifecycle-manager.py`** (Plexamp): Monitors PlayQueue.json file modifications

**Responsibilities**:
- Monitor integration-specific activity indicators
- Create Snapcast stream when activity detected (via `Stream.AddStream` JSON-RPC)
- Monitor stream state and client connections
- Remove stream after idle timeout (via `Stream.RemoveStream`)
- Clean up orphaned control script processes
- Coordinate with FIFO keeper

#### FIFO Keepers
Each integration has a FIFO keeper that prevents audio service blocking:

- **`fifo-keeper.sh`** (AirPlay `/tmp/snapfifo`)
- **`bluetooth-fifo-keeper.sh`** (Bluetooth `/tmp/bluetooth-fifo`)
- **`spotify-fifo-keeper.sh`** (Spotify `/tmp/spotify-fifo`)
- **`dlna-fifo-keeper.sh`** (DLNA `/tmp/dlna-fifo`)

**Operation**:
1. Check if Snapcast stream exists (query server status)
2. If stream doesn't exist: Read and discard FIFO data to prevent blocking
3. If stream exists: Sleep (Snapcast is reading FIFO)
4. Repeat every 1 second

**Why This Works**:
- Audio services write to FIFO continuously
- Without a reader, the service blocks on `write()`
- FIFO keeper provides a "dummy reader" when no stream exists
- When stream is created, Snapcast becomes the primary reader

### 13.5. Integration-Specific Implementations

#### AirPlay (Shairport-Sync)
- **Activity Trigger**: MQTT `active_start` or metadata activity
- **Idle Trigger**: MQTT `active_end` + idle timeout, or signal file mtime change
- **Metadata Source**: MQTT broker (`localhost:1883`) for real-time updates
- **Disconnect Detection**: MQTT activity monitor distinguishes pause (activity continues) from disconnect (no activity for 15s)
- **Signal File**: `/tmp/airplay-{id}-stream-end.signal` - mtime change triggers disconnect check
- **Multi-Instance**: Each endpoint has separate lifecycle manager, signal file, and MQTT topics

#### Bluetooth (BlueZ + bluez-alsa)
- **Activity Trigger**: BlueZ Device1 `Connected=true` + A2DP profile
- **Idle Trigger**: Device disconnect + 10s timeout
- **Metadata Source**: BlueZ AVRCP via D-Bus
- **Disconnect**: D-Bus property change → immediate removal

#### Spotify (Spotifyd)
- **Activity Trigger**: MPRIS `PlaybackStatus=Playing`
- **Idle Trigger**: `PlaybackStatus=Stopped` + 10s timeout
- **Metadata Source**: D-Bus MPRIS interface
- **Disconnect**: Spotifyd disconnect → immediate removal

#### DLNA/UPnP (gmrender-resurrect)
- **Activity Trigger**: GStreamer playback state change to PLAYING
- **Idle Trigger**: State STOPPED + 10s timeout
- **Metadata Source**: UPnP AVTransport service
- **Disconnect**: Renderer stop → removal after timeout

#### Plexamp
- **Activity Trigger**: PlayQueue.json modification with playback state
- **Idle Trigger**: Empty queue or stopped + 30s timeout
- **Metadata Source**: PlayQueue.json file monitoring
- **Disconnect**: Queue empty → removal after timeout

### 13.6. Benefits

1. **Reduced Clutter**: Streams only appear in UI when actively playing
2. **Resource Efficiency**: Control scripts only run when needed (~50MB memory saved per idle integration)
3. **Always Discoverable**: Services remain visible on network even when stream doesn't exist
4. **Smart Cleanup**: Orphaned processes automatically cleaned up
5. **Graceful Handling**: Idle timeouts prevent premature removal during pauses
6. **No User Impact**: Stream creation/removal is seamless, no user intervention required

### 13.7. Configuration

**Idle Timeouts** (hardcoded in lifecycle managers):
- AirPlay: 10 seconds
- Bluetooth: 10 seconds
- Spotify: 10 seconds
- DLNA: 10 seconds
- Plexamp: 30 seconds (longer timeout for queue navigation)

**Supervisord Priority** (start order):
- Priority 20: FIFO keepers (start before lifecycle managers)
- Priority 25: Lifecycle managers (start after FIFO keepers, before other services)

### 13.8. Edge Cases Handled

1. **Control Script Missing Initial Metadata**: Control script may miss first metadata bundle if spawned after activity start. Solution: Cached metadata reload on `mden` events (AirPlay).

2. **Orphaned Control Scripts**: If stream removal fails, control script process remains. Solution: Lifecycle manager performs cleanup on startup and before removal.

3. **Race Condition (Creation During Removal)**: Activity detected while stream is being removed. Solution: State machine prevents creation when state is `REMOVING`.

4. **FIFO Keeper vs Snapcast Race**: Both try to read FIFO simultaneously. Solution: FIFO keeper checks for stream existence before reading.

5. **Same-Album Artwork Not Updating**: Shairport-sync doesn't resend artwork for tracks from same album. Solution: Control script checks cache on every `mden` event (AirPlay).

### 13.9. Troubleshooting

**Stream Not Creating**:
```bash
# Check lifecycle manager status
docker exec plum-snapcast-server supervisorctl status | grep lifecycle

# View lifecycle manager logs
docker exec plum-snapcast-server tail -f /var/log/supervisord/stream-lifecycle-manager_err.log

# Test metadata flow (AirPlay example)
docker exec plum-snapcast-server cat /tmp/shairport-sync-metadata | head -20
```

**Stream Not Deleting**:
```bash
# Check for orphaned control scripts
docker exec plum-snapcast-server ps aux | grep control-script

# Manually remove stream
docker exec plum-snapcast-server python3 -c "
import socket, json
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('localhost', 1704))
req = json.dumps({'jsonrpc':'2.0','method':'Stream.RemoveStream','params':{'id':'AirPlay'},'id':1})
sock.sendall((req + '\r\n').encode())
print(sock.recv(4096).decode())
"
```

**FIFO Blocking Issues**:
```bash
# Check FIFO keeper status
docker exec plum-snapcast-server supervisorctl status | grep fifo-keeper

# Manually drain FIFO
docker exec plum-snapcast-server timeout 1 cat /tmp/snapfifo > /dev/null || true
```

### 13.10. Future Enhancements

- **Gradual Idle Timeout**: Longer timeout if clients are connected to stream
- **Pre-warming**: Create stream on service startup to reduce first-connection latency
- **Multi-FIFO Support**: Single keeper script managing multiple FIFOs
- **HTTP API**: REST endpoints to manually force stream creation/deletion for testing

## 14. Critical Architectural Decisions

### Decision 1: Dynamic Stream Lifecycle Management

**Context**: Traditional deployments create static Snapcast streams at container startup that exist whether or not the source is active.

**Decision**: Implement dynamic stream lifecycle management for all audio integrations.

**Rationale**:
- Reduces UI clutter - streams only visible when actively playing
- Saves resources - control scripts only run when needed
- Maintains discoverability - services remain visible on network
- Improves user experience - cleaner interface, automatic cleanup

**Consequences**:
- ✅ Cleaner UI (no empty streams)
- ✅ Reduced resource usage (~50MB per idle integration)
- ✅ Services always discoverable (AirPlay visible, Bluetooth pairable)
- ✅ Automatic cleanup of orphaned processes
- ❌ Added complexity (lifecycle managers + FIFO keepers)
- ❌ Potential edge cases with rapid connect/disconnect
- ❌ Slight delay on first connection (stream creation time)

**Implementation**: Each integration has a lifecycle manager monitoring activity and a FIFO keeper preventing blocking. See Section 13 for details.

### Decision 2: Integrated Snapclient

**Context**: Traditional Snapcast deployments separate server and clients across different devices.

**Decision**: Include snapclient in the same container as snapserver.

**Rationale**:
- Simplifies single-device deployments (Raspberry Pi as standalone unit)
- Reduces network latency for local output
- Easier setup for non-technical users
- Fewer containers to manage

**Consequences**:
- ✅ Simpler deployment
- ✅ Lower latency for local output
- ❌ Limits multi-room expansion (requires additional client devices)
- ❌ Server and client share resources

**Future Consideration**: Make snapclient optional for pure server-only deployments.

### Decision 3: Host Network Mode

**Context**: AirPlay discovery requires mDNS (multicast DNS) for device visibility.

**Decision**: Use `network_mode: host` for backend container.

**Rationale**:
- mDNS multicast requires host network stack
- Avahi service discovery needs direct network access
- Bridge networking breaks mDNS multicast packets
- Simpler than mDNS reflectors or macvlan networks

**Consequences**:
- ✅ AirPlay discovery works reliably
- ✅ No complex networking configuration
- ❌ Container exposes all ports directly on host
- ❌ Reduced network isolation
- ❌ Potential port conflicts

**Mitigation**: Firewall rules on host to limit exposure.

### Decision 4: Host D-Bus + Container Avahi

**Context**: Both D-Bus and Avahi are required for AirPlay, and running both in the container caused conflicts.

**Decision**: Use host's D-Bus socket, run Avahi in container.

**Rationale**:
- Avoids D-Bus socket permission issues
- Leverages host's properly configured D-Bus
- Container Avahi has full control over service registration
- Eliminates duplicate D-Bus instances

**Consequences**:
- ✅ Reliable AirPlay service discovery
- ✅ No permission issues
- ✅ Simpler container configuration
- ❌ Requires host D-Bus to be running
- ❌ Host Avahi must be disabled
- ❌ Volume mount required for D-Bus socket

**Setup Requirement**: One-time host configuration (disable Avahi, ensure D-Bus is running).

### Decision 5: React with Custom CSS vs UI Framework

**Context**: Frontend needed to be lightweight, fast, and customizable.

**Decision**: Use React with custom CSS and CSS variables for theming.

**Rationale**:
- Full control over styling
- No framework bloat
- Fast load times
- Easy theme customization via CSS variables
- No learning curve for CSS framework

**Consequences**:
- ✅ Lightweight bundle size
- ✅ Full styling control
- ✅ Fast initial load
- ❌ More CSS to write manually
- ❌ No pre-built components

### Decision 6: Album Artwork via Stream Properties

**Context**: Snapcast's control script can set custom stream properties, which are transmitted to clients via WebSocket.

**Decision**: Base64-encode artwork and embed in Snapcast stream properties.

**Rationale**:
- Control scripts can set arbitrary stream properties (no filtering)
- Properties are automatically sent to WebSocket clients
- No need for separate HTTP endpoints or file serving
- Artwork data travels through same channel as other metadata
- Frontend receives everything in one JSON payload

**Consequences**:
- ✅ Simple architecture - single data channel
- ✅ No CORS issues or proxy configuration
- ✅ Artwork arrives automatically via WebSocket
- ❌ Large base64 payloads (~50-200KB per artwork)
- ❌ Must write artwork to disk first (shairport-sync limitation)
- ❌ Requires cache directory to exist on startup

**Implementation**:
- `backend/scripts/setup.sh` - Creates `/tmp/shairport-sync/.cache/coverart/`
- `backend/scripts/airplay-control-script.py` - Loads, encodes, and embeds artwork
- `frontend/App.tsx` - Receives artwork via WebSocket, displays in `<img src="data:image/jpeg;base64,..."/>`

**Critical Bugs Fixed** (2025-11-17):
1. **Missing cache directory**: Setup script didn't create artwork directory, causing all artwork to fail silently
2. **Race condition**: Artwork loaded then immediately cleared by track change event - fixed with 2-second grace period

## 15. Performance Characteristics

**Audio Latency**:
- AirPlay to Snapcast: ~50-100ms
- Snapcast server to client: <10ms
- Total system latency: ~60-110ms

**Synchronization Accuracy**:
- Between clients: <1ms (sample-accurate)
- Network jitter compensation: Automatic

**Resource Usage** (Raspberry Pi 4):
- CPU: 5-15% during playback
- Memory: ~150MB (backend container)
- Memory: ~50MB (frontend container)
- Network: Minimal (compressed audio streams)

**Scalability**:
- Clients per server: Tested up to 10+ clients
- Streams per server: Up to 5 simultaneous streams
- Bottleneck: Network bandwidth for large deployments

## 16. Troubleshooting Architecture

**Log Locations**:
- Supervisord main log: `/app/config/supervisord.log` (in container)
- Docker logs: `docker logs plum-snapcast-server`
- Frontend logs: Browser console

**Common Issues**:
1. **AirPlay not visible**: Avahi not running or host Avahi conflicting
2. **No audio output**: Snapclient not running or audio device permissions
3. **Artwork not loading**: Cache directory missing or permissions incorrect
4. **Artwork flashes then disappears**: Race condition between artwork load and track change
5. **Metadata not updating**: Control script errors or metadata pipe issues
6. **Desynchronization**: Network latency too high, buffer adjustment needed

**Artwork Troubleshooting**:
```bash
# Check if cache directory exists
docker exec plum-snapcast-server ls -la /tmp/shairport-sync/.cache/coverart/

# Check if artwork files are being written
docker exec plum-snapcast-server ls -lht /tmp/shairport-sync/.cache/coverart/ | head -5

# Check control script logs
docker logs plum-snapcast-server 2>&1 | grep -i "artwork\|track"

# Enable detailed frontend logging
# Browser console will show: [ArtworkRetry], [Metadata], [Polling] logs
```

**Diagnostic Commands**: See [QUICK-REFERENCE.md](QUICK-REFERENCE.md#troubleshooting)

---

**Document Maintenance**: This architecture document should be updated whenever:
- Major component changes
- New services added
- Architectural decisions made
- Performance characteristics change
- Security considerations evolve

**Last Reviewed**: 2025-12-31
