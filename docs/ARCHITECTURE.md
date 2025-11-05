# Architecture Overview

This document provides a comprehensive understanding of the Plum-Snapcast codebase architecture, enabling efficient navigation and effective contribution from day one. This document is actively maintained as the codebase evolves.

## 1. Project Structure

The project follows a clean separation of concerns with distinct directories for backend services, frontend application, Docker orchestration, documentation, and development resources.

```
Plum-Snapcast/
├── backend/                    # Snapcast server container (Alpine Linux)
│   ├── Dockerfile              # Multi-arch build configuration
│   ├── README.md              # Backend-specific documentation
│   ├── config/                # Service configurations
│   │   ├── supervisord/       # Process management configs
│   │   │   ├── supervisord.conf     # Main supervisor config
│   │   │   ├── snapcast.ini         # Snapcast services config
│   │   │   └── snapclient.ini       # Audio output client config
│   │   └── shairport-sync.conf      # AirPlay receiver config
│   └── scripts/               # Container initialization scripts
│       ├── setup.sh           # Container startup script
│       └── process-airplay-metadata.sh  # AirPlay metadata handler
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
│   │   └── snapcastDataService.ts    # Data transformation
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
│   ├── QUICK-REFERENCE.md   # Quick reference guide
│   └── original/            # Legacy documentation
├── _resources/              # Development references (NOT in git)
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
┌───────────────────────────────────────────────────────────────────┐
│                         Host Network                               │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Backend Container (network_mode: host)                  │   │
│  │  ┌────────────┐  ┌─────────────┐  ┌──────────────┐     │   │
│  │  │  Snapcast  │  │  Shairport  │  │   Librespot  │     │   │
│  │  │  Server    │←─│  -Sync      │  │   (Spotify)  │     │   │
│  │  │:1704-1705  │  │  (AirPlay)  │  │              │     │   │
│  │  └─────┬──────┘  └─────────────┘  └──────────────┘     │   │
│  │        │                                                 │   │
│  │        │         ┌──────────────┐                       │   │
│  │        └────────→│  Snapclient  │──→ 🔊 Audio Output   │   │
│  │                  │  (Integrated)│                       │   │
│  │                  └──────────────┘                       │   │
│  │                                                          │   │
│  │  ┌─────────────┐  ┌─────────────┐                      │   │
│  │  │   Avahi     │  │    D-Bus    │                      │   │
│  │  │  (mDNS)     │  │   System    │                      │   │
│  │  └─────────────┘  └─────────────┘                      │   │
│  │                                                          │   │
│  │  Managed by Supervisord                                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Frontend Container                                      │   │
│  │  Nginx serving React app on :3000                       │   │
│  │  WebSocket client connects to :1704                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
         ↑                                              ↑
    AirPlay from                                  Browser access
    iOS/macOS                                http://localhost:3000
         ↓
    Spotify App
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

**Name**: AirPlay Audio Receiver

**Description**: Receives AirPlay and AirPlay 2 audio streams from iOS/macOS devices and pipes them into Snapcast for synchronized multi-room playback. Includes custom metadata processing for album art and track information.

**Technologies**:
- Shairport-Sync (latest from Alpine repositories)
- D-Bus for inter-process communication
- Avahi for mDNS service discovery
- Custom shell script for metadata processing

**Deployment**: Managed by Supervisord in backend container

**Ports**:
- 3689: AirPlay control
- 5000: AirPlay Classic/1 streaming
- 6000-6009/udp: AirPlay audio streaming
- 7000: AirPlay 2 streaming (in airplay2 builds)
- 319-320/udp: NQPTP for AirPlay 2

#### 3.2.4. Librespot (Spotify Connect)

**Name**: Spotify Connect Endpoint

**Description**: Optional service that makes the system appear as a Spotify Connect device, allowing users to cast audio from the Spotify app directly to the multi-room audio system.

**Technologies**:
- Librespot (open-source Spotify Connect client)
- Configured to output to Snapcast FIFO pipe

**Deployment**: Optional, enabled via environment variable

#### 3.2.5. Service Discovery (Avahi + D-Bus)

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

**Type**: Temporary files in `/tmp` and `/usr/share/snapserver/snapweb`

**Purpose**: Stores album artwork and metadata for display in web interface

**Key Files**:
- `/tmp/coverart.jpg` - Current track artwork
- `/usr/share/snapserver/snapweb/airplay-artwork.json` - Artwork metadata
- `/usr/share/snapserver/snapweb/coverart/*.jpg` - Cached artwork

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

**Date of Last Update**: 2025-11-04

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
AirPlay Device
     │
     ├─→ Cover Art → Shairport-Sync → /tmp/coverart.jpg
     │
     └─→ Track Info → Shairport-Sync → process-airplay-metadata.sh
                                               │
                                               ├─→ Saves artwork to snapweb/
                                               └─→ Writes airplay-artwork.json
                                                        │
                                                        ↓
                                                Frontend (via nginx proxy)
                                                        │
                                                        ↓
                                                User sees Now Playing
```

## 13. Critical Architectural Decisions

### Decision 1: Integrated Snapclient

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

### Decision 2: Host Network Mode

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

### Decision 3: Host D-Bus + Container Avahi

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

### Decision 4: React with Custom CSS vs UI Framework

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

### Decision 5: Album Artwork Workaround

**Context**: Snapcast's plugin system filters out custom metadata fields, preventing direct artwork URLs.

**Decision**: Save artwork to snapweb directory and expose via nginx proxy.

**Rationale**:
- Snapcast web directory is already served by snapserver
- Frontend container can proxy to snapserver for artwork
- Avoids CORS issues
- Works around Snapcast metadata limitations

**Consequences**:
- ✅ Artwork displays correctly
- ✅ No CORS issues
- ❌ Requires nginx proxy configuration
- ❌ Artwork must be written to disk
- ❌ Requires coordination between backend script and frontend

**Implementation**: See `backend/scripts/process-airplay-metadata.sh` and frontend nginx config.

## 14. Performance Characteristics

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

## 15. Troubleshooting Architecture

**Log Locations**:
- Supervisord main log: `/app/config/supervisord.log` (in container)
- Docker logs: `docker logs plum-snapcast-server`
- Frontend logs: Browser console

**Common Issues**:
1. **AirPlay not visible**: Avahi not running or host Avahi conflicting
2. **No audio output**: Snapclient not running or audio device permissions
3. **Metadata not updating**: Metadata processing script errors
4. **Desynchronization**: Network latency too high, buffer adjustment needed

**Diagnostic Commands**: See [QUICK-REFERENCE.md](QUICK-REFERENCE.md#troubleshooting)

---

**Document Maintenance**: This architecture document should be updated whenever:
- Major component changes
- New services added
- Architectural decisions made
- Performance characteristics change
- Security considerations evolve

**Last Reviewed**: 2025-11-04
