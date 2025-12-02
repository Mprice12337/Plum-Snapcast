# Federation Architecture for Multi-Server Snapcast

> **Status**: Planned
> **Branch**: `feature/federation-layer`
> **Author**: Claude + Michael Price
> **Date**: December 2024

## Overview

The Federation Layer enables a unified control plane for multiple Snapcast servers, allowing any stream from any server to be routed to any client across the network. This creates a pro-AV style audio matrix where sources and destinations can be freely interconnected.

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
2. If client is on different server:
   a. Reconfigure snapclient to connect to target server
   b. Wait for client to appear on target server
   c. Assign client to requested stream
3. If client is on same server:
   a. Simply assign client to stream via JSON-RPC

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

## Implementation Plan

### Phase 1: Federation Service Backend (~10 hours)

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

### Phase 2: Frontend Updates (~6 hours)

#### 2.1 Federation API Client
- Replace direct Snapcast WebSocket with Federation REST API
- Polling for real-time updates (or WebSocket upgrade later)

#### 2.2 Type Updates
- Add server context to Stream and Client types
- New Server type and federation settings

#### 2.3 Component Updates
- StreamSelector: Group streams by server
- ClientManager: Show server context, cross-server routing
- Settings: Federation configuration panel
- New: ServerManager component

#### 2.4 Matrix View (Optional)
- Sources × Destinations grid view
- One-click routing like pro-AV control systems

### Phase 3: Multi-AirPlay Support (~4 hours)

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
2. **Stream priority/presets**: Save common routing configurations
3. **Auto-failover**: If a server goes down, reroute clients automatically
4. **Bandwidth monitoring**: Show network utilization per stream
5. **Access control**: Per-user routing permissions
6. **Mobile app**: Native iOS/Android control app

## References

- [Snapcast GitHub](https://github.com/badaix/snapcast)
- [Snapcast JSON-RPC API](https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/)
- [Snapcast Configuration](https://github.com/badaix/snapcast/blob/develop/doc/configuration.md)
- [Avahi Service Discovery](https://avahi.org/)
