# Federation Architecture for Multi-Server Snapcast

> **Status**: Implemented
> **Branch**: `feature/federation-layer`
> **Author**: Claude + Michael Price
> **Date**: December 2024

## Overview

The Federation Layer enables a unified control plane for multiple Snapcast servers, providing:
- **Unified View**: See all streams and clients from all servers in one interface
- **Cross-Server Control**: Control volume and playback for clients on any server
- **Partial Cross-Server Routing**: Route managed clients (local snapclient) to streams on any server

**Important Limitation**: Due to Snapcast architecture, cross-server routing only works for clients you have shell access to (local snapclient). Third-party server clients (like Music Assistant) cannot be routed to different servers via API.

## Problem Statement

Snapcast's default architecture has limitations for multi-server deployments:
- **Streams are server-bound**: Each stream lives on a specific server
- **Clients connect to one server**: A snapclient can only play streams from its connected server
- **No native federation**: Servers don't communicate or share routing information

### Target Use Cases

1. **Multi-user simultaneous streaming**: User A streams AirPlay to Living Room + Garage while User B streams to Office + Bedroom
2. **Distributed endpoints**: Main server (wired, beefy CPU) handles source processing; WiFi endpoints throughout the house receive audio
3. **Scalable sources**: Add AirPlay/Bluetooth endpoints without infrastructure changes
4. **Matrix-style routing**: Any source to any destination, like Dante or Q-SYS

## Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                      Frontend (React)                           │
│                 Shows ALL streams from ALL servers              │
│                 Routes ANY client to ANY stream                 │
└─────────────────────────┬───────────────────────────────────────┘
                          │ REST API
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Federation Service                            │
│  • Discovers servers via Avahi                                  │
│  • Aggregates streams/clients from all servers                  │
│  • Handles cross-server routing                                 │
│  • Exposes unified REST API                                     │
└────────┬────────────────┬────────────────┬──────────────────────┘
         │                │                │
    JSON-RPC         JSON-RPC         JSON-RPC
         │                │                │
         ▼                ▼                ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Server .122 │   │ Server .123 │   │ Server .226 │
│ Main Server │   │  Office Pi  │   │Music Assist │
├─────────────┤   ├─────────────┤   ├─────────────┤
│ AirPlay-1   │   │ AirPlay-Off │   │ MA-Stream1  │
│ AirPlay-2   │   │ Bluetooth   │   │ MA-Stream2  │
│ Spotify     │   │             │   │             │
└─────────────┘   └─────────────┘   └─────────────┘
```

### Components

#### 1. Federation Service (Backend)

A Python service running alongside Snapserver that:
- Discovers Snapcast servers on the network via Avahi/mDNS
- Connects to each server's JSON-RPC WebSocket API
- Aggregates stream and client metadata
- Handles cross-server client routing
- Exposes a unified REST API for the frontend

#### 2. Frontend Updates

Enhanced React UI that:
- Connects to Federation API instead of direct Snapcast WebSocket
- Displays streams grouped by server with clear labeling
- Allows routing any client to any stream (cross-server)
- Provides server management (add/remove/configure)
- Presents a matrix-style view (sources × destinations)

#### 3. Multi-Source Support (Backend)

Enhanced source configuration:
- Multiple shairport-sync instances for concurrent AirPlay users
- Each instance has unique Avahi name and dedicated FIFO
- Environment variables control number of instances
- Auto-generated Snapserver stream configuration

## API Design

### Federation Service REST API

#### GET /api/federation/servers
Returns all discovered Snapcast servers.

```json
{
  "servers": [
    {
      "id": "server-122",
      "name": "Main Server",
      "host": "192.168.7.122",
      "port": 1780,
      "connected": true,
      "isLocal": true
    },
    {
      "id": "server-226",
      "name": "Music Assistant",
      "host": "192.168.7.226",
      "port": 1780,
      "connected": true,
      "isLocal": false
    }
  ]
}
```

#### GET /api/federation/streams
Returns all streams from all servers.

```json
{
  "streams": [
    {
      "id": "122-airplay1",
      "serverId": "server-122",
      "serverName": "Main Server",
      "name": "AirPlay Zone 1",
      "status": "playing",
      "metadata": {
        "title": "Song Name",
        "artist": "Artist",
        "album": "Album",
        "artUrl": "..."
      }
    },
    {
      "id": "226-ma-stream",
      "serverId": "server-226",
      "serverName": "Music Assistant",
      "name": "MA Default",
      "status": "idle"
    }
  ]
}
```

#### GET /api/federation/clients
Returns all clients from all servers.

```json
{
  "clients": [
    {
      "id": "122-living-room",
      "serverId": "server-122",
      "serverName": "Main Server",
      "name": "Living Room",
      "connected": true,
      "currentStreamId": "122-airplay1",
      "volume": 80,
      "muted": false
    }
  ]
}
```

#### POST /api/federation/route
Route a client to a stream (handles cross-server routing).

```json
// Request
{
  "clientId": "122-living-room",
  "streamId": "226-ma-stream"
}

// Response
{
  "success": true,
  "message": "Client 'Living Room' routed to 'MA Default' on server 'Music Assistant'"
}
```

#### POST /api/federation/client/volume
Set client volume.

```json
{
  "clientId": "122-living-room",
  "volume": 75,
  "muted": false
}
```

### Cross-Server Routing Logic

When a client needs to play a stream from a different server:

1. Federation Service identifies which server owns the target stream
2. **If client is on same server**:
   - Simply assign client to stream via JSON-RPC (`Group.SetStream`)
3. **If client is on different server**:
   - **Only works for local snapclient** (shell access required)
   - Reconfigure snapclient via supervisord to connect to target server
   - Wait for client to appear on target server
   - Assign client to requested stream

**Limitation**: Snapcast has no API to remotely change a client's server connection. Cross-server routing requires:
- Shell access to the client's host system
- Permission to modify client configuration
- Ability to restart the snapclient process

This means third-party server clients (e.g., Music Assistant) cannot be routed cross-server, as they're controlled by their respective systems.

## Data Model Changes

### types.ts Updates

```typescript
// New: Server representation
export interface Server {
  id: string;           // "server-122"
  name: string;         // "Main Server"
  host: string;         // "192.168.7.122"
  port: number;         // 1780
  connected: boolean;
  isLocal: boolean;
}

// Updated: Stream with server context
export interface Stream {
  id: string;           // "122-airplay1" (prefixed with server)
  serverId: string;     // "server-122"
  serverName: string;   // "Main Server"
  name: string;         // "AirPlay Zone 1"
  sourceDevice: string;
  currentTrack: Track;
  isPlaying: boolean;
  progress: number;
}

// Updated: Client with server context
export interface Client {
  id: string;           // "122-living-room" (prefixed with server)
  serverId: string;     // "server-122"
  serverName: string;   // "Main Server"
  name: string;         // "Living Room"
  currentStreamId: string | null;
  volume: number;
  connected: boolean;
}

// Updated: Settings with federation config
export interface Settings {
  // ... existing fields
  federation: {
    enabled: boolean;
    autoDiscover: boolean;
    manualServers: ServerConfig[];
    localServerName: string;
  };
}
```

## Implementation Status

### Implemented Features ✅

1. **Multi-Server Discovery**
   - Avahi/mDNS auto-discovery for Snapcast servers
   - Manual server configuration via environment variables
   - JSON-based server list

2. **WebSocket Connection Management**
   - Concurrent connections to multiple Snapcast servers
   - Automatic reconnection with exponential backoff
   - Music Assistant compatibility mode (one-shot requests)

3. **REST API**
   - `GET /api/federation/status` - All servers, streams, clients
   - `POST /api/federation/route` - Client routing (same-server + local cross-server)
   - `POST /api/federation/volume` - Volume control for any client
   - `POST /api/federation/control` - Stream control for any stream

4. **Frontend Integration**
   - Unified view of all streams and clients
   - Server badges showing origin
   - Cross-server routing for local clients
   - Volume control for all clients
   - Stream controls for all streams

5. **Music Assistant Compatibility**
   - Automatic detection of MA servers (by name)
   - One-shot WebSocket mode (workaround for MA bug where it stops responding after first request)
   - Explicit status refresh after commands (MA doesn't send event notifications)

### What Works

- ✅ View streams from all servers in one UI
- ✅ View clients from all servers in one UI
- ✅ Control volume for ANY client (local or remote)
- ✅ Control playback for ANY stream (local or remote)
- ✅ Route local snapclient to streams on any server
- ✅ Route clients to streams on same server
- ✅ Automatic server discovery via Avahi/mDNS
- ✅ Manual server configuration
- ✅ Real-time updates via polling

### What Doesn't Work

- ❌ Cross-server routing for third-party clients (Music Assistant, etc.)
- ❌ WebSocket updates (currently uses polling)
- ❌ Multiple AirPlay instances (planned for future)

### Recent Fixes (December 2024)

1. **Auto-Discovery Port Fix** (discovery.py:186)
   - Issue: Avahi discovery was using advertised port 1705 (Snapcast control port)
   - Fix: Hardcoded port 1780 (HTTP/WebSocket port) for all discovered servers
   - Impact: Auto-discovered servers now connect properly without manual configuration

2. **Stream Routing Revert Fix** (App.tsx)
   - Issue: User stream changes reverted within 5 seconds due to polling conflicts
   - Root Cause: Grace period (3s) shorter than polling interval (5s), stale closure bug
   - Fix: Extended grace period to 7 seconds + added `recentUserChangesRef` to prevent stale closures
   - Impact: Stream changes now persist reliably without reverting

3. **Local Server Detection** (App.tsx)
   - Issue: Hardcoded "server-localhost-" prefix failed for servers with different IDs
   - Fix: Added helper functions `getLocalServer()` and `isLocalId()` that use actual server list
   - Impact: Properly routes local vs remote clients regardless of server configuration

### Known Limitations

1. **Music Assistant Bug**: MA's Snapcast server responds to first WebSocket request but stops responding to subsequent requests on same connection. Workaround: One-shot mode creates new connection per request.

2. **No Event Notifications**: Some servers (like Music Assistant) don't send Snapcast event notifications (`Client.OnVolumeChanged`, etc.). Workaround: Explicit `Server.GetStatus` after every command.

3. **Cross-Server Routing**: Snapcast API doesn't support remotely changing a client's server. Only clients with shell access can be routed cross-server.

## Implementation Plan

### Phase 1: Federation Service Backend ✅ COMPLETED

#### 1.1 Server Discovery Module
- Avahi/mDNS discovery for `_snapcast-jsonrpc._tcp` services
- Manual server configuration support
- Connection health monitoring

#### 1.2 Multi-Server WebSocket Manager
- Concurrent WebSocket connections to multiple servers
- Reconnection logic with exponential backoff
- Event aggregation from all servers

#### 1.3 REST API Implementation
- Flask/FastAPI service
- Endpoints: /servers, /streams, /clients, /route, /volume
- Cross-server routing logic

#### 1.4 Snapclient Reconfiguration
- API to dynamically change snapclient's target server
- Supervisord integration for restart handling

### Phase 2: Frontend Updates ✅ COMPLETED

#### 2.1 Federation API Client ✅
- Replaced direct Snapcast WebSocket with Federation REST API
- Implemented polling for real-time updates

#### 2.2 Type Updates ✅
- Added server context to Stream and Client types
- Added federation settings to configuration

#### 2.3 Component Updates ✅
- StreamSelector: Shows server badges, cross-server compatible
- ClientManager: Server context display, cross-server routing
- ServerManager: New component for viewing connected servers

#### 2.4 Matrix View ⏸️ Deferred
- Future enhancement
- Would provide grid-style routing interface

### Phase 3: Multi-AirPlay Support ⏸️ Planned

#### 3.1 Multiple Shairport-Sync Instances
- Supervisord configs for N instances
- Unique Avahi names per instance
- Individual FIFOs per instance

#### 3.2 Dynamic Configuration
- Environment variable: `AIRPLAY_INSTANCES=3`
- Auto-generate shairport-sync configs
- Auto-generate Snapserver stream sources

#### 3.3 Documentation
- Configuration guide for multi-source setup
- Scaling recommendations

## File Structure

```
backend/
├── scripts/
│   ├── federation/
│   │   ├── __init__.py
│   │   ├── service.py           # Main Federation Service
│   │   ├── discovery.py         # Avahi/mDNS server discovery
│   │   ├── websocket_manager.py # Multi-server WebSocket handling
│   │   ├── router.py            # Cross-server routing logic
│   │   └── api.py               # REST API endpoints
│   └── setup.sh                 # Updated for multi-AirPlay
├── config/
│   └── supervisord/
│       ├── federation.ini       # Federation service config
│       └── shairport-multi.ini  # Multi-instance AirPlay (generated)

frontend/
├── services/
│   ├── federationService.ts     # New: Federation API client
│   └── snapcastService.ts       # Existing (kept for direct mode)
├── components/
│   ├── StreamSelector.tsx       # Updated: grouped by server
│   ├── ClientManager.tsx        # Updated: cross-server routing
│   ├── ServerManager.tsx        # New: server management
│   └── Settings.tsx             # Updated: federation settings
└── types.ts                     # Updated with server context
```

## Configuration

### Environment Variables

```bash
# Federation
FEDERATION_ENABLED=1
FEDERATION_AUTO_DISCOVER=1
FEDERATION_LOCAL_NAME="Main Server"
FEDERATION_MANUAL_SERVERS=""  # JSON array of {host, port, name}

# Multi-AirPlay
AIRPLAY_INSTANCES=3
AIRPLAY_BASE_NAME="Plum Audio Zone"

# Multi-Bluetooth (future)
BLUETOOTH_INSTANCES=1
```

### Manual Server Configuration

If auto-discovery is disabled or additional servers need manual configuration:

```json
[
  {"host": "192.168.7.226", "port": 1780, "name": "Music Assistant"},
  {"host": "192.168.7.227", "port": 1780, "name": "Kitchen Pi"}
]
```

## Deployment Considerations

### Main Server (Recommended Setup)
- Wired Gigabit Ethernet connection
- Beefy CPU for audio processing
- Runs full Plum-Snapcast with all sources enabled
- Federation Service runs here (or any server)
- Multiple AirPlay instances for concurrent users

### Satellite Endpoints (WiFi Pis)
- Snapclient-only OR full Plum-Snapcast
- If full: provides additional local sources
- Connects to any server's streams via Federation routing

### Receive-Only Endpoints
- Snapclient only (not full Plum-Snapcast container)
- Minimal resource usage
- Federation routes by reconfiguring snapclient target

## Future Enhancements

1. **WebSocket for real-time updates**: Replace polling with WebSocket from Federation Service
2. **Multiple AirPlay instances**: Support concurrent users on same server
3. **Stream priority/presets**: Save common routing configurations
4. **Auto-failover**: If a server goes down, reroute clients automatically
5. **Matrix View**: Grid-style routing interface (sources × destinations)
6. **Bandwidth monitoring**: Show network utilization per stream
7. **Access control**: Per-user routing permissions

## Troubleshooting

### Music Assistant Clients Not Routing Cross-Server

**Expected behavior**: Music Assistant's clients cannot be routed to streams on other servers.

**Reason**: Snapcast has no API to remotely change a client's server connection. Cross-server routing requires shell access to reconfigure and restart the snapclient process. Music Assistant controls its own clients.

**Workaround**: Use Music Assistant's interface to control those clients, or route your local clients to Music Assistant's streams instead.

### Volume Sliders Reverting After Changes

**Cause**: Server doesn't send event notifications after volume changes.

**Fixed**: Federation service now explicitly refreshes status after volume commands.

### Commands Timing Out After 30 Seconds

**Cause**: Music Assistant's Snapcast server bug - stops responding after first request on persistent WebSocket connection.

**Fixed**: Automatic detection and one-shot mode enabled for servers with "music" or "ma" in name.

## References

- [Snapcast GitHub](https://github.com/badaix/snapcast)
- [Snapcast JSON-RPC API](https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/)
- [Snapcast Configuration](https://github.com/badaix/snapcast/blob/develop/doc/configuration.md)
- [Avahi Service Discovery](https://avahi.org/)
