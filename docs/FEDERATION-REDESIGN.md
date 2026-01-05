# Multi-Server Federation Architecture Redesign

## Current Architecture Summary

**Current Approach: Physical Snapclient Reconnection**
- Single snapclient instance per device that physically reconnects to different servers
- Cross-server routing: Write target to `/app/data/snapclient_target` → restart snapclient → connect to remote server
- Downsides: Slow (18s wait time), complex reconnection logic, limited to local clients only

**Discovery & Connection:**
- Avahi/mDNS discovers `_snapcast-http._tcp` services
- WebSocket connections to each discovered server
- Federation API aggregates streams/clients from all servers
- Frontend polls every 5 seconds for updates

## Proposed Architecture

**New Approach: Multiple Snapclients with Stream Routing Lockout**

Instead of reconnecting ONE snapclient to different servers, create MULTIPLE snapclients that all output to the same audio device, with stream routing ensuring only one is active:

1. **Local Output Snapclient** (existing)
   - Connects to: Local snapserver (127.0.0.1:1705)
   - Outputs to: Hardware audio device (hw:Headphones)
   - Active when: Playing local streams
   - Inactive when: Routed to `none` stream (silence)

2. **Remote Output Snapclients** (new, one per discovered server)
   - Connects to: Remote snapserver (e.g., 192.168.1.133:1704)
   - Outputs to: Hardware audio device (hw:Headphones) - SAME as local
   - Active when: Playing remote streams from that server
   - Inactive when: Routed to `none` stream (silence)

3. **Stream Routing Lockout**
   - Federation service tracks which snapclient is currently "active"
   - Only ONE snapclient routed to actual stream at a time
   - All others routed to `none` stream (play silence)
   - Prevents multiple audio streams mixing on same output

**Example Scenario:**
- Server A (192.168.1.133) and Server B (192.168.1.138)
- Server A has TWO snapclients:
  - Local snapclient → connected to Server A (127.0.0.1:1705)
  - Remote snapclient → connected to Server B (192.168.1.138:1704)
- **Playing Local AirPlay:**
  - Local snapclient: Routed to `airplay` stream → plays to hw:Headphones
  - Remote snapclient: Routed to `none` stream → silent
- **Switch to Remote AirPlay on Server B:**
  - Local snapclient: Routed to `none` stream → silent
  - Remote snapclient: Routed to Server B's `airplay` stream → plays to hw:Headphones
- Result: Instant switching (stream routing) + single decode path (no FIFO re-encoding)

## Benefits

1. **Faster Switching**: Stream routing vs reconnection (~50ms vs 18s)
2. **No Dual Encoding**: Single decode path (server → snapclient → audio)
3. **Lower CPU Usage**: No FIFO re-encoding, single active decoder
4. **Lower Latency**: Direct audio path, no intermediate pipes
5. **Simpler Logic**: No snapclient target file, no restart coordination
6. **Better UX**: Instant response, consistent audio quality
7. **More Reliable**: No reconnection race conditions

## Implementation Plan

### Phase 1: Backend - Dynamic Remote Snapclient Management

**Files to modify:**
- `backend/scripts/federation/service.py` - Add remote snapclient lifecycle management
- `backend/scripts/federation/discovery.py` - Trigger snapclient creation/removal on server changes
- `backend/scripts/setup.sh` - Create remote snapclient stream templates

**Key Changes:**

1. **Create Remote Snapclient Manager** (new file: `backend/scripts/federation/remote_snapclient_manager.py`):
   ```python
   class RemoteSnapclientManager:
       def add_remote_server(server_id, host, port):
           # 1. Create FIFO pipe: /tmp/remote-{server_id}-fifo
           # 2. Add stream to snapserver via JSON-RPC: Stream.AddStream
           # 3. Spawn snapclient via subprocess (NOT supervisord - dynamic)
           # 4. Track process in memory

       def remove_remote_server(server_id):
           # 1. Kill snapclient process
           # 2. Remove stream from snapserver
           # 3. Clean up FIFO pipe
   ```

2. **Integration with Discovery**:
   - Discovery callback triggers `add_remote_server()` for new servers
   - Stale server timeout triggers `remove_remote_server()`
   - Skip local server (don't create snapclient to ourselves)

3. **Stream Configuration**:
   - Stream name: `remote-{server_id}` (e.g., `remote-192-168-1-138`)
   - Stream metadata: Set `serverId`, `serverName` via Stream properties
   - FIFO source: `/tmp/remote-{server_id}-fifo`

4. **Snapclient Command**:
   ```bash
   snapclient --host {remote_host} --port {remote_port} \
              --player file \
              --parameter filename=/tmp/remote-{server_id}-fifo
   ```
   - Uses file player to write to FIFO (not audio output)
   - No soundcard needed
   - Connects to remote server's port 1704

**Technical Considerations:**
- FIFO pipe creation: Must be read continuously to avoid blocking
- Process management: Use subprocess.Popen, store PIDs
- Error handling: Auto-reconnect if snapclient disconnects
- Resource cleanup: Ensure FIFOs and processes cleaned up on shutdown

### Phase 2: Backend - Simplify Routing Logic

**Files to modify:**
- `backend/scripts/federation/router.py` - Remove cross-server reconnection logic

**Key Changes:**

1. **Remove `_route_cross_server()` method**:
   - No longer need to write `/app/data/snapclient_target`
   - No longer need to restart snapclient via supervisorctl
   - No longer need 18-second wait period

2. **Unified Routing Logic**:
   ```python
   def route_client(client_id, stream_id):
       # 1. Parse client/stream server IDs
       # 2. Determine target stream ID:
       #    - If stream is local: Use local stream ID
       #    - If stream is remote: Use "remote-{server_id}" stream
       # 3. Get client's group
       # 4. Call Group.SetStream on client's server
       # 5. If stream is remote, also route remote server's group to actual stream
   ```

3. **Two-Step Remote Routing**:
   - Step 1: Switch local client to `remote-{server_id}` stream
   - Step 2: On remote server, route our snapclient to the desired stream
   - Example: Play Server B's AirPlay on Server A:
     1. Server A: Route local client to stream `remote-server-B`
     2. Server B: Route Server A's snapclient to stream `airplay1`

**Edge Cases:**
- Multiple local devices wanting different remote streams (need separate snapclients per remote server)
- Remote server goes offline (detect disconnect, fall back to local stream)

### Phase 3: Frontend - Update Stream Handling

**Files to modify:**
- `frontend/App.tsx` - Update routing logic
- `frontend/components/StreamSelector.tsx` - Handle remote streams
- `frontend/services/federationService.ts` - Update API calls

**Key Changes:**

1. **Stream Type Detection**:
   - Local streams: `airplay1`, `spotify1`, etc.
   - Remote streams: `remote-192-168-1-138` (represents entire remote server)
   - Display: Show remote streams as "All from {Server Name}"

2. **Routing Simplification**:
   ```typescript
   const handleStreamChange = async (clientId: string, streamId: string) => {
       // No more needsFederationRouting check
       // Just call snapcastService.setGroupStream() - works for all cases
       const groupId = clientGroupMap[clientId];
       await snapcastService.setGroupStream(groupId, streamId);
   }
   ```

3. **Stream Selection UI**:
   - Group streams by server (keep existing)
   - Add remote server streams at top level
   - Example dropdown:
     ```
     None
     ─────────────────────
     LOCAL STREAMS
       AirPlay 1
       Spotify 1
     ─────────────────────
     REMOTE: Bedroom Server
       All from Bedroom Server
     ```

4. **Remote Stream Sub-Selection** (future enhancement):
   - When on remote stream, show "Now Playing: AirPlay on Bedroom Server"
   - Allow selecting which stream on remote server (API call to remote)

### Phase 4: Migration & Compatibility

**Files to modify:**
- `backend/config/supervisord/snapclient.ini` - Keep for backwards compatibility
- `backend/scripts/get-settings.py` - No changes needed
- `backend/scripts/audio_api.py` - Update restart logic

**Migration Strategy:**

1. **Backwards Compatibility**:
   - Keep existing supervisord snapclient for non-federation mode
   - Only use new approach when federation enabled
   - `/app/data/snapclient_target` no longer used in federation mode

2. **Graceful Upgrade**:
   - On federation enable: Start remote snapclient manager
   - On federation disable: Stop remote snapclients, fall back to single snapclient

3. **Audio Output Changes**:
   - Keep existing restart logic for local output snapclient
   - Remote snapclients don't need audio device changes (file player only)

## Critical Files to Modify

1. **backend/scripts/federation/remote_snapclient_manager.py** (NEW)
2. **backend/scripts/federation/service.py** (MODIFY)
3. **backend/scripts/federation/discovery.py** (MODIFY - add callbacks)
4. **backend/scripts/federation/router.py** (SIMPLIFY)
5. **backend/scripts/setup.sh** (MODIFY - FIFO pipe creation)
6. **frontend/App.tsx** (SIMPLIFY - remove dual API logic)
7. **frontend/components/StreamSelector.tsx** (MODIFY - remote stream display)

## Testing Plan

1. **Single Server (Non-Federation)**: Verify existing behavior unchanged
2. **Two Server Discovery**: Verify remote snapclient spawned
3. **Remote Stream Switching**: Verify fast switching, no reconnection delay
4. **Server Disconnect**: Verify cleanup, fallback to local
5. **Audio Quality**: Verify no degradation through remote snapclient

## Implementation Details (Clarified)

### Stream Selection & Routing

**User Flow:**
1. User selects stream from UI (already groups by server): "Bedroom Server - AirPlay"
2. System determines if stream is remote (serverId !== localServerId)
3. If remote, perform two-step routing:
   - **Step 1 (Local)**: Route local output client to `remote-{serverId}` stream
   - **Step 2 (Remote)**: Route our snapclient on remote server to the actual stream (e.g., `airplay`)

**Example:**
- User on Server A (192.168.1.133) selects "Server B (192.168.1.138) - AirPlay"
- Backend calls:
  1. Server A: `Group.SetStream(local_client_group, "remote-192-168-1-138")`
  2. Server B: Find Server A's snapclient → `Group.SetStream(serverA_client_group, "airplay")`

### Metadata Handling

- Remote snapclient automatically passes through metadata from remote server
- No special handling needed - Snapcast protocol includes metadata in stream
- Frontend shows album art, track info from remote stream automatically
- Display: "Now Playing: [Track] from Bedroom Server - AirPlay"

### UI Changes

**No major UI restructuring needed:**
- Stream grouping by server already exists
- Just need to handle routing logic differences
- Remote streams appear same as local streams in UI
- Frontend can't distinguish local vs remote streams (that's the point!)

## Key Technical Decisions

### Why Multiple Snapclients Instead of Reconnection?

**Current Approach Problems:**
- 18-second delay (15s startup + 3s connection)
- Complex state management (`snapclient_target` file)
- Race conditions on reconnection
- Only works for local clients (can't route Music Assistant clients)

**New Approach Advantages:**
- ~50ms stream switching (local operation)
- No state files, no restart coordination
- Works for all clients (local, browser, third-party)
- Simpler error handling (stream switching can't fail dramatically)
- Better user experience (instant response)

### Remote Snapclient Configuration

**Each remote snapclient:**
- Connects to: Remote server's port 1704 (snapclient port)
- Outputs to: Same audio device as local snapclient (hw:Headphones)
- Command: `snapclient --host {remote_host} --port 1704 --soundcard hw:Headphones --latency 0`
- Identifier: Unique MAC address or client ID
- Group: Assigned to `none` stream by default (inactive)
- Activation: Routed to desired stream when user selects it

**Lifecycle:**
- Created: When server discovered via Avahi
- Destroyed: When server stale (2 minutes no mDNS response)
- Auto-reconnect: If remote server temporarily unavailable
- Always running: All snapclients run simultaneously

**Stream Routing States:**
- **Active**: Routed to actual stream (e.g., `airplay`, `spotify`)
- **Inactive**: Routed to `none` stream (plays silence)
- **Transition**: Route inactive to `none` → route active to desired stream

### Stream Routing & Lockout Logic

**Endpoint Tracking:**
- Federation service tracks "active endpoint" (which snapclient is currently playing)
- Active endpoint = (server_id, client_id, stream_id)
- Example: ("local", "aa:bb:cc:dd:ee:ff", "airplay1")

**Routing Flow (Example: Switch from local to remote stream):**

1. **Current State:**
   - Local snapclient (on Server A): Playing `airplay` stream
   - Remote snapclient (on Server B): Playing `none` stream (silent)

2. **User selects:** "Server B - Spotify"

3. **Federation service:**
   - Identifies current active: (Server A, local-client, airplay)
   - Identifies target: (Server B, remote-client, spotify)
   - Routes local client to `none`: `Server A → Group.SetStream(local-group, "none")`
   - Routes remote client to `spotify`: `Server B → Group.SetStream(remote-group, "spotify")`
   - Updates active endpoint tracking

4. **Result:**
   - Local snapclient: Now playing `none` stream (silent)
   - Remote snapclient: Now playing `spotify` stream (audio output)
   - Same audio device (hw:Headphones), no conflict

## Detailed Implementation Steps

### Step 1: Remote Snapclient Manager (New Component)

**File:** `backend/scripts/federation/remote_snapclient_manager.py`

**Class: RemoteSnapclientManager**
```python
class RemoteSnapclientManager:
    def __init__(self, audio_device="hw:Headphones", latency=0):
        self.processes = {}  # {server_id: subprocess.Popen}
        self.client_ids = {}  # {server_id: snapcast_client_id}
        self.audio_device = audio_device
        self.latency = latency

    def add_remote_server(self, server_id, host, port):
        """Add remote server and spawn snapclient"""
        # Spawn snapclient subprocess (outputs to audio device)
        cmd = [
            "/usr/bin/snapclient",
            "--host", host,
            "--port", str(port or 1704),
            "--soundcard", self.audio_device,
            "--latency", str(self.latency)
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            user="snapcast"  # Run as snapcast user for audio group access
        )
        self.processes[server_id] = proc

        log(f"Remote snapclient spawned for {server_id} → {host}:{port}")

        # Wait for client to connect and get its ID
        # Query remote server to find our client
        # (Client ID will be MAC address or generated UUID)
        time.sleep(2)  # Brief wait for connection
        client_id = self._find_client_on_server(server_id, host, port)
        if client_id:
            self.client_ids[server_id] = client_id
            # Route to 'none' stream (inactive by default)
            self._route_to_none(server_id, host, port, client_id)
        else:
            log(f"Warning: Could not find client ID for {server_id}")

    def remove_remote_server(self, server_id):
        """Remove remote server and cleanup"""
        # Kill snapclient process
        if server_id in self.processes:
            proc = self.processes[server_id]
            proc.terminate()
            proc.wait(timeout=5)
            del self.processes[server_id]

        # Remove from client ID tracking
        if server_id in self.client_ids:
            del self.client_ids[server_id]

        log(f"Remote snapclient terminated for {server_id}")

    def restart_remote_client(self, server_id, host, port):
        """Restart if connection lost"""
        self.remove_remote_server(server_id)
        time.sleep(1)  # Brief pause before reconnect
        self.add_remote_server(server_id, host, port)

    def get_client_id(self, server_id):
        """Get snapcast client ID for a remote server"""
        return self.client_ids.get(server_id)

    def get_active_servers(self):
        """List currently connected remote servers"""
        return list(self.processes.keys())

    def cleanup_all(self):
        """Cleanup all remote clients on shutdown"""
        for server_id in list(self.processes.keys()):
            self.remove_remote_server(server_id)

    def _find_client_on_server(self, server_id, host, port):
        """Query remote server to find our client ID"""
        # Use WebSocket manager to query server status
        # Find client by MAC address or most recent connection
        # Return client ID
        pass  # Implementation details

    def _route_to_none(self, server_id, host, port, client_id):
        """Route client to 'none' stream (inactive)"""
        # Use federation router or WebSocket manager
        # Call Group.SetStream to route client's group to 'none'
        pass  # Implementation details
```

**Key Implementation Details:**

1. **Snapclient Audio Output** (all clients output to same device):
   - Command: `snapclient --host {host} --port 1704 --soundcard hw:Headphones --latency 0`
   - All snapclients (local + remote) output to same audio device
   - ALSA/audio driver handles mixing (but we prevent conflicts via routing)

2. **Client Identification**:
   - Each snapclient has unique ID (MAC address or UUID)
   - Query server status to find client ID after spawning
   - Track mapping: {server_id → client_id}

3. **Stream Routing** (prevent conflicts):
   - Active client: Routed to desired stream
   - Inactive clients: Routed to `none` stream (silence)
   - API: `Group.SetStream(group_id, stream_id)`

4. **Process Management**:
   - Subprocess.Popen for dynamic snapclient spawning
   - Run as `snapcast` user for audio group access (GID 29)
   - Monitor process health, auto-restart on crash

**Integration Points:**
- Called by `federation/service.py` on server discovery/removal callbacks
- Uses Snapcast JSON-RPC API for stream management (reuse existing RPC client pattern)
- Uses subprocess.Popen for snapclient lifecycle (not supervisord - dynamic management)
- Error handling: Log failures, auto-retry on disconnect (monitor process health)

### Step 2: Update Discovery to Trigger Snapclient Creation

**File:** `backend/scripts/federation/discovery.py`

**Changes:**
- Add callback: `on_server_added(server_id, host, port, name)`
- Add callback: `on_server_removed(server_id)`
- Call remote snapclient manager when servers change
- Skip local server (don't create snapclient to ourselves)

**File:** `backend/scripts/federation/service.py`

**Changes:**
- Initialize `RemoteSnapclientManager()` on startup
- Register discovery callbacks
- Handle server add/remove events
- Cleanup on shutdown

### Step 3: Update Router for Stream Lockout Logic

**File:** `backend/scripts/federation/router.py`

**Changes:**

1. **Add active endpoint tracking:**

```python
class FederationRouter:
    def __init__(self, websocket_manager, snapclient_manager):
        self.ws_manager = websocket_manager
        self.snapclient_manager = snapclient_manager  # RemoteSnapclientManager
        self.active_endpoint = None  # (server_id, client_id, stream_id)
        self.local_server_id = None  # Set during init
```

2. **Remove `_route_cross_server()` method entirely**

3. **Rewrite `route_client()` with lockout logic:**

```python
def route_client(self, client_id: str, stream_id: str) -> bool:
    """Route client to stream with endpoint lockout"""
    # Parse server IDs
    client_server_id = self._get_server_id(client_id)
    stream_server_id = self._get_server_id(stream_id) if stream_id else None

    # Determine if this is local or remote output client
    is_local_output = (client_server_id == self.local_server_id and
                       self._is_output_client(client_id))

    if not is_local_output:
        # Non-output client (e.g., browser client, third-party)
        # Route normally without lockout logic
        return self._route_simple(client_server_id, client_id, stream_id)

    # Output client routing with lockout
    if self.active_endpoint:
        # Deactivate current endpoint (route to 'none')
        old_server, old_client, old_stream = self.active_endpoint
        self._route_to_none(old_server, old_client)

    # Activate new endpoint
    if stream_id and stream_id != "none":
        # Route to desired stream
        self._route_simple(stream_server_id, client_id, stream_id)
        self.active_endpoint = (stream_server_id, client_id, stream_id)
    else:
        # Route to none (deactivate)
        self._route_to_none(client_server_id, client_id)
        self.active_endpoint = None

    return True

def _route_to_none(self, server_id: str, client_id: str):
    """Route client to 'none' stream (silence)"""
    # Get none stream ID for this server
    none_stream_id = self._get_none_stream(server_id)
    self._route_simple(server_id, client_id, none_stream_id)

def _route_simple(self, server_id: str, client_id: str, stream_id: str):
    """Route client to stream (no lockout logic)"""
    # Get client's group
    group_id = self._get_client_group(server_id, client_id)
    # Route group to stream
    self._call_group_set_stream(server_id, group_id, stream_id)
```

### Step 4: Update Frontend Routing Logic

**File:** `frontend/App.tsx`

**Changes:**

1. **Simplify `handleStreamChange()`:**
   - Backend handles endpoint lockout automatically
   - Frontend just calls federation API with desired stream
   - No need to track which endpoint is active (backend manages this)

2. **Stream ID handling:**
   - Keep federated IDs (e.g., `server-192-168-1-138-airplay`)
   - Backend router parses server IDs and applies lockout logic

3. **No changes needed for:**
   - Metadata handling (passes through snapclient automatically)
   - Stream grouping (already works correctly)
   - UI display (streams appear same as before)

**File:** `frontend/components/StreamSelector.tsx`

**No changes needed:**
- Stream grouping by server already exists
- All streams (local and remote) appear in grouped list
- User selects stream normally, backend handles routing complexity

### Step 5: Testing & Validation

**Test Scenarios:**

1. **Single Server Mode:**
   - Verify no remote snapclients created
   - Existing behavior unchanged

2. **Two Server Discovery:**
   - Enable federation on both servers
   - Verify each creates remote snapclient for the other
   - Check stream list shows `remote-{server_id}` on each

3. **Remote Stream Selection:**
   - Server A: Select "Server B - AirPlay"
   - Verify fast switching (< 1 second)
   - Verify audio plays from Server B's AirPlay
   - Verify metadata shows correctly

4. **Server Disconnect:**
   - Disconnect Server B (network/power)
   - Verify Server A removes remote stream
   - Verify cleanup of snapclient process

5. **Server Reconnect:**
   - Reconnect Server B
   - Verify remote snapclient re-created
   - Verify stream reappears

6. **Audio Quality:**
   - Compare local stream vs remote stream audio quality
   - Should be identical (snapclient lossless over LAN)

## Files to Create/Modify Summary

### New Files:
1. `backend/scripts/federation/remote_snapclient_manager.py` - Remote snapclient spawning and lifecycle

### Modified Files:
1. `backend/scripts/federation/service.py` - Initialize remote snapclient manager, handle discovery callbacks
2. `backend/scripts/federation/discovery.py` - Add callbacks for server add/remove events
3. `backend/scripts/federation/router.py` - Add endpoint lockout logic, remove reconnection code
4. `frontend/App.tsx` - Minimal changes (backend handles complexity)

### Deprecated/Removed:
1. `/app/data/snapclient_target` - No longer used in federation mode
2. `FederationRouter._route_cross_server()` - Deleted (replaced with lockout logic)
3. Snapclient restart coordination logic - Removed (no restarts needed)
4. FIFO pipes for remote streams - Not used (direct audio output)
5. Stream.AddStream/RemoveStream for remote streams - Not used (no FIFO streams)

## Migration & Backwards Compatibility

**Non-Federation Mode:**
- Single snapclient via supervisord (unchanged)
- No remote snapclients created
- Existing behavior preserved

**Federation Mode:**
- Remote snapclients managed by new manager
- Supervisord snapclient becomes local output only
- `/app/data/snapclient_target` ignored (deprecated)

**Upgrade Path:**
- No manual migration needed
- On federation enable: Remote snapclients auto-created
- On federation disable: Remote snapclients auto-removed

## Performance & Resource Considerations

**Additional Resources per Remote Server:**
- 1 snapclient process (~10MB RAM)
- 1 network connection to remote server
- 1 audio decoder (but only active client decodes at any time)

**Example: 3-server setup:**
- Each server runs 2 remote snapclients (for the other 2 servers)
- Total: ~20MB extra RAM per server
- Network: 2 snapclient connections per server (low bandwidth when on 'none' stream)
- CPU: Only 1 active decoder at a time (others play silence, minimal CPU)

**Audio Mixing:**
- Multiple snapclients CAN output to same device (ALSA dmix)
- Lockout logic ensures only one plays audio (others play 'none' stream)
- No actual audio mixing occurs (prevented by routing)

**Scalability:**
- Tested up to: TBD (recommend max 5-10 servers)
- Auto-discovery limit: None (but Avahi scan may slow with many servers)
- Network bandwidth: Active stream uses full bandwidth, inactive streams minimal

## Next Steps After Implementation

**Future Enhancements:**
1. Remote stream health monitoring (detect if remote snapclient disconnects)
2. UI indicator showing which server you're playing from
3. Bandwidth optimization (only connect to remote servers when needed)
4. Support for remote server authentication (if implemented)
5. Remote group management (create/delete groups on remote servers)
