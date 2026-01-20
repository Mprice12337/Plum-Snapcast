# Federation & Control API Reference

> **Purpose**: Complete API documentation for integrating with Plum-Snapcast, including federation features and endpoint control. Designed for third-party integrations like ESPHome, Home Assistant, and custom clients.

**Version**: 1.0.0
**Last Updated**: 2026-01-19

---

## Table of Contents

1. [Overview](#1-overview)
2. [Connection & Authentication](#2-connection--authentication)
3. [Snapcast JSON-RPC 2.0 API (WebSocket)](#3-snapcast-json-rpc-20-api-websocket)
4. [Federation API (REST)](#4-federation-api-rest)
5. [Playback Position API](#5-playback-position-api)
6. [Settings API](#6-settings-api)
7. [Integrations API](#7-integrations-api)
8. [Audio Configuration API](#8-audio-configuration-api)
9. [Source Volume Control](#9-source-volume-control)
10. [Stream Lifecycle](#10-stream-lifecycle)
11. [Data Types & Schemas](#11-data-types--schemas)
12. [Error Handling](#12-error-handling)
13. [ESPHome Integration Guide](#13-esphome-integration-guide)
14. [Example Workflows](#14-example-workflows)

---

## 1. Overview

### 1.1. Architecture Summary

Plum-Snapcast exposes multiple APIs for different purposes:

| API | Protocol | Port | Purpose |
|-----|----------|------|---------|
| **Snapcast Control** | WebSocket JSON-RPC 2.0 | 1788 (HTTPS) / 1780 (HTTP) | Real-time audio control, stream/client/group management |
| **Federation** | REST HTTP | 5001 | Multi-server discovery, cross-server routing, unified control |
| **Playback Position** | REST HTTP | 5001 | Track position/duration for progress bars |
| **Settings** | REST HTTP | 5002 | Device configuration, integration settings |
| **Integrations** | REST HTTP | 5003 | Enable/disable sources, manage endpoints |
| **Audio** | REST HTTP | 5004 | Output/input device configuration, source volume |

### 1.2. Non-Federation vs Federation Mode

**Non-Federation Mode** (default):
- Single server deployment
- All APIs work with local streams/clients
- Federation API returns only local server data
- Suitable for simple setups

**Federation Mode** (enabled in settings):
- Multiple Plum-Snapcast servers on network
- Automatic server discovery via mDNS
- Cross-server audio routing
- Unified view of all streams/clients
- Federated IDs for addressing remote resources

### 1.3. Quick Start

```bash
# Test Snapcast WebSocket connection
wscat -c wss://192.168.1.100:1788/jsonrpc --no-check

# Get server status
curl http://192.168.1.100:5001/api/federation/status

# Get all playback positions
curl http://192.168.1.100:5001/api/playback
```

---

## 2. Connection & Authentication

### 2.1. Network Requirements

- **Layer 2 Network**: Required for mDNS/Avahi discovery
- **Host Networking**: Plum-Snapcast uses `network_mode: host`
- **Ports**: See port table above (typically all on same IP)

### 2.2. Authentication

Currently, Plum-Snapcast is designed for **trusted local networks only**:
- No authentication on any API
- All endpoints accessible without credentials
- For remote access, use a reverse proxy with authentication

### 2.3. TLS/SSL

- **HTTPS Available**: Port 1788 for Snapcast WebSocket (self-signed cert)
- **HTTP Alternative**: Port 1780 for non-TLS WebSocket
- **REST APIs**: Currently HTTP only (behind nginx proxy on port 3000)

### 2.4. CORS

REST APIs include CORS headers for browser-based clients:
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

---

## 3. Snapcast JSON-RPC 2.0 API (WebSocket)

The primary real-time control interface for Snapcast. All audio control goes through this API.

### 3.1. Connection

```javascript
// JavaScript WebSocket connection
const ws = new WebSocket('wss://192.168.1.100:1788/jsonrpc');

// For self-signed certs, may need to accept certificate first
// Or use HTTP: ws://192.168.1.100:1780/jsonrpc

ws.onopen = () => {
  console.log('Connected to Snapcast');
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.method) {
    // Server notification
    console.log('Notification:', msg.method, msg.params);
  } else if (msg.result) {
    // Response to request
    console.log('Response:', msg.result);
  }
};
```

### 3.2. Request Format

```json
{
  "jsonrpc": "2.0",
  "method": "Method.Name",
  "params": { /* method-specific parameters */ },
  "id": 1
}
```

- `id`: Must be unique per request (integer or string)
- Response will include same `id` for correlation

### 3.3. Core Methods

#### Server.GetStatus

Get complete server state including all groups, streams, and clients.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "Server.GetStatus",
  "id": 1
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "server": {
      "host": {
        "arch": "aarch64",
        "ip": "192.168.1.100",
        "mac": "dc:a6:32:xx:xx:xx",
        "name": "plum-snapcast",
        "os": "Alpine Linux v3.19"
      },
      "snapserver": {
        "controlProtocolVersion": 1,
        "name": "Snapserver",
        "protocolVersion": 1,
        "version": "0.27.0"
      }
    },
    "groups": [
      {
        "id": "b8e3f9a2-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "name": "",
        "stream_id": "AirPlay - Living Room",
        "muted": false,
        "clients": [
          {
            "id": "dc:a6:32:xx:xx:xx",
            "connected": true,
            "config": {
              "name": "Snapclient",
              "volume": {"percent": 80, "muted": false}
            }
          }
        ]
      }
    ],
    "streams": [
      {
        "id": "AirPlay - Living Room",
        "status": "playing",
        "uri": {
          "raw": "pipe:///tmp/airplay-1-fifo?name=AirPlay%20-%20Living%20Room",
          "scheme": "pipe",
          "host": "",
          "path": "/tmp/airplay-1-fifo",
          "query": {"name": "AirPlay - Living Room"}
        },
        "properties": {
          "canControl": true,
          "canGoNext": true,
          "canGoPrevious": true,
          "canPause": true,
          "canPlay": true,
          "canSeek": false,
          "metadata": {
            "title": "Track Name",
            "artist": ["Artist Name"],
            "album": "Album Name",
            "artUrl": "data:image/jpeg;base64,/9j/4AAQ...",
            "duration": 180000
          },
          "playbackStatus": "playing"
        }
      }
    ]
  },
  "id": 1
}
```

#### Client.SetVolume

Set volume for a specific client.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "Client.SetVolume",
  "params": {
    "id": "dc:a6:32:xx:xx:xx",
    "volume": {"percent": 75, "muted": false}
  },
  "id": 2
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "volume": {"percent": 75, "muted": false}
  },
  "id": 2
}
```

#### Group.SetStream

Change which stream a group is listening to.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "Group.SetStream",
  "params": {
    "id": "b8e3f9a2-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "stream_id": "Spotify - Office"
  },
  "id": 3
}
```

#### Group.SetMute

Mute/unmute an entire group.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "Group.SetMute",
  "params": {
    "id": "b8e3f9a2-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "mute": true
  },
  "id": 4
}
```

#### Stream.Control

Send playback control commands to a stream.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "Stream.Control",
  "params": {
    "id": "AirPlay - Living Room",
    "command": "pause"
  },
  "id": 5
}
```

**Valid Commands:**
- `play` - Resume playback
- `pause` - Pause playback
- `playPause` - Toggle play/pause
- `stop` - Stop playback
- `next` - Skip to next track
- `previous` - Skip to previous track

**Note:** Not all sources support all commands. Check `canControl`, `canPause`, etc. in stream properties.

#### Stream.AddStream

Dynamically add a new stream (used by lifecycle managers).

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "Stream.AddStream",
  "params": {
    "streamUri": "pipe:///tmp/spotify-fifo?name=Spotify%20-%20Office&sampleformat=44100:16:2"
  },
  "id": 6
}
```

#### Stream.RemoveStream

Remove a stream (used by lifecycle managers).

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "Stream.RemoveStream",
  "params": {
    "id": "Spotify - Office"
  },
  "id": 7
}
```

#### Stream.SetProperties

Update stream metadata (used by control scripts).

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "Stream.SetProperties",
  "params": {
    "id": "Spotify - Office",
    "properties": {
      "metadata": {
        "title": "New Track",
        "artist": ["New Artist"],
        "album": "New Album",
        "artUrl": "data:image/jpeg;base64,/9j/4AAQ...",
        "duration": 240000
      },
      "playbackStatus": "playing"
    }
  },
  "id": 8
}
```

### 3.4. Server Notifications

The server sends notifications for state changes. These have no `id` field.

#### Server.OnUpdate

Full server state update (sent on any change).

```json
{
  "jsonrpc": "2.0",
  "method": "Server.OnUpdate",
  "params": {
    "server": { /* full server state */ }
  }
}
```

#### Client.OnVolumeChanged

```json
{
  "jsonrpc": "2.0",
  "method": "Client.OnVolumeChanged",
  "params": {
    "id": "dc:a6:32:xx:xx:xx",
    "volume": {"percent": 80, "muted": false}
  }
}
```

#### Client.OnConnect / Client.OnDisconnect

```json
{
  "jsonrpc": "2.0",
  "method": "Client.OnConnect",
  "params": {
    "client": { /* client object */ }
  }
}
```

#### Stream.OnProperties

```json
{
  "jsonrpc": "2.0",
  "method": "Stream.OnProperties",
  "params": {
    "id": "AirPlay - Living Room",
    "properties": { /* updated properties */ }
  }
}
```

---

## 4. Federation API (REST)

Unified control plane for single or multiple Plum-Snapcast servers.

**Base URL:** `http://<host>:5001/api/federation`

### 4.1. Server Discovery

#### List Discovered Servers

```http
GET /api/federation/servers
```

**Response:**
```json
[
  {
    "id": "server-192-168-1-100",
    "name": "Living Room Snapcast",
    "host": "192.168.1.100",
    "port": 1788,
    "connected": true,
    "last_seen": 1735600000.0,
    "is_local": true
  },
  {
    "id": "server-192-168-1-101",
    "name": "Kitchen Snapcast",
    "host": "192.168.1.101",
    "port": 1788,
    "connected": true,
    "last_seen": 1735600050.0,
    "is_local": false
  }
]
```

### 4.2. Aggregated Status

#### Get Federation Status

Returns streams and clients from all connected servers with federated IDs.

```http
GET /api/federation/status
```

**Response:**
```json
{
  "success": true,
  "servers": [
    {
      "id": "server-192-168-1-100",
      "name": "Living Room",
      "host": "192.168.1.100",
      "connected": true,
      "streams": [
        {
          "id": "server-192-168-1-100-airplay1",
          "friendlyId": "airplay1",
          "localId": "AirPlay - Living Room",
          "name": "AirPlay - Living Room",
          "status": "playing",
          "properties": {
            "metadata": {
              "title": "Song Title",
              "artist": ["Artist"],
              "album": "Album",
              "artUrl": "data:image/jpeg;base64,..."
            },
            "playbackStatus": "playing"
          }
        }
      ],
      "groups": [
        {
          "id": "server-192-168-1-100-group1",
          "friendlyId": "group1",
          "name": "Living Room",
          "stream_id": "server-192-168-1-100-airplay1",
          "muted": false,
          "clients": ["server-192-168-1-100-client1"]
        }
      ],
      "clients": [
        {
          "id": "server-192-168-1-100-dc:a6:32:xx:xx:xx",
          "friendlyId": "dc:a6:32:xx:xx:xx",
          "name": "Snapclient",
          "connected": true,
          "volume": {"percent": 80, "muted": false},
          "group_id": "server-192-168-1-100-group1"
        }
      ]
    }
  ]
}
```

### 4.3. Federated ID Format

All resources in federation mode use federated IDs:

```
server-{ip-with-dashes}-{local-id}
```

Examples:
- `server-192-168-1-100-airplay1` - Stream on 192.168.1.100
- `server-192-168-1-100-dc:a6:32:xx:xx:xx` - Client MAC address
- `server-192-168-1-100-group1` - Group on 192.168.1.100

The API automatically translates between federated and local IDs.

### 4.4. Active Endpoint

#### Get Active Endpoint

Returns which client/stream is currently active (outputting audio).

```http
GET /api/federation/active-endpoint
```

**Response:**
```json
{
  "success": true,
  "server_id": "server-192-168-1-100",
  "client_id": "server-192-168-1-100-dc:a6:32:xx:xx:xx",
  "stream_id": "server-192-168-1-100-airplay1",
  "is_active": true
}
```

### 4.5. Cross-Server Routing

#### Route Client to Stream

Route any client to any stream across the federation.

```http
POST /api/federation/route
Content-Type: application/json

{
  "client_id": "server-192-168-1-100-dc:a6:32:xx:xx:xx",
  "stream_id": "server-192-168-1-101-spotify1"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Client routed to stream",
  "client_id": "server-192-168-1-100-dc:a6:32:xx:xx:xx",
  "stream_id": "server-192-168-1-101-spotify1"
}
```

**Cross-Server Routing Flow:**
1. Deactivate all currently active endpoints
2. Find/create remote snapclient on target server
3. Route remote snapclient to desired stream
4. Route local output client through remote connection

### 4.6. Volume Control

#### Set Client Volume

```http
POST /api/federation/volume
Content-Type: application/json

{
  "client_id": "server-192-168-1-100-dc:a6:32:xx:xx:xx",
  "volume": 75
}
```

**Response:**
```json
{
  "success": true,
  "message": "Volume set to 75%",
  "client_id": "server-192-168-1-100-dc:a6:32:xx:xx:xx",
  "volume": 75
}
```

### 4.7. Playback Control

#### Send Control Command

```http
POST /api/federation/control
Content-Type: application/json

{
  "stream_id": "server-192-168-1-100-spotify1",
  "command": "pause"
}
```

**Valid Commands:** `play`, `pause`, `stop`, `next`, `previous`

**Response:**
```json
{
  "success": true,
  "message": "Command 'pause' sent to stream",
  "stream_id": "server-192-168-1-100-spotify1"
}
```

---

## 5. Playback Position API

Real-time track position tracking, independent from Snapcast to avoid audio stuttering.

**Base URL:** `http://<host>:5001/api/playback`

### 5.1. Get All Positions

```http
GET /api/playback
```

**Response:**
```json
{
  "success": true,
  "streams": {
    "AirPlay - Living Room": {
      "stream_id": "AirPlay - Living Room",
      "position": 45000,
      "duration": 180000,
      "playback_status": "playing",
      "interpolated_position": 47500,
      "last_update": 1735600000.0,
      "position_timestamp": 1735599998.0,
      "age_seconds": 2.5,
      "is_stale": false
    },
    "Spotify - Office": {
      "stream_id": "Spotify - Office",
      "position": 120000,
      "duration": 240000,
      "playback_status": "paused",
      "interpolated_position": 120000,
      "last_update": 1735600000.0,
      "position_timestamp": 1735599990.0,
      "age_seconds": 10.0,
      "is_stale": false
    }
  }
}
```

### 5.2. Get Specific Stream Position

```http
GET /api/playback/{stream_id}
```

**Example:**
```http
GET /api/playback/AirPlay%20-%20Living%20Room
```

**Response:**
```json
{
  "success": true,
  "stream_id": "AirPlay - Living Room",
  "position": 45000,
  "duration": 180000,
  "playback_status": "playing",
  "interpolated_position": 47500,
  "last_update": 1735600000.0,
  "position_timestamp": 1735599998.0,
  "age_seconds": 2.5,
  "is_stale": false
}
```

### 5.3. Position Fields Explained

| Field | Description |
|-------|-------------|
| `position` | Last reported position in milliseconds |
| `duration` | Track duration in milliseconds |
| `playback_status` | `playing`, `paused`, or `stopped` |
| `interpolated_position` | Server-calculated current position (position + elapsed time if playing) |
| `last_update` | Unix timestamp of last heartbeat (any update) |
| `position_timestamp` | Unix timestamp of last position change |
| `age_seconds` | Seconds since last update |
| `is_stale` | True if >30 seconds since last update |

### 5.4. Update Position (for control scripts)

Used by control scripts to report position changes.

```http
POST /api/playback/{stream_id}
Content-Type: application/json

{
  "position": 45000,
  "duration": 180000,
  "playback_status": "playing",
  "title": "Track Name",
  "artist": "Artist Name"
}
```

### 5.5. Delete Position

Remove position data for a stream (called when stream is removed).

```http
DELETE /api/playback/{stream_id}
```

---

## 6. Settings API

Device configuration and integration settings.

**Base URL:** `http://<host>:5002/api/settings`

### 6.1. Get Current Settings

```http
GET /api/settings
```

**Response:**
```json
{
  "version": 42,
  "deviceName": "Plum Snapcast",
  "hostname": "plum-snapcast",
  "integrations": {
    "airplay": {
      "endpoints": [
        {
          "id": "1",
          "enabled": true,
          "deviceName": "Living Room",
          "port": 5050,
          "udpPortBase": 6001
        }
      ]
    },
    "bluetooth": {
      "enabled": false,
      "deviceName": "Plum Audio",
      "autoPair": true,
      "discoverable": true
    },
    "spotify": {
      "bitrate": 320,
      "endpoints": [
        {
          "id": "1",
          "enabled": true,
          "deviceName": "Living Room Spotify",
          "zeroconfPort": 5354
        }
      ]
    },
    "dlna": {
      "endpoints": []
    },
    "plexamp": {
      "available": false,
      "enabled": false,
      "sourceName": "Plexamp"
    },
    "visualizer": {
      "enabled": true,
      "theme": "user"
    }
  },
  "federation": {
    "enabled": false,
    "autoDiscover": true
  },
  "audio": {
    "output": {
      "device": "hw:Headphones",
      "device_type": "BUILTIN_HEADPHONES"
    },
    "input": {
      "devices": []
    }
  }
}
```

### 6.2. Update Settings

Partial updates supported - only include fields to change.

```http
POST /api/settings
Content-Type: application/json

{
  "deviceName": "Kitchen Snapcast",
  "integrations": {
    "bluetooth": {
      "enabled": true
    }
  }
}
```

**Response:** Updated settings with incremented `version`.

### 6.3. Update Device Name/Hostname

```http
POST /api/settings/device
Content-Type: application/json

{
  "deviceName": "Kitchen Audio",
  "hostname": "kitchen-audio"
}
```

**Side Effects:**
- Updates Avahi configuration
- Restarts Avahi service for mDNS changes
- May briefly interrupt service discovery

---

## 7. Integrations API

Enable/disable audio source integrations and manage multi-instance endpoints.

**Base URL:** `http://<host>:5003/api/integrations`

### 7.1. Integration Status

#### Get Status

```http
GET /api/integrations/{integration}/status
```

**Integrations:** `airplay`, `bluetooth`, `spotify`, `dlna`, `plexamp`

**Response:**
```json
{
  "running": true,
  "status": "running",
  "enabled": true,
  "endpoint_count": 2
}
```

### 7.2. Enable/Disable

```http
POST /api/integrations/{integration}/enable
POST /api/integrations/{integration}/disable
```

**Response:**
```json
{
  "success": true,
  "message": "Spotify enabled",
  "status": "running"
}
```

### 7.3. Multi-Instance Endpoints

AirPlay, Spotify, and DLNA support up to 10 simultaneous endpoints.

#### List Endpoints

```http
GET /api/integrations/{integration}/endpoints
```

**AirPlay Response:**
```json
{
  "success": true,
  "endpoints": [
    {
      "id": "1",
      "enabled": true,
      "deviceName": "Living Room",
      "port": 5050,
      "udpPortBase": 6001
    },
    {
      "id": "2",
      "enabled": true,
      "deviceName": "Kitchen",
      "port": 5051,
      "udpPortBase": 6011
    }
  ]
}
```

#### Add Endpoint

```http
POST /api/integrations/{integration}/endpoints
Content-Type: application/json

{
  "deviceName": "Bedroom",
  "enabled": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Endpoint added",
  "endpoint": {
    "id": "3",
    "enabled": true,
    "deviceName": "Bedroom",
    "port": 5052,
    "udpPortBase": 6021
  }
}
```

#### Update Endpoint

```http
PUT /api/integrations/{integration}/endpoints/{id}
Content-Type: application/json

{
  "deviceName": "Master Bedroom",
  "enabled": true
}
```

#### Delete Endpoint

```http
DELETE /api/integrations/{integration}/endpoints/{id}
```

**Note:** Cannot delete the last endpoint.

### 7.4. Bluetooth Settings

```http
POST /api/integrations/bluetooth/settings
Content-Type: application/json

{
  "autoPair": true,
  "discoverable": true
}
```

### 7.5. Spotify Bitrate

```http
POST /api/integrations/spotify/bitrate
Content-Type: application/json

{
  "bitrate": 320
}
```

**Valid values:** 96, 160, 320

**Warning:** Restarts all Spotify instances.

---

## 8. Audio Configuration API

Audio device discovery and configuration.

**Base URL:** `http://<host>:5004/api/audio`

### 8.1. List Output Devices

```http
GET /api/audio/devices/output
```

**Response:**
```json
[
  {
    "hw_id": "hw:Headphones",
    "hw_name": "bcm2835 - Headphones",
    "friendly_name": "Raspberry Pi Headphones",
    "type": "BUILTIN_HEADPHONES",
    "is_available": true
  },
  {
    "hw_id": "hw:Device,0",
    "hw_name": "USB Audio Device",
    "friendly_name": "USB Audio Device",
    "type": "USB_AUDIO",
    "is_available": true
  }
]
```

### 8.2. Get Current Output

```http
GET /api/audio/output/current
```

### 8.3. Set Output Device

```http
POST /api/audio/output/device
Content-Type: application/json

{
  "hw_id": "hw:Headphones"
}
```

**Side Effects:**
- Stops snapclient service
- Restarts with new device
- Brief audio interruption

### 8.4. Test Output Device

```http
POST /api/audio/output/test
Content-Type: application/json

{
  "hw_id": "hw:Headphones"
}
```

Plays a brief test tone through the specified device.

### 8.5. Input Devices (BETA)

```http
GET /api/audio/devices/input
GET /api/audio/input/devices
POST /api/audio/input/device
DELETE /api/audio/input/device/{hw_id}
POST /api/audio/input/device/{hw_id}/toggle
```

---

## 9. Source Volume Control

Control volume at the audio source level (not Snapcast client volume).

**Base URL:** `http://<host>:5004/api/audio`

### 9.1. Set Source Volume

```http
POST /api/audio/source-volume
Content-Type: application/json

{
  "streamId": "AirPlay - Living Room",
  "volume": 80
}
```

**Volume Range:** 0-100

**Response:**
```json
{
  "success": true,
  "message": "Volume set to 80%"
}
```

### 9.2. Get Source Volume

```http
GET /api/audio/source-volume?streamId=AirPlay%20-%20Living%20Room
```

**Response:**
```json
{
  "success": true,
  "volume": 80,
  "message": "Volume: 80%"
}
```

### 9.3. Source-Specific Volume Mechanisms

| Source | Mechanism |
|--------|-----------|
| AirPlay | D-Bus MPRIS SetVolume |
| Spotify | D-Bus MPRIS Properties.Set |
| Bluetooth | AVRCP Absolute Volume (0-127 internal) |
| DLNA | GStreamer volume control |
| Plexamp | HTTP API `/player/playback/setParameters?volume=` |

---

## 10. Stream Lifecycle

Understanding when streams appear and disappear.

### 10.1. Dynamic Lifecycle

Streams are created dynamically when activity is detected and removed after idle timeout:

| State | Description | FIFO Status |
|-------|-------------|-------------|
| **IDLE** | Service discoverable, no stream | FIFO keeper drains pipe |
| **ACTIVE** | Stream exists, control script running | Snapcast reads pipe |
| **REMOVING** | Cleanup in progress | Transitioning |

### 10.2. Idle Timeouts

| Integration | Timeout |
|-------------|---------|
| AirPlay | 10 seconds |
| Bluetooth | 10 seconds |
| Spotify | 10 seconds |
| DLNA | 10 seconds |
| Plexamp | 30 seconds |

### 10.3. Stream Names

Streams use predictable naming:

```
{Integration} - {Endpoint Name}
```

Examples:
- `AirPlay - Living Room`
- `Spotify - Kitchen`
- `Bluetooth`
- `Plexamp`
- `DLNA - Office`

### 10.4. Programmatic Stream Creation

**Note:** Streams are managed automatically by lifecycle managers. Manual creation is possible but not recommended:

```json
{
  "jsonrpc": "2.0",
  "method": "Stream.AddStream",
  "params": {
    "streamUri": "pipe:///tmp/custom-fifo?name=Custom%20Stream&sampleformat=44100:16:2"
  },
  "id": 1
}
```

---

## 11. Data Types & Schemas

### 11.1. Volume Object

```typescript
interface Volume {
  percent: number;  // 0-100
  muted: boolean;
}
```

### 11.2. Client Object

```typescript
interface Client {
  id: string;           // MAC address or unique ID
  connected: boolean;
  config: {
    name: string;
    volume: Volume;
    instance: number;
  };
  host: {
    arch: string;
    ip: string;
    mac: string;
    name: string;
    os: string;
  };
  lastSeen: {
    sec: number;
    usec: number;
  };
}
```

### 11.3. Stream Object

```typescript
interface Stream {
  id: string;           // Stream name
  status: "idle" | "playing" | "unknown";
  uri: {
    raw: string;
    scheme: string;
    host: string;
    path: string;
    query: Record<string, string>;
  };
  properties: StreamProperties;
}

interface StreamProperties {
  canControl: boolean;
  canGoNext: boolean;
  canGoPrevious: boolean;
  canPause: boolean;
  canPlay: boolean;
  canSeek: boolean;
  metadata: StreamMetadata;
  playbackStatus: "playing" | "paused" | "stopped";
}

interface StreamMetadata {
  title?: string;
  artist?: string[];
  album?: string;
  artUrl?: string;      // data:image/jpeg;base64,... or http URL
  duration?: number;    // milliseconds
  trackNumber?: number;
}
```

### 11.4. Group Object

```typescript
interface Group {
  id: string;           // UUID
  name: string;
  stream_id: string;
  muted: boolean;
  clients: Client[];
}
```

### 11.5. Endpoint Object (AirPlay/Spotify/DLNA)

```typescript
interface Endpoint {
  id: string;           // "1", "2", etc.
  enabled: boolean;
  deviceName: string;
  port: number;         // Integration-specific port
  // AirPlay only:
  udpPortBase?: number;
  // DLNA only:
  uuid?: string;
  // Spotify only:
  zeroconfPort?: number;
}
```

---

## 12. Error Handling

### 12.1. REST API Errors

**Error Response Format:**
```json
{
  "success": false,
  "error": "Error message",
  "details": "Additional information (optional)"
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad request (invalid parameters)
- `404` - Resource not found
- `500` - Internal server error

### 12.2. JSON-RPC Errors

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32602,
    "message": "Invalid params",
    "data": "Stream not found"
  },
  "id": 1
}
```

**Common Error Codes:**
- `-32700` - Parse error
- `-32600` - Invalid request
- `-32601` - Method not found
- `-32602` - Invalid params
- `-32603` - Internal error

### 12.3. WebSocket Reconnection

Implement exponential backoff for reconnection:

```javascript
let reconnectAttempts = 0;
const maxReconnectDelay = 30000;

function getReconnectDelay() {
  const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), maxReconnectDelay);
  reconnectAttempts++;
  return delay;
}

ws.onclose = () => {
  setTimeout(connect, getReconnectDelay());
};

ws.onopen = () => {
  reconnectAttempts = 0;
};
```

---

## 13. ESPHome Integration Guide

Guidelines for creating ESPHome-based Snapcast receive-only endpoints.

### 13.1. Architecture Overview

```
┌──────────────────────┐
│ Plum-Snapcast Server │
│   (192.168.1.100)    │
│                      │
│  Streams:            │
│  - AirPlay           │
│  - Spotify           │
│  - Bluetooth         │
└──────────┬───────────┘
           │ Snapcast protocol (1704/1705)
           │
    ┌──────┴──────┐
    │             │
┌───▼───┐   ┌────▼────┐
│ ESPHome│   │ ESPHome │
│ Client │   │ Client  │
│ Kitchen│   │ Bedroom │
└────────┘   └─────────┘
```

### 13.2. Required Capabilities

An ESPHome Snapcast endpoint should implement:

1. **Snapcast Client Protocol** - Connect to port 1704/1705
2. **Audio Playback** - I2S DAC or PWM output
3. **REST API Client** - For federation/control integration
4. **mDNS Discovery** - Find Snapcast servers on network

### 13.3. API Integration Points

**Discovery:**
```http
GET /api/federation/servers
# Find available Snapcast servers

GET /api/federation/status
# Get available streams
```

**Control:**
```http
POST /api/federation/route
{
  "client_id": "esphome-kitchen",
  "stream_id": "server-192-168-1-100-spotify1"
}
# Route this ESPHome device to a stream

POST /api/federation/volume
{
  "client_id": "esphome-kitchen",
  "volume": 75
}
# Set volume
```

**Monitoring:**
```http
GET /api/playback/{stream_id}
# Get current track position for display
```

### 13.4. WebSocket Events to Handle

Connect to WebSocket and listen for:

```javascript
// Volume change notification
{
  "method": "Client.OnVolumeChanged",
  "params": {"id": "esphome-kitchen", "volume": {...}}
}

// Stream switch notification
{
  "method": "Group.OnStreamChanged",
  "params": {"id": "group-id", "stream_id": "new-stream"}
}

// Metadata update
{
  "method": "Stream.OnProperties",
  "params": {"id": "stream-id", "properties": {...}}
}
```

### 13.5. ESPHome Component Pseudocode

```yaml
# esphome/snapcast_client.yaml (concept)
external_components:
  - source: github://user/esphome-snapcast

snapcast_client:
  server: auto  # or specific IP
  port: 1704
  name: "Kitchen Speaker"

  # Audio output
  i2s_dac:
    bck_pin: GPIO26
    ws_pin: GPIO25
    data_pin: GPIO22

  # Optional display
  on_metadata:
    - display.print: !lambda 'return x.title;'

  on_volume_change:
    - logger.log: "Volume changed"
```

### 13.6. Registration Flow

1. ESPHome device boots and discovers Snapcast server via mDNS
2. Connects to Snapcast as client (appears in client list)
3. Server assigns to default group
4. ESPHome can call REST APIs to switch streams or adjust volume
5. Audio streams via Snapcast protocol with sample-accurate sync

---

## 14. Example Workflows

### 14.1. Simple Volume Control

```javascript
// 1. Connect to WebSocket
const ws = new WebSocket('ws://192.168.1.100:1780/jsonrpc');

// 2. Get current state
ws.send(JSON.stringify({
  jsonrpc: "2.0",
  method: "Server.GetStatus",
  id: 1
}));

// 3. Find client ID from response, then set volume
ws.send(JSON.stringify({
  jsonrpc: "2.0",
  method: "Client.SetVolume",
  params: {
    id: "dc:a6:32:xx:xx:xx",
    volume: {percent: 50, muted: false}
  },
  id: 2
}));
```

### 14.2. Stream Switching

```javascript
// Get group ID and available streams from Server.GetStatus
// Then switch stream:
ws.send(JSON.stringify({
  jsonrpc: "2.0",
  method: "Group.SetStream",
  params: {
    id: "group-uuid-here",
    stream_id: "Spotify - Office"
  },
  id: 3
}));
```

### 14.3. Progress Bar with Position API

```javascript
// Poll every 2 seconds
setInterval(async () => {
  const response = await fetch(
    'http://192.168.1.100:5001/api/playback/AirPlay%20-%20Living%20Room'
  );
  const data = await response.json();

  if (data.success && !data.is_stale) {
    const progress = data.interpolated_position / data.duration;
    updateProgressBar(progress);
    updateTimeDisplay(data.interpolated_position, data.duration);
  }
}, 2000);
```

### 14.4. Cross-Server Routing (Federation)

```javascript
// Route local speaker to remote Spotify stream
const response = await fetch('http://192.168.1.100:5001/api/federation/route', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    client_id: 'server-192-168-1-100-dc:a6:32:xx:xx:xx',
    stream_id: 'server-192-168-1-101-spotify1'
  })
});
```

### 14.5. Enable Integration and Add Endpoint

```javascript
// 1. Enable Spotify integration
await fetch('http://192.168.1.100:5003/api/integrations/spotify/enable', {
  method: 'POST'
});

// 2. Add new Spotify endpoint
const endpoint = await fetch(
  'http://192.168.1.100:5003/api/integrations/spotify/endpoints',
  {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      deviceName: 'Office Spotify',
      enabled: true
    })
  }
);

// 3. New endpoint will appear as "Spotify - Office Spotify" in Spotify app
```

---

## Appendix A: Port Reference

| Port | Protocol | Service |
|------|----------|---------|
| 1704 | TCP | Snapcast client connections |
| 1705 | TCP | Snapcast client connections (alternative) |
| 1780 | HTTP/WS | Snapcast control (HTTP) |
| 1788 | HTTPS/WSS | Snapcast control (HTTPS) |
| 3000 | HTTP | Frontend web interface |
| 5001 | HTTP | Federation API / Playback API |
| 5002 | HTTP | Settings API |
| 5003 | HTTP | Integrations API |
| 5004 | HTTP | Audio API |
| 5050-5059 | TCP | AirPlay endpoints |
| 5353 | UDP | mDNS |
| 5354-5363 | TCP | Spotify Connect zeroconf |
| 6001-6100 | UDP | AirPlay RTP/timing |
| 49494-49503 | TCP | DLNA/UPnP endpoints |

## Appendix B: Stream URI Format

```
pipe://{path}?name={name}&sampleformat={rate}:{bits}:{channels}
```

**Examples:**
```
pipe:///tmp/airplay-1-fifo?name=AirPlay%20-%20Living%20Room&sampleformat=44100:16:2
pipe:///tmp/spotify-fifo?name=Spotify%20-%20Office&sampleformat=44100:16:2
pipe:///tmp/bluetooth-fifo?name=Bluetooth&sampleformat=44100:16:2
```

## Appendix C: mDNS Service Types

| Service | Type |
|---------|------|
| Snapcast | `_snapcast-http._tcp` |
| AirPlay | `_raop._tcp` |
| Spotify Connect | `_spotify-connect._tcp` |
| DLNA/UPnP | `_upnp._tcp` |

---

**Document Maintenance:** Update when APIs change, new integrations added, or federation features evolve.
