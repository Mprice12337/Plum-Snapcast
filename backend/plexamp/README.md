# Plexamp Headless Container (Debian Sidecar)

This is a minimal Debian-based container that runs Plexamp headless alongside the main Alpine Snapcast container.

## Why a Separate Container?

Plexamp's pre-compiled native Node.js modules are built against **glibc** and cannot run on Alpine Linux's **musl libc**. The incompatibilities include:

- `__*_finite` math functions (glibc-specific optimizations)
- `__*_chk` security functions (glibc buffer overflow protection)
- `makecontext`/`getcontext`/`setcontext` (deprecated POSIX functions)
- Other glibc-specific ABI symbols

Even with compatibility layers like `gcompat`, these symbols don't exist in musl. Therefore, Plexamp requires a glibc-based distribution like Debian.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Host (Raspberry Pi)               │
│                                                               │
│  ┌────────────────────────────┐  ┌─────────────────────────┐│
│  │  Alpine Container          │  │  Debian Container       ││
│  │  (plum-snapcast-server)    │  │  (plum-plexamp)         ││
│  │                            │  │                         ││
│  │  - Snapcast server         │  │  - Node.js 20+          ││
│  │  - AirPlay (shairport)     │  │  - Plexamp headless     ││
│  │  - Spotify (spotifyd)      │  │  - ALSA→FIFO output     ││
│  │  - Bluetooth (bluez)       │  │                         ││
│  │  - DLNA (gmrender)         │  │  Writes audio ──────┐   ││
│  │  - Plexamp control script  │  │                     │   ││
│  │                            │  └─────────────────────┼───┘│
│  │  Reads audio ───────────────────────────────────────┘    │
│  │  from FIFO                 │                             │
│  │                            │                             │
│  └────────────────────────────┘                             │
│                                                               │
│  Shared Volume: snapcast-fifos                               │
│  └─ /tmp/snapcast-fifos/plexamp-fifo  (FIFO pipe)            │
└─────────────────────────────────────────────────────────────┘
```

## How It Works

1. **Plexamp** (Debian container) receives cast requests from Plex apps
2. **ALSA** redirects Plexamp's audio output to `/tmp/snapcast-fifos/plexamp-fifo`
3. **Snapcast** (Alpine container) reads from the shared FIFO pipe
4. **Control script** (Alpine, Python) polls Plexamp's HTTP API at `localhost:32500` for metadata

## Usage

### Enable Plexamp

1. **Get a claim token** (valid 4 minutes):
   ```bash
   # Visit https://plex.tv/claim and copy the token
   ```

2. **Update `.env`**:
   ```env
   PLEXAMP_ENABLED=1
   PLEXAMP_CLAIM_TOKEN=claim-xxxxxxxxxxxx
   PLEXAMP_SERVER_NAME=Plum Audio
   ```

3. **Start with Docker Compose profile**:
   ```bash
   docker compose --profile plexamp up -d
   ```

4. **Complete setup via web UI**:
   ```
   http://[raspberry-pi-ip]:32500
   ```
   - Select your music library
   - Configure audio quality settings

### Verify Operation

```bash
# Check Plexamp is running
docker logs plum-plexamp

# Verify FIFO exists in shared volume
docker exec plum-snapcast-server ls -la /tmp/snapcast-fifos/

# Test HTTP API
curl http://localhost:32500/
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PLEXAMP_CLAIM_TOKEN` | - | Claim token from https://plex.tv/claim |
| `PLEXAMP_PLAYER_NAME` | Plum Audio | Player name visible in Plex apps |
| `TZ` | America/Los_Angeles | Timezone |

## Volumes

- `plexamp-data:/app/plexamp` - Plexamp configuration and state
- `snapcast-fifos:/tmp/snapcast-fifos` - Shared FIFO pipe with Alpine container

## Ports

- `32500` - Plexamp web UI and HTTP API (host networking mode)

## Requirements

- **Plex Pass subscription** (required for Plexamp)
- **Host networking** (for mDNS service discovery)
- **Shared volume** with Alpine container for FIFO pipe

## Troubleshooting

### Plexamp not appearing as cast target

```bash
# Check if running
docker ps | grep plum-plexamp

# Check logs
docker logs plum-plexamp

# Verify claim token processed
docker exec plum-plexamp ls -la /app/plexamp/config.json

# Test HTTP API
curl http://localhost:32500/
```

### No audio output to Snapcast

```bash
# Verify FIFO exists
docker exec plum-snapcast-server ls -la /tmp/snapcast-fifos/plexamp-fifo

# Check ALSA config
docker exec plum-plexamp cat /etc/alsa/asound.conf

# Verify Snapcast stream configured
docker exec plum-snapcast-server cat /app/config/snapserver.conf | grep plexamp
```

## Dependencies

- **Debian Bookworm Slim** base image
- **Node.js** (from Debian repos, glibc-compatible)
- **ALSA** (audio output to FIFO)
- **curl** (health checks)
- **jq** (JSON parsing for version detection)

## Image Size

- Base: ~150MB (Debian bookworm-slim)
- With Node.js + Plexamp: ~250MB
- Total: Significantly smaller than full Alpine→Debian migration

## Alternatives Considered

1. ❌ **Alpine with gcompat** - Incompatible due to missing `__*_finite` symbols
2. ❌ **Migrate entire project to Debian** - Too disruptive, loses Alpine benefits
3. ❌ **Official plexinc/plexamp image** - Less control, doesn't integrate with Snapcast
4. ✅ **Debian sidecar (this solution)** - Minimal impact, preserves Alpine architecture

## Credits

- [Plexamp](https://plexamp.plex.tv/) by Plex Inc.
- Architecture inspired by microservices pattern
