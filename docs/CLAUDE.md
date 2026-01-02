# CLAUDE.md - Plum-Snapcast

> **Purpose**: Project memory for Claude Code. Defines rules, workflows, and preferences.

## Project Overview

**Plum-Snapcast** is a multi-room audio streaming solution combining Snapcast server backend with React/TypeScript frontend. Enables synchronized audio playback with multi-instance AirPlay (up to 10), Spotify Connect (up to 10), DLNA/UPnP (up to 10), Plexamp, and Bluetooth sources.

**Key Features**: Multi-room sync, integrated snapclient (RPi 3.5mm output), browser audio client, React web UI, WebSocket (JSON-RPC 2.0), real-time metadata with album art, volume control, full-screen audio visualizer, enhanced theming with album art color extraction

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
- React 19, TypeScript 5, Vite 6
- Custom CSS with variables, WebSocket JSON-RPC 2.0
- Dependencies: ColorThief (album art color extraction), react-colorful (custom color picker)

### Infrastructure
- Docker multi-arch builds (amd64, arm64), Docker Hub registry
- Target: Raspberry Pi 3+ with RPi OS Lite (64-bit), host networking mode

---

## Project Structure

```
├── _resources/          # Dev references (NOT in git)
├── docs/                # Project documentation
│   ├── ARCHITECTURE.md  # Detailed architecture & API specs
│   ├── CLAUDE.md        # This file (symlinked to root)
│   ├── DEV-SETUP.md
│   └── QUICK-REFERENCE.md
├── backend/
│   ├── Dockerfile
│   ├── config/          # shairport-sync.conf, snapserver.conf.template
│   ├── scripts/         # entrypoint.sh, setup scripts, API servers, lifecycle managers
│   └── supervisord/     # Process configs (.ini files)
├── frontend/
│   ├── src/
│   │   ├── components/  # NowPlaying, PlayerControls, Settings, Visualizer, etc.
│   │   ├── services/    # snapcastService, snapcastDataService
│   │   ├── hooks/       # useAudioSync, useBrowserAudio
│   │   └── types.ts
│   └── Dockerfile
└── docker/
    ├── docker-compose.yml
    └── build-and-push.sh
```

**Special Directories**:
- `_resources/`: Dev templates and research (NEVER committed to git)
- `docs/`: All documentation except README.md

---

## Core Architecture

### Audio Pipeline
```
Source (AirPlay/Bluetooth/Spotify/DLNA/Plexamp)
  → Audio Service (shairport-sync/bluealsa/spotifyd/gmrender/plexamp)
  → FIFO Pipe (/tmp/*-fifo)
  → Snapserver (distribution + sync)
  → Snapclient (integrated, hw:Headphones)
  → Speakers (RPi 3.5mm jack)
```

All services run in single Alpine container (supervisord). Plexamp runs in optional Debian sidecar (glibc requirement).

### Key Design Patterns
- **JSON-RPC 2.0 over WebSocket**: Snapcast control
- **REST APIs (Flask)**: Settings, integrations, audio config, playback position
- **FIFO pipes**: Audio transport between services
- **Dynamic stream lifecycle**: Services run continuously (discoverable), streams created/removed based on activity
- **Settings persistence**: `/app/data/settings.json` for all configuration

### Data Flows
- **Metadata**: Source → Service → JSON/D-Bus → Control script → Snapcast properties → WebSocket → Frontend
- **Settings**: Frontend → settingsService → settings_api.py → settings.json
- **Integration Control**: Frontend → integrationsService → integrations_api.py → supervisorctl

> **Detailed API specs**: See `docs/ARCHITECTURE.md`

---

## Development Workflow

### Git Strategy
- **Main Branch**: `main` (protected)
- **Branch Naming**: `feature/*`, `bugfix/*`, `docs/*`, `refactor/*`
- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`)
- **Best Practices**: `git pull --rebase`, atomic commits, never force push to main

### Code Quality
- **Linting**: ESLint (TypeScript), shellcheck (shell scripts)
- **Formatting**: Prettier (TypeScript)
- **Style**: 2 spaces (TS/JS), 4 spaces (shell), 120 char max
- **Naming**: Components `PascalCase.tsx`, Services `camelCase.ts`, Variables/Functions `camelCase`, Constants `UPPER_SNAKE_CASE`

---

## Environment Configuration

### Integration Settings (AirPlay, Bluetooth, Spotify, DLNA)
- **Managed via Web UI**: Settings → Integrations (no env vars needed)
- **Storage**: `/app/data/settings.json` (Docker volume)
- **Defaults**: AirPlay enabled ("Plum Audio"), all others disabled

### Container-Level Settings (env vars)
- **Plexamp**: `PLEXAMP_ENABLED`, `PLEXAMP_CLAIM_TOKEN`, `PLEXAMP_SERVER_NAME`
- **Snapclient**: `SNAPCLIENT_ENABLED`, `SNAPCLIENT_LATENCY`
- **Network**: `HTTPS_ENABLED` (default: 1), `FRONTEND_PORT` (default: 3000)

### Key Ports
- Snapcast: 1704-1705 (clients), 1780 (HTTP/WS), 1788 (HTTPS/WS)
- AirPlay: 5050-5059 (up to 10 endpoints), 5353/udp (mDNS), UDP 6001-6100
- Spotify Connect: 5354-5363 (zeroconf ports, up to 10 endpoints)
- DLNA/UPnP: 49494-49503 (UPnP ports, up to 10 endpoints)
- Internal APIs: 5001-5004 (Federation, Settings, Integrations, Audio)
- Frontend: 3000

**Requirements**: Layer 2 network for mDNS/Avahi, host networking mode

---

## Integration Notes

| Integration | Key Details |
|-------------|-------------|
| **AirPlay** | Multi-instance (up to 10 endpoints), MQTT metadata, dynamic stream lifecycle, control script wrapper pattern |
| **Bluetooth** | No album art (BlueZ 5.70 < 5.81 required), SSP only (no PIN), AVRCP metadata |
| **Spotify** | Multi-instance (up to 10 endpoints), spotifyd (not librespot) for D-Bus MPRIS, patched with-avahi |
| **DLNA/UPnP** | Multi-instance (up to 10 endpoints), gmrender-resurrect, GStreamer 44.1kHz/16-bit, UPnP AVTransport metadata |
| **Plexamp** | Separate Debian container, PlayQueue.json metadata, pinned v4.11.3 (4.12.x buggy) |

---

## Coding Conventions

### General Principles
1. Keep it simple - prefer straightforward solutions
2. Audio quality first - never compromise pipeline reliability
3. Document the why - explain architectural decisions
4. Fail gracefully - handle errors without crashing
5. Test on hardware - verify changes on actual Raspberry Pi

### Project-Specific Rules
- **D-Bus/Avahi**: Container runs its own (self-contained, no host mounts)
- **Audio Group GID**: Always 29 (Raspberry Pi standard)
- **Attribution**: Maintain CREDITS.md
- **WebSocket**: Check `isConnected` before requests, handle failures gracefully
- **TypeScript**: Use explicit types from `types.ts`, avoid `any`
- **Icons**: Local SVG icons (not Font Awesome) - add to `frontend/src/assets/icons/`

### Error Handling
- **Backend**: Auto-restart via supervisord
- **Frontend**: Display errors in UI, don't crash
- **WebSocket**: Auto-reconnect with exponential backoff

---

## Common Tasks

### Adding a New Audio Source
1. Add settings schema to `migrate-env-to-settings.py`
2. Update `get-settings.py` to export settings as env vars
3. Update `backend/scripts/setup.sh` to add Snapcast stream source
4. Add supervisord config (if service needed)
5. Add integration API endpoints to `integrations_api.py`
6. Update frontend Settings UI
7. Test: Build → Deploy to RPi → Verify in web UI

### Debugging
```bash
docker logs plum-snapcast-server
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f [service]
docker exec plum-snapcast-server aplay -l
```

**Common Issues**:
- No audio: Check `aplay -l` output
- AirPlay not visible: Verify Avahi running, host Avahi disabled
- Bluetooth not pairing: Check `bluetoothctl show`, verify discoverable in UI
- Stream not found errors: Check lifecycle manager logs for false disconnect triggers

---

## Important Development Notes

1. **Container Architecture**: Self-contained D-Bus/Avahi - works across all host OS versions, no host mounts needed

2. **Dynamic Stream Lifecycle**: All integrations use lifecycle managers to create/remove streams based on activity. FIFO keepers prevent blocking when no stream exists. Signal files track disconnect events via mtime - be careful not to touch them unnecessarily.

3. **Multi-Instance Support**: AirPlay, Spotify Connect, and DLNA/UPnP each support up to 10 independent endpoints. Each appears as a separate device on the network. Control script wrapper pattern works around Snapcast's no-arguments limitation. See `airplay_endpoints_api.py`, `spotify_endpoints_api.py`, and `dlna_endpoints_api.py`.

4. **Playback Position API**: Independent from Snapcast to avoid audio stuttering. Uses dual-timestamp architecture for accurate interpolation. See `playback_api.py`.

5. **Browser Audio**: Snapweb clients hidden from UI. useBrowserAudio hook manages auto-assignment and reconnection.

6. **Audio I/O Config**: Output via GUI (Settings → Audio). Input devices (BETA) create ALSA streams - not yet tested with physical hardware.

7. **Enhanced Theming**: 5 modes, 6 accent colors + custom, album art extraction with WCAG AA contrast.

8. **Audio Visualizer**: Full-screen overlay, multiple presets, Web Audio API, smart color theming.

---

## Quick Reference

### Most Common Commands
```bash
# Development
cd frontend && npm run dev                # Dev server
cd frontend && npm run build              # Production build

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
- Frontend build: `frontend/dist/`
- Dev references: `/_resources/` (NOT in git)

---

## Resources

- **Snapcast**: https://github.com/badaix/snapcast
- **Snapcast JSON-RPC API**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/
- **Docker Snapcast**: https://github.com/firefrei/docker-snapcast
- **Shairport-Sync**: https://github.com/mikebrady/shairport-sync

---

## Maintaining This File

**When to Update**: Major architecture changes, new audio sources, new env vars, new workflows
**What Not to Include**: Temporary notes (use `_resources/`), detailed API specs (use ARCHITECTURE.md)
**Tips**: Document WHY (not just WHAT), keep ARCHITECTURE.md in sync for detailed specs
