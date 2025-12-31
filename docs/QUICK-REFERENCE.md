# Quick Reference - Plum-Snapcast

> One-page guide to essential commands, workflows, and troubleshooting for Plum-Snapcast development

---

## Git Workflow

### ✅ DO: Use `git pull --rebase`

```bash
# Set up rebase as default
git config pull.rebase true

# Or use alias
git config alias.pr 'pull --rebase'
git pr
```

**Why**: Maintains linear commit history, avoids merge commits

### ✅ DO: Handle rebase conflicts

```bash
# Option 1: Abort and use merge
git rebase --abort
git pull

# Option 2: Fix conflicts and continue
# [fix conflicts in files]
git add .
git rebase --continue
```

### Commit Message Format

```bash
# Format: <type>: <description>
git commit -m "feat: Add album artwork support to AirPlay metadata"
git commit -m "fix: Correct audio device permissions in Dockerfile"
git commit -m "docs: Update ARCHITECTURE.md with D-Bus/Avahi pattern"
```

**Types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`

---

## Docker Commands

### Container Management

```bash
# Start all containers
cd docker && docker compose up -d

# Stop containers
docker compose down

# Restart containers
docker compose restart

# View logs
docker compose logs -f
docker logs plum-snapcast-server | grep -i error

# Shell access
docker exec -it plum-snapcast-server sh
```

### Build and Deploy

```bash
# Multi-architecture build (amd64 + arm64)
cd docker && bash build-and-push.sh

# Build with --no-cache
bash build-and-push.sh --no-cache

# Quick local build (amd64 only)
cd backend && docker build -t plum-snapcast-server:dev .

# Deploy to Raspberry Pi
ssh pi@raspberrypi.local "cd ~/Plum-Snapcast/docker && docker compose pull && docker compose up -d"
```

### Service Management (Inside Container)

```bash
# Check all services
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status

# Restart specific service
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf restart shairport-sync

# View service logs
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapserver

# View all supervisord logs
docker exec plum-snapcast-server cat /var/log/supervisor/supervisord.log

# View lifecycle manager logs
docker logs plum-snapcast-server 2>&1 | grep -E '\[Lifecycle\]|\[Signal\]'
```

---

## Audio Testing

### Verify Audio Device

```bash
# List playback devices (what you can output to)
docker exec plum-snapcast-server aplay -l

# List capture devices (what you can record from)
docker exec plum-snapcast-server arecord -l

# Test specific output device
docker exec plum-snapcast-server speaker-test -D hw:0,0 -c 2 -t wav -l 1
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1
docker exec plum-snapcast-server speaker-test -D hw:1,0 -c 2 -t wav -l 1  # HAT or USB device
```

### Audio Device Configuration (API)

```bash
# List all available output devices
curl http://localhost:3000/api/audio/devices/output | python3 -m json.tool

# Get current output device
curl http://localhost:3000/api/audio/output/current

# Change output device to HAT (hw:1,0)
curl -X POST http://localhost:3000/api/audio/output/device \
  -H "Content-Type: application/json" \
  -d '{"hw_id":"hw:1,0"}'

# Test a device
curl -X POST http://localhost:3000/api/audio/output/test \
  -H "Content-Type: application/json" \
  -d '{"hw_id":"hw:Headphones"}'
```

**Note**: Audio devices are configured via GUI (Settings → Audio). The SNAPCLIENT_SOUNDCARD env var is deprecated.

```bash
# List all available input devices
curl http://localhost:3000/api/audio/devices/input | python3 -m json.tool

# Get configured input devices
curl http://localhost:3000/api/audio/input/devices | python3 -m json.tool

# Enable an input device (creates Snapcast stream)
curl -X POST http://localhost:3000/api/audio/input/device \
  -H "Content-Type: application/json" \
  -d '{"hw_id":"hw:0,0","custom_name":"Microphone","enabled":true}'

# Update stream name
curl -X POST http://localhost:3000/api/audio/input/device \
  -H "Content-Type: application/json" \
  -d '{"hw_id":"hw:0,0","custom_name":"Office Mic"}'

# Toggle input device on/off
curl -X POST http://localhost:3000/api/audio/input/device/hw%3A0%2C0/toggle

# Remove input device configuration
curl -X DELETE http://localhost:3000/api/audio/input/device/hw%3A0%2C0
```

**⚠️ BETA Feature - Testing Required**:
- Audio input device configuration is a beta feature
- Has NOT been tested with physical audio input devices
- Requires USB microphone or audio interface to validate
- Expected behavior:
  1. Input devices should be detected via `arecord -l`
  2. Enabling a device should create an ALSA input stream in Snapcast
  3. Stream should appear in Snapcast server status
  4. Audio from input device should be captured and streamed
- Please report any issues or successful tests

### AirPlay Endpoints API (Multi-Instance)

```bash
# List all AirPlay endpoints
curl http://localhost:3000/api/airplay/endpoints | python3 -m json.tool

# Add a new AirPlay endpoint
curl -X POST http://localhost:3000/api/airplay/endpoints \
  -H "Content-Type: application/json" \
  -d '{"deviceName":"Kitchen"}'

# Update endpoint name
curl -X PUT http://localhost:3000/api/airplay/endpoints/2 \
  -H "Content-Type: application/json" \
  -d '{"deviceName":"Kitchen Updated"}'

# Enable/disable an endpoint
curl -X PUT http://localhost:3000/api/airplay/endpoints/2 \
  -H "Content-Type: application/json" \
  -d '{"enabled":false}'

# Remove an endpoint
curl -X DELETE http://localhost:3000/api/airplay/endpoints/2
```

**Endpoint Limits**: Up to 10 AirPlay endpoints (ports 5050-5059)

### Playback Position API

```bash
# Get position for all active streams
curl http://localhost:5001/api/playback | python3 -m json.tool

# Get position for specific stream
curl "http://localhost:5001/api/playback/AirPlay%20-%20Living%20Room"

# Response includes interpolated_position for smooth progress bar updates
```

**Note**: The Playback Position API runs on the Federation port (5001) and provides real-time position tracking independent of Snapcast to avoid audio stuttering.

### Check Audio Pipeline

```bash
# 1. Verify audio device accessible
docker exec plum-snapcast-server aplay -l

# 2. Test speaker directly
docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1

# 3. Play via AirPlay
# Use iPhone/Mac → AirPlay → "Plum Audio"

# 4. Check web interface
# Open http://raspberrypi.local:3000
```

### Verify Services Running

```bash
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status

# Expected output (varies by enabled integrations):
# avahi                                  RUNNING
# dbus                                   RUNNING
# shairport-sync-1                       RUNNING    (AirPlay endpoint 1)
# shairport-sync-2                       RUNNING    (AirPlay endpoint 2, if configured)
# stream-lifecycle-manager-1             RUNNING    (AirPlay 1 lifecycle)
# stream-lifecycle-manager-2             RUNNING    (AirPlay 2 lifecycle, if configured)
# fifo-keeper-1                          RUNNING    (AirPlay 1 FIFO keeper)
# bluetooth-stream-lifecycle-manager     RUNNING    (if Bluetooth enabled)
# bluetooth-fifo-keeper                  RUNNING    (Bluetooth FIFO keeper)
# spotify-stream-lifecycle-manager       RUNNING    (if Spotify enabled)
# spotify-fifo-keeper                    RUNNING    (Spotify FIFO keeper)
# snapserver                             RUNNING
# snapclient                             RUNNING    (if hardware output enabled)
```

---

## Frontend Development

### Development Server

```bash
# Install dependencies
cd frontend && npm install

# Start dev server with HMR
npm run dev
# Opens at http://localhost:5173

# Enable access from other devices
npm run dev -- --host 0.0.0.0

# Build for production
npm run build

# Preview production build
npm run preview
```

### Type Checking

```bash
# Type check without building
npx tsc --noEmit

# Watch mode
npx tsc --noEmit --watch
```

### Code Quality

```bash
# Run linter (if configured)
npm run lint

# Format code (if configured)
npm run format
```

---

## Raspberry Pi Deployment

### One-Time Setup

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# 2. Configure audio permissions
echo 'SUBSYSTEM=="sound", MODE="0666"' | sudo tee /etc/udev/rules.d/99-audio-permissions.rules
sudo udevadm control --reload-rules && sudo udevadm trigger

# 3. Disable host Avahi (container runs its own)
sudo systemctl disable avahi-daemon.service
sudo systemctl disable avahi-daemon.socket

# 4. Clone and deploy
git clone <repo-url> ~/Plum-Snapcast
cd ~/Plum-Snapcast/docker
cp .env.example .env
nano .env  # Edit configuration
docker compose pull && docker compose up -d

# 5. Reboot
sudo reboot
```

### Update Deployment

```bash
# SSH to Raspberry Pi
ssh pi@raspberrypi.local

# Update application
cd ~/Plum-Snapcast/docker
git pull
docker compose pull
docker compose up -d

# Verify services
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
```

---

## WebSocket / JSON-RPC

### Test WebSocket Connection

**In browser console:**
```javascript
// Monitor WebSocket messages
snapcastService.ws.addEventListener('message', (e) => {
  console.log('WebSocket RX:', JSON.parse(e.data));
});

// Send test request
snapcastService.send({
  id: 999,
  jsonrpc: "2.0",
  method: "Server.GetStatus"
});
```

### Common JSON-RPC Methods

```bash
# Get server status (all streams, groups, clients)
{ "method": "Server.GetStatus" }

# Set client volume
{ "method": "Client.SetVolume", "params": { "id": "client-id", "volume": { "percent": 80, "muted": false } } }

# Assign stream to group
{ "method": "Group.SetStream", "params": { "id": "group-id", "stream_id": "stream-id" } }

# Control playback
{ "method": "Stream.Control", "params": { "id": "stream-id", "command": "play" } }
```

---

## Environment Variables

### Backend (.env in docker/ folder)

**Note**: Most integration settings are now managed via web UI (Settings → Integrations). Only container-level settings use env vars.

```bash
# Snapclient (integrated audio output)
SNAPCLIENT_ENABLED=1
SNAPCLIENT_LATENCY=0
# SNAPCLIENT_SOUNDCARD is deprecated - use Settings → Audio instead

# Plexamp (optional, separate container)
PLEXAMP_ENABLED=0
PLEXAMP_CLAIM_TOKEN=claim-xxxxx  # From https://plex.tv/claim
PLEXAMP_SERVER_NAME=Plum Plexamp

# General
TZ=America/New_York
FRONTEND_PORT=3000
HTTPS_ENABLED=1
```

**Managed via Web UI** (Settings → Integrations):
- AirPlay: Enable/disable, device names, multi-endpoint support
- Bluetooth: Enable/disable, device name, discoverable setting
- Spotify: Enable/disable, device name
- DLNA: Enable/disable, device name

### Frontend (.env.local in frontend/ folder)

```bash
VITE_SNAPCAST_HOST=localhost
VITE_SNAPCAST_PORT=1788
```

---

## Troubleshooting

### No Audio Output

```bash
# Check snapclient status
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status snapclient
# Should show: RUNNING

# If FATAL, check logs
docker logs plum-snapcast-server | grep snapclient

# Verify audio device
docker exec plum-snapcast-server aplay -l

# Fix permissions (on Raspberry Pi)
sudo chmod 666 /dev/snd/*
sudo udevadm control --reload-rules && sudo udevadm trigger
docker compose restart
```

### AirPlay Device Not Visible

```bash
# Check Avahi is running
docker exec plum-snapcast-server ps aux | grep avahi

# Verify host Avahi is disabled
sudo systemctl status avahi-daemon.service
# Should show: disabled

# Check D-Bus socket accessible
docker exec plum-snapcast-server test -S /var/run/dbus/system_bus_socket && echo "OK" || echo "FAIL"

# Restart container
docker compose restart

# Scan for AirPlay services (from another machine)
avahi-browse -r _raop._tcp
```

### Audio Group Mismatch

```bash
# Check container's audio group
docker exec plum-snapcast-server id
# Should show: groups=29(audio)

# Check device group ownership on host
ls -la /dev/snd/controlC0
# Should show: crw-rw-rw- 1 root 29 ...

# If GID mismatch, rebuild with correct GID in Dockerfile
```

### Frontend Can't Connect to Backend

```bash
# Verify backend is running
docker compose ps

# Check WebSocket endpoint accessible
curl -k https://localhost:1788/jsonrpc
# Should return WebSocket upgrade error (expected)

# Check snapserver logs
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapserver

# Restart backend
docker compose restart
```

### Stream Not Appearing (Dynamic Lifecycle)

```bash
# Check lifecycle manager status (example: AirPlay)
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status | grep lifecycle
# Should show: RUNNING

# View lifecycle manager logs
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f stream-lifecycle-manager stderr

# Check if FIFO keeper is running
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status | grep fifo-keeper
# Should show: RUNNING

# Test metadata flow (AirPlay example)
docker exec plum-snapcast-server timeout 10 cat /tmp/shairport-sync-metadata | head -20
# Should show XML metadata when AirPlay is connected

# Manually check for streams in Snapcast
curl -s http://localhost:1780/jsonrpc -d '{"jsonrpc":"2.0","method":"Server.GetStatus","id":1}' | grep -o '"name":"[^"]*"'
```

### Orphaned Control Scripts

```bash
# Check for orphaned control script processes
docker exec plum-snapcast-server ps aux | grep control-script
# Should only see running scripts when streams exist

# Kill orphaned processes
docker exec plum-snapcast-server pkill -f airplay-control-script.py

# Restart lifecycle manager to trigger cleanup
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf restart stream-lifecycle-manager
```

### Docker Build Fails

```bash
# Clear build cache
docker builder prune

# Rebuild with --no-cache
cd docker && bash build-and-push.sh --no-cache

# Check buildx builder
docker buildx ls
docker buildx inspect multiarch
```

---

## File Locations

### Project Structure

```
├── _resources/              # Development references (NOT in git)
├── docs/                    # All documentation
│   ├── ARCHITECTURE.md      # System architecture
│   ├── CLAUDE.md            # Claude Code config (symlinked to root)
│   ├── DEV-SETUP.md         # Development setup guide
│   └── QUICK-REFERENCE.md   # This file
├── backend/                 # Docker container backend
│   ├── Dockerfile           # Multi-arch backend build
│   ├── config/              # Configuration templates
│   │   ├── shairport-sync.conf
│   │   └── snapserver.conf.template
│   ├── scripts/             # Backend scripts
│   │   ├── entrypoint.sh
│   │   ├── generate-config.sh
│   │   └── process-airplay-metadata.sh
│   └── supervisord/         # Process management
├── frontend/                # React/TypeScript web app
│   ├── src/
│   │   ├── components/
│   │   ├── services/
│   │   ├── hooks/
│   │   └── App.tsx
│   └── vite.config.ts
├── docker/                  # Docker Compose
│   ├── docker-compose.yml
│   ├── .env.example
│   └── build-and-push.sh
└── README.md                # Main documentation
```

### Container Paths (Inside Backend Container)

```bash
/app/config/                  # Configuration files
/app/data/                    # Runtime data
/app/certs/                   # TLS certificates
/tmp/snapfifo                 # FIFO pipe for audio
/var/run/dbus/system_bus_socket  # D-Bus socket (from host)
/var/log/supervisor/supervisord.log  # All service logs
```

---

## Common Tasks

### Add New Frontend Component

```bash
cd frontend/src/components

# Create component
cat > NewComponent.tsx << 'EOF'
import React from 'react';

interface NewComponentProps {
  title: string;
}

export const NewComponent: React.FC<NewComponentProps> = ({ title }) => {
  return <div><h2>{title}</h2></div>;
};
EOF

# Import in App.tsx and use
```

### Modify Backend Configuration

```bash
# Edit configuration generator
nano backend/scripts/generate-config.sh

# Rebuild backend
cd backend && docker build -t plum-snapcast-server:dev .

# Restart
cd ../docker && docker compose down && docker compose up -d
```

### Add Environment Variable

**Backend:**
```bash
# 1. Edit docker/.env.example
nano docker/.env.example

# 2. Update your docker/.env
nano docker/.env

# 3. Update generate-config.sh to use new variable
nano backend/scripts/generate-config.sh

# 4. Rebuild and restart
docker compose down && docker compose up -d
```

**Frontend:**
```bash
# 1. Add to frontend/.env.local (must start with VITE_)
echo "VITE_NEW_VARIABLE=value" >> frontend/.env.local

# 2. Use in code
const newVar = import.meta.env.VITE_NEW_VARIABLE;

# 3. Restart dev server
npm run dev
```

### View Detailed Logs

```bash
# All container logs
docker logs plum-snapcast-server

# Specific service via supervisord
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f snapclient stdout

# Errors only
docker logs plum-snapcast-server 2>&1 | grep -i "error\|fail"

# Supervisord combined log
docker exec plum-snapcast-server cat /var/log/supervisor/supervisord.log
```

---

## Architecture Essentials

### Audio Pipeline

```
iOS/Mac (AirPlay) or Spotify App or Plex
              ↓
    shairport-sync / spotifyd / plexamp / gmrender / bluealsa
              ↓
       /tmp/*-fifo (FIFO pipes per source)
              ↓
         snapserver (distributes audio)
              ↓
         snapclient (integrated, outputs to hardware)
              ↓
    ALSA output device (configured via Settings → Audio)
              ↓
      Speakers/Headphones
```

### Critical Architecture Pattern

**Self-Contained Container:**
- **Container**: Runs its own D-Bus and Avahi daemons (fully self-contained)
- **Host System**: Only requires Docker and audio device access - no D-Bus/Avahi config needed
- **Portability**: Works identically across different host OS versions (Debian 12, 13, etc.)

**Why**: True Docker isolation, no host dependencies, eliminates OS-specific issues

### Port Mappings

**Snapcast:**
- `1704-1705`: Client connections
- `1780`: HTTP/WebSocket (legacy)
- `1788`: HTTPS/WebSocket (default)

**AirPlay (Multi-Instance):**
- `5050-5059`: AirPlay endpoints (5050 + endpoint_id - 1)
- `6001-6100/udp`: RTP/timing ports (10 per endpoint)
- `3689, 5353/udp`: mDNS (Avahi)
- `319-320/udp`: NQPTP for AirPlay 2

**Internal APIs:**
- `5001`: Federation/Playback API
- `5002`: Settings API
- `5003`: Integrations API
- `5004`: Audio API

**Frontend:**
- `3000`: Web interface (default, proxies to all APIs)

---

## Quick Wins

1. **Git rebase alias**: `git config alias.pr 'pull --rebase'`
2. **Audio test command**: `docker exec plum-snapcast-server speaker-test -D hw:Headphones -c 2 -t wav -l 1`
3. **Service status**: `docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status`
4. **View logs**: `docker logs plum-snapcast-server | grep -i error`
5. **Restart services**: `docker compose restart`
6. **Frontend dev**: `cd frontend && npm run dev`
7. **Build and push**: `cd docker && bash build-and-push.sh`
8. **SSH to Pi**: `ssh pi@raspberrypi.local`
9. **Update Pi**: `cd ~/Plum-Snapcast/docker && git pull && docker compose pull && docker compose up -d`
10. **Check D-Bus**: `docker exec plum-snapcast-server test -S /var/run/dbus/system_bus_socket && echo "OK"`

---

## Naming Conventions

- **React Components**: `PascalCase.tsx` (e.g., `NowPlaying.tsx`)
- **Services**: `camelCase.ts` (e.g., `snapcastService.ts`)
- **Functions/Variables**: `camelCase` (e.g., `getCurrentStream`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_VOLUME`)
- **Environment Variables**: `UPPER_SNAKE_CASE` (e.g., `AIRPLAY_DEVICE_NAME`)
- **Git Commits**: `<type>: <description>` (e.g., `feat: Add new component`)

---

## Resources

- **Snapcast Documentation**: https://github.com/badaix/snapcast
- **Snapcast JSON-RPC API**: https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/
- **React Documentation**: https://react.dev
- **Vite Documentation**: https://vitejs.dev
- **Docker Documentation**: https://docs.docker.com
- **Alpine Linux Packages**: https://pkgs.alpinelinux.org/

---

## Emergency Commands

### Complete Reset

```bash
# Stop and remove everything
docker compose down -v

# Remove all volumes
docker volume rm docker_snapcast-config docker_snapcast-data docker_snapcast-certs

# Rebuild from scratch
docker compose up -d

# Container will regenerate defaults
```

### Fix Permissions (Raspberry Pi)

```bash
# Fix audio device permissions
sudo chmod 666 /dev/snd/*
sudo udevadm control --reload-rules && sudo udevadm trigger

# Restart container
docker compose restart
```

### Force Rebuild

```bash
# Backend
cd backend && docker build --no-cache -t plum-snapcast-server:dev .

# Multi-arch with no cache
cd docker && bash build-and-push.sh --no-cache
```

---

**Pro Tip**: When in doubt, check the supervisord log first:
```bash
docker exec plum-snapcast-server cat /var/log/supervisor/supervisord.log | tail -50
```

This log contains output from all services and is the first place to look when debugging issues.
