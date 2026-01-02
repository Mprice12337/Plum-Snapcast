# Multi-Instance Support Feasibility Analysis

> **Status**: ✅ COMPLETED - Both Spotify Connect and DLNA/UPnP multi-instance implementations are complete and merged to main.
>
> This document served as the feasibility analysis and is preserved for historical reference.

## Executive Summary

Based on thorough research of the codebase and underlying technologies, here's the feasibility assessment for multi-instance support:

| Integration | Feasible? | Effort | Rationale |
|-------------|-----------|--------|-----------|
| **Bluetooth** | **NO** | N/A | Hardware/protocol limitation - A2DP supports ONE audio stream |
| **Spotify Connect** | **YES** | Medium-High | Zeroconf auth (no credentials) - same pattern as AirPlay |
| **DLNA/UPnP** | **YES** | Medium-High | gmrender supports multiple instances, needs AirPlay-style refactoring |

---

## 1. Bluetooth - NOT FEASIBLE

### Technical Analysis

**Fundamental Limitation**: Bluetooth A2DP (Advanced Audio Distribution Profile) only supports **ONE active audio stream** at a time per adapter.

**Current Architecture Already Optimal**:
- Multiple devices CAN pair and connect simultaneously
- `connected_devices = set()` tracks all connected A2DP devices
- When one device plays, others are in standby
- Switching requires user action on source device

**Why Multiple Streams Are Impossible**:
1. **A2DP Protocol**: Designed for point-to-point audio streaming (one source → one sink)
2. **Single ALSA Device**: `bluealsa` exposes one audio device for all Bluetooth audio
3. **Hardware Constraint**: Single Bluetooth adapter can only receive one A2DP stream
4. **No Software Workaround**: Even with multiple USB Bluetooth adapters, each would be a separate system requiring complex routing

**Code Evidence** (`bluetooth-stream-lifecycle-manager.py`):
```python
BLUETOOTH_STREAM_ID = "Bluetooth"  # Single stream - by design
self.connected_devices = set()      # Tracks MULTIPLE devices, but...
# Only ONE plays audio at a time (A2DP limitation)
```

### Recommendation

**Do not pursue multi-instance Bluetooth**. The current implementation is already optimal:
- Multiple devices can pair/connect
- Seamless handoff between devices
- No user confusion about which "Bluetooth endpoint" to use

---

## 2. Spotify Connect - FEASIBLE ✓

### Technical Analysis

**Key Discovery**: Spotify Connect uses **Zeroconf authentication** - NO server-side credentials needed!

**How It Works** (identical to AirPlay):
1. Each spotifyd instance advertises itself via mDNS (`_spotify-connect._tcp`)
2. Users see multiple "speakers" in their Spotify app
3. When connecting, the Spotify app transfers encrypted credentials to spotifyd
4. spotifyd authenticates on behalf of that user - no stored passwords
5. Different users can connect to different instances simultaneously

**Evidence from Current Config** (`spotifyd.conf`):
```ini
# NO username/password fields - pure Zeroconf mode
zeroconf_port = 0  # Auto-assign port for discovery
device_name = "Plum Audio"
```

**Official Spotify ZeroConf API Confirms Multi-Device Support**:
> "Using ZeroConf, it is possible to announce multiple 'virtual devices' from a device.
> This allows the eSDK device to expose, for instance, multiroom zones as ZeroConf devices."
> — [Spotify ZeroConf API Documentation](https://developer.spotify.com/documentation/commercial-hardware/implementation/guides/zeroconf)

**Real-World Confirmation** ([GitHub Issue #114](https://github.com/Spotifyd/spotifyd/issues/114)):
> "I'm running 2 daemons at a time on a Raspberry Pi so that one can use its own account
> in the living room on the amplifier."

### What Each Instance Needs

| Resource | Pattern | Example |
|----------|---------|---------|
| Device Name | Unique per instance | "Living Room", "Kitchen" |
| Zeroconf Port | Auto or explicit | 0 (auto) or 5354, 5355, etc. |
| FIFO Pipe | `/tmp/spotify-{id}-fifo` | `/tmp/spotify-1-fifo` |
| D-Bus Service | Auto instance naming | `org.mpris.MediaPlayer2.spotifyd.instance{PID}` |
| Cache Dir | `/tmp/spotify-{id}-cache` | `/tmp/spotify-1-cache` |
| Config File | `/app/config/spotifyd-{id}.conf` | `/app/config/spotifyd-1.conf` |

### Implementation Plan

#### Phase 1: Infrastructure (Foundation)

**1.1 Create Configuration Template** (`spotifyd.conf.template`)
```ini
[global]
device_name = "SPOTIFY_NAME"
backend = "pipe"
device = "/tmp/spotify-INSTANCE_ID-fifo"
cache_path = "/tmp/spotify-INSTANCE_ID-cache"
zeroconf_port = SPOTIFY_ZEROCONF_PORT
use_mpris = true
dbus_type = "system"
bitrate = 320
audio_format = "S16"
device_type = "speaker"
volume_normalisation = true
initial_volume = 50
```

**1.2 Port Allocation Strategy**
- Zeroconf Port: 5354 + (endpoint_id - 1)
  - Endpoint 1: 5354 (or 0 for auto)
  - Endpoint 2: 5355
  - Endpoint 3: 5356
- Maximum: 10 endpoints (matching AirPlay)

**1.3 Create `spotify_endpoints_api.py`** (based on `airplay_endpoints_api.py`)
```python
class SpotifyEndpointsController:
    def list_endpoints() -> List[Dict]
    def add_endpoint(device_name: str, enabled: bool = True) -> Dict
    def update_endpoint(endpoint_id: str, ...) -> Dict
    def remove_endpoint(endpoint_id: str) -> Dict
```

#### Phase 2: Backend Scripts

**2.1 Create `setup-spotify-multi-instance.sh`**
- Generate per-instance spotifyd configs from template
- Create FIFOs with correct permissions
- Generate control script wrappers (Snapcast limitation workaround)

**2.2 Create `generate-spotify-supervisord-config.py`**
Generate for each endpoint:
```ini
[program:spotifyd-{id}]
[program:spotify-{id}-fifo-keeper]
[program:spotify-{id}-lifecycle-manager]
```

**2.3 Update `spotify-stream-lifecycle-manager.py`**
Add `--instance-id` argument support:
```python
if args.instance_id:
    globals()['SPOTIFY_STREAM_ID'] = f"Spotify - {endpoint_name}"
    globals()['SPOTIFY_FIFO_PATH'] = f"/tmp/spotify-{instance_id}-fifo"
    globals()['LOG_FILE'] = f"/tmp/spotify-lifecycle-{instance_id}.log"
```

**2.4 Update `spotify-control-script.py`**
- Add `--instance-id` argument support
- Per-instance D-Bus service discovery
- Per-instance metadata handling

**2.5 Create Control Script Wrapper Pattern**
```python
# /usr/share/snapserver/plug-ins/spotify-control-script-{id}.py
import os
os.execv("/app/scripts/spotify-control-script.py",
         ["spotify-control-script.py", "--instance-id", "{id}"])
```

#### Phase 3: Frontend Integration

**3.1 Update `IntegrationsTab.tsx`**
- Add Spotify endpoints management UI (similar to AirPlay)
- List/Add/Edit/Remove endpoint controls
- Device name configuration per endpoint

**3.2 Update `integrationsService.ts`**
```typescript
getSpotifyEndpoints(): Promise<SpotifyEndpoint[]>
addSpotifyEndpoint(deviceName: string): Promise<SpotifyEndpoint>
updateSpotifyEndpoint(id: string, updates: Partial<SpotifyEndpoint>): Promise<SpotifyEndpoint>
removeSpotifyEndpoint(id: string): Promise<void>
```

#### Phase 4: Testing & Documentation

**4.1 Test Scenarios**
- [ ] Multiple Spotify endpoints visible in Spotify app
- [ ] Different users connecting to different endpoints
- [ ] Simultaneous playback to different endpoints
- [ ] Dynamic add/remove without container restart
- [ ] Metadata accuracy per endpoint
- [ ] Playback controls per endpoint

### Estimated Changes

| Component | Files to Create | Files to Modify |
|-----------|-----------------|-----------------|
| Backend Scripts | 3 new | 3 modified |
| Config Templates | 1 new | 0 |
| Supervisord | 1 template | 1 modified |
| API Endpoints | 1 new | 1 modified |
| Frontend | 0 new | 2 modified |
| Documentation | 0 new | 3 modified |

### User Experience

**In Spotify App**: Users will see multiple devices:
- "Living Room" (Spotify Connect)
- "Kitchen" (Spotify Connect)
- "Bedroom" (Spotify Connect)

**Behavior**: Each device is independent - different users/accounts can play to different rooms simultaneously.

### Sources

- [Spotify ZeroConf API Documentation](https://developer.spotify.com/documentation/commercial-hardware/implementation/guides/zeroconf)
- [spotifyd Multi-Instance Discussion (GitHub #114)](https://github.com/Spotifyd/spotifyd/issues/114)
- [Home Assistant Add-on Multi-Account Request (GitHub #26)](https://github.com/hassio-addons/addon-spotify-connect/issues/26)

---

## 3. DLNA/UPnP - FEASIBLE

### Technical Analysis

**gmrender-resurrect Supports Multiple Instances**:
- Each instance can have unique `--friendly-name`
- Each instance can have unique `--uuid`
- Each instance binds to different port
- UPnP discovery handles multiple renderers naturally

**Current Single-Instance Implementation**:
```bash
# gmrender.ini - Single instance
/usr/local/bin/gmediarender \
    --friendly-name "Plum Audio" \
    --gstout-audiopipe "... filesink location=/tmp/dlna-fifo"
```

### Implementation Plan

#### Phase 1: Infrastructure (Foundation)

**1.1 Create Configuration Template**
```
File: /app/config/gmrender.conf.template

[gmrender]
friendly_name = DLNA_NAME
uuid = DLNA_UUID
port = DLNA_PORT
fifo_path = /tmp/dlna-INSTANCE_ID-fifo
metadata_file = /tmp/dlna-INSTANCE_ID-metadata.json
```

**1.2 Port Allocation Strategy**
- Primary Port: 49494 + (endpoint_id - 1)
  - Endpoint 1: 49494
  - Endpoint 2: 49495
  - Endpoint 3: 49496
- Maximum: 10 endpoints (matching AirPlay)

**1.3 Per-Instance Resources**
Each endpoint needs:
- FIFO: `/tmp/dlna-{id}-fifo`
- Metadata: `/tmp/dlna-{id}-metadata.json`
- Log: `/tmp/dlna-{id}.log`
- UUID: Auto-generated or user-specified

#### Phase 2: Backend Scripts

**2.1 Create `dlna_endpoints_api.py`** (based on `airplay_endpoints_api.py`)
```python
class DLNAEndpointsController:
    def list_endpoints() -> List[Dict]
    def add_endpoint(device_name: str, enabled: bool = True) -> Dict
    def update_endpoint(endpoint_id: str, device_name: str = None, enabled: bool = None) -> Dict
    def remove_endpoint(endpoint_id: str) -> Dict
```

**2.2 Create `setup-dlna-multi-instance.sh`**
- Generate per-instance gmrender configs
- Create FIFOs with correct permissions
- Generate control script wrappers

**2.3 Create `generate-dlna-supervisord-config.py`**
Generate for each endpoint:
```ini
[program:gmrender-{id}]
[program:dlna-{id}-fifo-keeper]
[program:dlna-{id}-lifecycle-manager]
[program:dlna-{id}-metadata-bridge]
```

**2.4 Update `dlna-stream-lifecycle-manager.py`**
- Add `--instance-id` argument support
- Per-instance stream IDs: `DLNA - {deviceName}`
- Per-instance FIFO and metadata paths
- Fix missing `_cleanup_control_scripts()` method (bug found during research)

**2.5 Update `dlna-control-script.py`**
- Add `--instance-id` argument support
- Per-instance metadata file monitoring
- Per-instance UPnP port discovery

**2.6 Create Control Script Wrapper Pattern**
```python
# /usr/share/snapserver/plug-ins/dlna-control-script-{id}.py
import os
os.execv("/app/scripts/dlna-control-script.py",
         ["dlna-control-script.py", "--instance-id", "{id}"])
```

#### Phase 3: Frontend Integration

**3.1 Update `IntegrationsTab.tsx`**
- Add DLNA endpoints management UI (similar to AirPlay)
- List/Add/Edit/Remove endpoint controls
- Device name configuration per endpoint

**3.2 Update `integrationsService.ts`**
```typescript
// New API methods
getDLNAEndpoints(): Promise<DLNAEndpoint[]>
addDLNAEndpoint(deviceName: string): Promise<DLNAEndpoint>
updateDLNAEndpoint(id: string, updates: Partial<DLNAEndpoint>): Promise<DLNAEndpoint>
removeDLNAEndpoint(id: string): Promise<void>
```

#### Phase 4: Testing & Documentation

**4.1 Test Scenarios**
- [ ] Multiple DLNA renderers visible on network
- [ ] Simultaneous playback to different endpoints
- [ ] Dynamic add/remove without container restart
- [ ] Metadata accuracy per endpoint
- [ ] Playback controls per endpoint

**4.2 Documentation Updates**
- Update ARCHITECTURE.md with multi-instance DLNA
- Update CLAUDE.md with new patterns
- Update README.md with multi-DLNA feature

### Estimated Changes

| Component | Files to Create | Files to Modify |
|-----------|-----------------|-----------------|
| Backend Scripts | 3 new | 4 modified |
| Supervisord Configs | 1 template | 1 modified |
| API Endpoints | 1 new | 1 modified |
| Frontend | 0 new | 2 modified |
| Documentation | 0 new | 3 modified |

### Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| UPnP port conflicts | Low | Strict port allocation, validation |
| Metadata bridge complexity | Medium | Per-instance log monitoring |
| GStreamer pipeline issues | Low | Proven pattern from single instance |
| UUID collision | Low | Auto-generate unique UUIDs |

---

## Implementation Priority Recommendation

1. **Spotify Connect Multi-Instance**: HIGH PRIORITY ✓
   - Same Zeroconf pattern as AirPlay (proven architecture)
   - Popular use case (family members with different Spotify accounts)
   - Medium complexity - can reuse AirPlay patterns directly
   - Each user sees their room in their Spotify app

2. **DLNA/UPnP Multi-Instance**: MEDIUM PRIORITY ✓
   - Clear technical path forward
   - Good user value (multiple DLNA renderers for different rooms)
   - Medium complexity (AirPlay provides excellent template)
   - Less common use case than Spotify

3. **Bluetooth**: NOT FEASIBLE
   - Hardware limitation makes it impossible
   - Current implementation already handles multiple paired devices optimally

---

## Appendix: Key Reference Files

### AirPlay Multi-Instance (Reference Pattern)
- `backend/scripts/airplay_endpoints_api.py` - API endpoint management
- `backend/scripts/generate-airplay-supervisord-config.py` - Dynamic config generation
- `backend/scripts/setup-airplay-multi-instance.sh` - Instance setup script
- `backend/scripts/stream-lifecycle-manager.py` - Lifecycle management (instance-aware)
- `backend/config/shairport-sync.conf.template` - Config template pattern

### Current DLNA Implementation (To Be Extended)
- `backend/config/supervisord/gmrender.ini` - Single instance config
- `backend/scripts/dlna-stream-lifecycle-manager.py` - Lifecycle manager
- `backend/scripts/dlna-control-script.py` - Control script
- `backend/scripts/gmrender-metadata-bridge.py` - Metadata extraction
- `backend/scripts/dlna-fifo-keeper.sh` - FIFO management

### Current Spotify Implementation (To Be Extended)
- `backend/config/spotifyd.conf` - Single instance config → template
- `backend/scripts/spotify-stream-lifecycle-manager.py` - Lifecycle manager → add instance support
- `backend/scripts/spotify-control-script.py` - Control script → add instance support
- `backend/scripts/spotify-fifo-keeper.sh` - FIFO management

### Current Bluetooth Implementation (No Changes Needed)
- `backend/scripts/bluetooth-stream-lifecycle-manager.py` - Already handles multiple devices
- `backend/scripts/bluetooth-control-script.py` - Metadata/controls
