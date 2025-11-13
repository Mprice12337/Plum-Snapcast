# Metadata Flow Diagnostics

## Problem
- `/metadata` endpoint shows correct data ✓
- Logs show correct data ✓
- Frontend GUI shows NO data ✗

## Data Flow
```
AirPlay → shairport-sync → /tmp/shairport-sync-metadata →
→ airplay-control-script.py (MetadataStore) →
→ [1] HTTP endpoint (metadata-debug-server.py) ✓ WORKING
→ [2] Snapcast JSON-RPC (stdout notification) → Snapcast Server → WebSocket → Frontend ✗ NOT WORKING
```

## Diagnostic Steps

### Step 1: Verify Control Script is Sending to Snapcast

Check the logs to see what's being sent:
```bash
docker exec plum-snapcast-server tail -50 /tmp/airplay-control-script.log | grep "\[Snapcast\]"
```

Look for lines like:
```
[Snapcast] → Plugin.Stream.Player.Properties
[Snapcast] Metadata → Title - Artist
```

### Step 2: Check What Stream ID is Being Used

```bash
docker exec plum-snapcast-server python3 /app/scripts/check-snapcast-metadata.py
```

This will show:
- All streams Snapcast knows about
- Their IDs
- Whether they have metadata in properties

**Key Question**: Does the Stream ID match what the control script is using?

### Step 3: Check Control Script Stream ID

```bash
docker exec plum-snapcast-server ps aux | grep airplay-control-script
```

Look for the `--stream` argument. Default is "Airplay".

### Step 4: Check Snapcast Configuration

```bash
docker exec plum-snapcast-server cat /app/config/snapserver.conf | grep -A 5 "source = pipe"
```

Look for the stream configuration. The stream ID should match the `name=` parameter.

### Step 5: Listen to WebSocket Notifications

Open browser console on the frontend and run:
```javascript
// See what notifications the frontend is receiving
const oldLog = console.log;
console.log = function(...args) {
  if (args[0]?.includes?.('notification') || args[0]?.includes?.('Metadata')) {
    oldLog.apply(console, ['🔔', ...args]);
  }
  oldLog.apply(console, args);
};
```

Then check for incoming WebSocket messages.

## Common Issues

### Issue 1: Stream ID Mismatch
- Control script uses: `--stream Airplay`
- Snapcast assigns: `pipe:///tmp/snapfifo?name=Airplay...`
- Frontend looks for: Stream ID from Server.GetStatus

**Solution**: The stream ID must match exactly.

### Issue 2: Snapcast Not Forwarding Notifications
- Control script sends: `Plugin.Stream.Player.Properties`
- Snapcast might forward as: `Stream.OnProperties` or `Stream.OnUpdate`
- Frontend listens for: `Plugin.Stream.Player.Properties` OR `Stream.OnProperties`

**Solution**: Need to verify what Snapcast actually forwards.

### Issue 3: Metadata Not Stored in Stream Properties
- Control script sends notification
- Snapcast doesn't store it in `stream.properties.metadata`
- Frontend initial load sees no metadata

**Solution**: Snapcast might not store control script metadata in stream properties.

## Expected vs Actual

### Expected Behavior:
1. Control script sends `Plugin.Stream.Player.Properties` with metadata
2. Snapcast stores in `stream.properties.metadata`
3. Snapcast forwards notification to WebSocket clients
4. Frontend receives notification OR queries stream properties
5. Frontend updates UI

### Check Each Step:
- [ ] Control script logs show `[Snapcast] Metadata →` ✓
- [ ] Snapcast `Server.GetStatus` shows `properties.metadata` ❓
- [ ] Frontend console shows WebSocket notification received ❓
- [ ] Frontend updates UI ✗

## Next Steps

Run diagnostics and report back:
1. What stream ID is the control script using?
2. What stream IDs does Snapcast show?
3. Does `Server.GetStatus` include `properties.metadata`?
4. What notifications does the frontend console show?
