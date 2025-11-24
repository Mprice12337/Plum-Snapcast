# CLAUDE.md - Plum-Snapcast

> **Purpose**: This file serves as your project's memory for Claude Code. It defines rules, workflows, and preferences that Claude will automatically follow when working on the Plum-Snapcast codebase.

## Project Overview

**Plum-Snapcast** is a multi-room audio streaming solution combining Snapcast server backend with React/TypeScript frontend. Enables synchronized audio playback with AirPlay, Spotify Connect, DLNA/UPnP, Plexamp, and Bluetooth sources.

**Key Features**: Multi-room sync, integrated snapclient (RPi 3.5mm output), React web UI, WebSocket (JSON-RPC 2.0), real-time metadata with album art, volume control

**Project Context**: Production-ready, solo developer with AI assistance, built on firefrei/docker-snapcast foundation

---

## Claude Code Preferences

- **Model**: Sonnet (daily work) / Opus (complex architecture)
- **Planning**: Complex multi-step tasks only
- **Communication**: Concise - explain major changes, skip obvious details
- **Task Management**: Auto-generate to-do lists for complex tasks, use subagents for exploration
- **Testing**: Manual integration testing on Raspberry Pi hardware

---

## Technology Stack

### Backend
- **Base**: Alpine Linux Docker container, multi-arch (amd64, arm64)
- **Audio**: Snapcast server/client, Shairport-Sync (AirPlay 1/2), BlueZ+bluez-alsa (Bluetooth A2DP), Spotifyd (Spotify Connect), gmrender-resurrect (DLNA/UPnP), Plexamp (Plex via Debian sidecar)
- **Infrastructure**: Supervisord (process mgmt), Avahi (mDNS), D-Bus (IPC), HTTPS with auto-cert generation
- **Security**: Rootless container (user: snapcast, UID 1000, GID 29 audio)

### Frontend
- React 19.1.1, TypeScript 5.8.2, Vite 6.2.0
- Custom CSS with variables, WebSocket JSON-RPC 2.0
- Components: NowPlaying, PlayerControls, StreamSelector, ClientManager, Settings
- Services: snapcastService.ts (WebSocket client), snapcastDataService.ts (data transforms)

### Infrastructure
- Docker multi-arch builds (amd64, arm64), Docker Hub registry
- Target: Raspberry Pi 3+ with RPi OS Lite (64-bit), host networking mode

---

## Project Structure

```
├── _resources/          # Dev references (NOT in git)
├── docs/                # Project documentation
│   ├── ARCHITECTURE.md
│   ├── CLAUDE.md        # This file (symlinked to root)
│   ├── DEV-SETUP.md
│   └── QUICK-REFERENCE.md
├── backend/
│   ├── Dockerfile
│   ├── config/          # shairport-sync.conf, snapserver.conf.template
│   ├── scripts/         # entrypoint.sh, generate-config.sh, metadata processors
│   └── supervisord/     # Process configs (.ini files)
├── frontend/
│   ├── src/
│   │   ├── components/  # NowPlaying, PlayerControls, etc.
│   │   ├── services/    # snapcastService, snapcastDataService
│   │   ├── hooks/       # useAudioSync
│   │   └── types.ts
│   ├── vite.config.ts
│   └── Dockerfile
├── docker/
│   ├── docker-compose.yml
│   ├── .env.example
│   └── build-and-push.sh
└── scripts/
    └── setup-audio.sh
```

**Special Directories**:
- `_resources/`: Dev templates and research (NEVER committed to git)
- `docs/`: All documentation except README.md

---

## Core Architecture

### Audio Pipeline
```
Source (AirPlay/Bluetooth/Spotify/DLNA/Plexamp)
  ↓
Audio Service (shairport-sync/bluealsa/spotifyd/gmrender/plexamp)
  ↓
FIFO Pipe (/tmp/*-fifo)
  ↓
Snapserver (distribution + sync)
  ↓
Snapclient (integrated, hw:Headphones)
  ↓
Speakers (RPi 3.5mm jack)
```

All services run in single Alpine container (supervisord). Plexamp runs in optional Debian sidecar (glibc requirement).

### Container Architecture Pattern

**Hybrid: Alpine Primary + Debian Sidecar (Optional)**

1. **Alpine Container (plum-snapcast-server)**: All core services, container D-Bus, container Avahi
2. **Debian Container (plum-plexamp)**: Optional (only when `PLEXAMP_ENABLED=1`), runs Plexamp headless, shared FIFO volume
3. **Host**: Docker + audio device access, host Avahi disabled, no D-Bus config needed

**Why**: Preserves Alpine benefits, adds glibc only where needed, optional sidecar

### Design Patterns
- Single container with supervised processes
- JSON-RPC 2.0 over WebSocket
- FIFO pipes for audio transport
- React component composition with hooks
- Client-side audio progress prediction (useAudioSync)

**Metadata Flow**: Source → Service → JSON files/D-Bus → Control script → Snapcast properties → WebSocket → Frontend

---

## Development Workflow

### Git Strategy
- **Main Branch**: `main` (protected)
- **Branch Naming**: `feature/*`, `bugfix/*`, `docs/*`, `refactor/*`
- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `build:`, `ci:`)
- **Best Practices**: `git pull --rebase`, atomic commits, never force push to main

### Code Quality
- **Linting**: ESLint (TypeScript), shellcheck (shell scripts)
- **Formatting**: Prettier (TypeScript)
- **Style**: 2 spaces (TS/JS), 4 spaces (shell), 120 char max
- **Naming**:
  - Components: `PascalCase.tsx` (NowPlaying.tsx)
  - Services: `camelCase.ts` (snapcastService.ts)
  - Variables/Functions: `camelCase`
  - Constants/Env Vars: `UPPER_SNAKE_CASE`

---

## Environment Configuration

### Key Environment Variables

**Audio Sources** (see docker/.env.example for full list):
- `AIRPLAY_CONFIG_ENABLED`, `AIRPLAY_DEVICE_NAME` (default: "Plum Audio")
- `BLUETOOTH_ENABLED`, `BLUETOOTH_DEVICE_NAME`, `BLUETOOTH_AUTO_PAIR` (default: 0, auto-accept SSP)
- `SPOTIFY_CONFIG_ENABLED`, `SPOTIFY_DEVICE_NAME`, `SPOTIFY_BITRATE` (default: 320)
- `DLNA_ENABLED`, `DLNA_DEVICE_NAME`
- `PLEXAMP_ENABLED`, `PLEXAMP_CLAIM_TOKEN` (from https://plex.tv/claim), `PLEXAMP_SERVER_NAME`

**Snapclient**:
- `SNAPCLIENT_ENABLED`, `SNAPCLIENT_SOUNDCARD` (default: hw:Headphones), `SNAPCLIENT_LATENCY`

**Network**:
- `HTTPS_ENABLED` (default: 1), `FRONTEND_PORT` (default: 3000)

**Important Implementation Notes**:
- **Bluetooth**: No album art (needs BlueZ 5.81+, Alpine has 5.70). SSP only (no PIN codes). Metadata via AVRCP.
- **Spotify**: Uses spotifyd (not librespot) for D-Bus MPRIS. Patched with-avahi to avoid port conflicts. Album art cached to `/usr/share/snapserver/snapweb/coverart/`
- **DLNA/UPnP**: gmrender-resurrect, GStreamer pipeline to 44.1kHz/16-bit stereo. Metadata from UPnP AVTransport.
- **Plexamp**: Separate Debian container (glibc). Monitors PlayQueue.json for metadata. HTTP API for controls at localhost:32500. S16_LE/44.1kHz/stereo conversion via ALSA. Start with `docker compose --profile plexamp up -d`

### Network Architecture

**Ports**:
- Snapcast: 1704-1705 (clients), 1780 (HTTP/WS), 1788 (HTTPS/WS)
- AirPlay: 3689, 5000, 6000-6009/udp, 5353/udp (mDNS), 7000 (AirPlay 2), 319-320/udp (NQPTP)
- Plexamp: 32500 (HTTP API)
- Frontend: 3000 (configurable)

**Requirements**: Layer 2 network for mDNS/Avahi, host networking mode, no VLANs without repeater

---

## API Documentation

### Snapcast JSON-RPC API
- **Protocol**: WebSocket + JSON-RPC 2.0
- **Endpoint**: `wss://[host]:1788/jsonrpc` (HTTPS) or `ws://[host]:1780/jsonrpc`
- **Docs**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/

**Key Methods**:
```typescript
Server.GetStatus() → { server: { streams: [], groups: [] } }
Client.SetVolume({ id: string, volume: { percent: number, muted: boolean } })
Group.SetStream({ id: string, stream_id: string })
Stream.Control({ id: string, command: "play" | "pause" | "next" | "previous" })
```

---

## Coding Conventions

### General Principles
1. Keep it simple - prefer straightforward solutions
2. Audio quality first - never compromise pipeline reliability
3. Document the why - explain architectural decisions
4. Fail gracefully - handle errors without crashing
5. Test on hardware - verify changes on actual Raspberry Pi

### Project-Specific Rules

1. **D-Bus/Avahi**: Container runs its own (self-contained, no host mounts)
2. **Audio Group GID**: Always 29 (Raspberry Pi standard)
3. **Snapclient Integration**: Runs in same container as snapserver
4. **Attribution**: Maintain CREDITS.md (firefrei/docker-snapcast, badaix/snapcast, mikebrady/shairport-sync)

### Error Handling
- **Backend**: Auto-restart via supervisord
- **Frontend**: Display errors in UI, don't crash
- **WebSocket**: Auto-reconnect with exponential backoff
- **Logging**: Use supervisord logs

### Performance
- Minimize audio latency (no transcoding)
- Poll server status every 5s max
- Use React.memo for expensive components (album art)
- Alpine + multi-stage builds for minimal image size

---

## Common Tasks

### Adding a New Audio Source
1. Update `backend/scripts/generate-config.sh`
2. Add supervisord config (if service needed)
3. Update `docker/.env.example`
4. Test: Build → Deploy to RPi → Verify in web UI

### Debugging

**Logs**:
```bash
docker logs plum-snapcast-server
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f [service]
```

**Common Issues**:
- No audio: Check `docker exec plum-snapcast-server aplay -l`
- AirPlay not visible: Verify Avahi running, host Avahi disabled
- Bluetooth not pairing: Check `bluetoothctl show`, verify `BLUETOOTH_DISCOVERABLE=1`
- D-Bus errors: Ensure host D-Bus socket mounted

---

## Deployment

### One-Time Raspberry Pi Setup
1. Install Docker: `curl -fsSL https://get.docker.com | sh`
2. Audio permissions: `echo 'SUBSYSTEM=="sound", MODE="0666"' | sudo tee /etc/udev/rules.d/99-audio-permissions.rules`
3. Disable host Avahi: `sudo systemctl disable avahi-daemon.service avahi-daemon.socket`
4. Clone, configure .env, deploy: `docker compose pull && docker compose up -d`
5. Reboot

### Updating
```bash
cd ~/Plum-Snapcast/docker
git pull && docker compose pull && docker compose up -d
```

---

## Important Development Notes

1. **Attribution**: Built on firefrei/docker-snapcast - maintain CREDITS.md
2. **Container Architecture**: Self-contained D-Bus/Avahi, works across all host OS versions
3. **WebSocket**: Check `isConnected` before requests, handle failures gracefully
4. **Stream Capabilities**: Check `stream.properties` for supported controls
5. **Volume Control**: No group volume API - adjust all clients individually
6. **Metadata**: Format varies by source, always provide fallbacks
7. **TypeScript**: Use explicit types from `types.ts`, avoid `any`
8. **Audio Device Access**: Privileged mode + udev rule + GID 29 audio group
9. **Multi-room**: Deploy additional snapclient-only containers, Layer 2 network required
10. **Bluetooth Album Art**: Not available (needs BlueZ 5.81+, Alpine has 5.70)

---

## Quick Reference

### Most Common Commands
```bash
# Development
cd frontend && npm run dev                # Dev server
cd frontend && npm run build              # Production build

# Testing
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
docker exec plum-snapcast-server aplay -l
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1

# Docker
docker compose up -d                      # Start
docker compose down                       # Stop
docker logs plum-snapcast-server          # View logs
docker exec -it plum-snapcast-server sh   # Shell access

# Build
cd docker && bash build-and-push.sh       # Multi-arch build
```

### File Locations
- Backend config: `/app/config/` (snapcast-config volume)
- Backend data: `/app/data/` (snapcast-data volume)
- Logs: `docker logs` or supervisorctl tail
- Frontend build: `frontend/dist/`
- Docs: `/docs/` (except README.md)
- Dev references: `/_resources/` (NOT in git)

---

## Resources

- **Snapcast**: https://github.com/badaix/snapcast
- **Snapcast JSON-RPC API**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/
- **Docker Snapcast**: https://github.com/firefrei/docker-snapcast
- **Shairport-Sync**: https://github.com/mikebrady/shairport-sync
- **Spotifyd**: https://github.com/Spotifyd/spotifyd

---

## Maintaining This File

**When to Update**: Major architecture changes, new audio sources, Docker/deployment changes, env var updates, new workflows
**What Not to Include**: Temporary notes (use `_resources/`), duplicate info from README/ARCHITECTURE, overly detailed API specs
**Tips**: Document WHY (not just WHAT), test command examples, keep ARCHITECTURE.md in sync
