# Timeline/Scrub Bar Testing Guide

## Overview

This guide provides diagnostic commands and testing procedures for the timeline/scrub bar feature across all audio sources.

---

## Pre-Flight Checks

### 1. Verify Docker Containers Running

```bash
docker ps | grep plum
# Should show: plum-snapcast-server (and plum-plexamp if enabled)
```

### 2. Check Control Script Logs

```bash
# Check which control scripts are running
docker exec plum-snapcast-server ps aux | grep control-script

# View recent logs for each source
docker exec plum-snapcast-server tail -100 /tmp/spotify-control-script.log
docker exec plum-snapcast-server tail -100 /tmp/airplay-control-script.log
docker exec plum-snapcast-server tail -100 /tmp/bluetooth-control-script.log
docker exec plum-snapcast-server tail -100 /tmp/dlna-control-script.log
docker exec plum-snapcast-server tail -100 /tmp/plexamp-control-script.log
```

### 3. Verify Snapcast Server Status

```bash
# Check snapserver is running
docker exec plum-snapcast-server supervisorctl status snapserver

# View snapserver logs
docker logs plum-snapcast-server | grep snapserver
```

---

## Testing By Source

### ✅ **Spotify (Full Support: Position + Seek)**

#### Setup
1. Connect to "Plum Audio" via Spotify app on phone/desktop
2. Start playing a song

#### Diagnostic Commands

```bash
# Monitor Spotify control script logs (real-time)
docker exec plum-snapcast-server tail -f /tmp/spotify-control-script.log

# Check D-Bus MPRIS connection
docker exec plum-snapcast-server dbus-send --system --print-reply \
  --dest=org.mpris.MediaPlayer2.spotifyd \
  /org/mpris/MediaPlayer2 \
  org.freedesktop.DBus.Properties.GetAll \
  string:org.mpris.MediaPlayer2.Player

# Verify position property is available
docker exec plum-snapcast-server dbus-send --system --print-reply \
  --dest=org.mpris.MediaPlayer2.spotifyd \
  /org/mpris/MediaPlayer2 \
  org.freedesktop.DBus.Properties.Get \
  string:org.mpris.MediaPlayer2.Player \
  string:Position
```

#### Expected Behavior
- ✅ Position updates every ~1 second (check logs for "Position changed")
- ✅ Duration displays correctly in GUI
- ✅ Timeline bar fills smoothly
- ✅ Clicking on timeline seeks to that position
- ✅ Cursor shows pointer on hover

#### Test Cases
1. **Position Tracking**: Play song, verify position increments in GUI
2. **Seek Forward**: Click 75% through timeline, verify playback jumps
3. **Seek Backward**: Click 25% through timeline, verify playback rewinds
4. **Track Change**: Skip track, verify position resets to 0
5. **Pause/Resume**: Pause, verify position stops updating

---

### ✅ **Plexamp (Full Support: Position + Seek)**

#### Setup
1. Ensure `PLEXAMP_ENABLED=1` in docker/.env
2. Start with profile: `docker compose --profile plexamp up -d`
3. Play music via Plexamp app

#### Diagnostic Commands

```bash
# Monitor Plexamp control script logs (real-time)
docker exec plum-plexamp tail -f /tmp/plexamp-control-script.log

# Check Plexamp HTTP API availability
docker exec plum-plexamp curl -s http://127.0.0.1:32500/player/timeline/poll?wait=0

# Verify PlayQueue.json exists and has data
docker exec plum-plexamp cat /root/.local/share/Plexamp/Plexamp/PlayQueue.json | jq '.timeline.mediaIndex'
```

#### Expected Behavior
- ✅ Position updates every ~2 seconds (polling interval)
- ✅ Duration displays correctly
- ✅ Timeline bar updates in 2-second intervals
- ✅ Seeking works via HTTP API
- ✅ Playback state (playing/paused) tracked correctly

#### Test Cases
1. **Position Tracking**: Verify updates every 2s (may appear slightly jumpy)
2. **Seek**: Click timeline, check logs for "Seek to" message
3. **API Response**: Verify HTTP API returns valid XML with position
4. **Track Change**: Skip track, verify new duration/position

---

### ✅ **AirPlay (Position Only, Conditional Seek)**

#### Setup
1. Connect iOS/macOS device to "Plum Audio" via AirPlay
2. Play music

#### Diagnostic Commands

```bash
# Monitor AirPlay control script logs (real-time)
docker exec plum-snapcast-server tail -f /tmp/airplay-control-script.log | grep -E "prgr|Progress|Position|MPRIS"

# Check for prgr metadata in logs
docker exec plum-snapcast-server grep "prgr" /tmp/airplay-control-script.log | tail -10

# Check if MPRIS interface is available (for seeking)
docker exec plum-snapcast-server dbus-send --system --print-reply \
  --dest=org.mpris.MediaPlayer2.ShairportSync \
  /org/mpris/MediaPlayer2 \
  org.freedesktop.DBus.Introspectable.Introspect 2>&1 | grep -i player

# Verify shairport-sync is running
docker exec plum-snapcast-server supervisorctl status shairport-sync
```

#### Expected Behavior
- ✅ Position tracked from RTP timestamps (prgr metadata)
- ✅ Duration calculated from RTP start/end
- ✅ Timeline updates smoothly
- ⚠️ Seek available ONLY if MPRIS enabled (check logs on startup)
- ⚠️ If MPRIS not available, timeline is view-only (no pointer cursor)

#### Test Cases
1. **prgr Parsing**: Check logs for "Progress" messages with RTP timestamps
2. **Position Display**: Verify current position shows in GUI
3. **Duration Accuracy**: Compare displayed duration to actual track length
4. **MPRIS Check**: Look for "MPRIS interface available" or "not available" in logs
5. **Seek (if MPRIS enabled)**: Try clicking timeline, check for seek command

#### Troubleshooting
```bash
# If no prgr metadata appearing:
# 1. Check shairport-sync metadata pipe
docker exec plum-snapcast-server ls -la /tmp/shairport-sync-metadata

# 2. Verify shairport-sync config has metadata enabled
docker exec plum-snapcast-server cat /app/config/shairport-sync.conf | grep -A5 metadata

# If MPRIS not available (expected on Alpine):
# This is normal - Alpine shairport-sync package doesn't include MPRIS
# Timeline will still work (position tracking), just no seeking
```

---

### ✅ **Bluetooth (Position Only, No Seek)**

#### Setup
1. Pair phone via Bluetooth
2. Enable "Bluetooth audio" on phone
3. Play music

#### Diagnostic Commands

```bash
# Monitor Bluetooth control script logs (real-time)
docker exec plum-snapcast-server tail -f /tmp/bluetooth-control-script.log | grep -E "Position|Duration|Track"

# Check BlueZ MediaPlayer interface
docker exec plum-snapcast-server dbus-send --system --print-reply \
  --dest=org.bluez \
  / \
  org.freedesktop.DBus.ObjectManager.GetManagedObjects | grep -A20 MediaPlayer1

# View current track properties
docker exec plum-snapcast-server busctl --system introspect org.bluez /org/bluez/hci0/dev_XX_XX_XX_XX_XX_XX/player0
```

#### Expected Behavior
- ✅ Position tracked via AVRCP Position property
- ✅ Duration extracted from Track metadata
- ✅ Timeline displays and updates
- ❌ NO seek support (AVRCP protocol limitation)
- ⚠️ Position updates depend on phone sending AVRCP position events

#### Test Cases
1. **Position Updates**: Check if position increments (depends on phone)
2. **Duration Display**: Verify track duration shown correctly
3. **Client-side Fallback**: If no position events, client estimates
4. **Track Change**: Skip track, verify new metadata received

#### Troubleshooting
```bash
# If no position updates:
# Check if phone is sending position events
docker exec plum-snapcast-server dbus-monitor --system "type='signal',interface='org.freedesktop.DBus.Properties'" &
# Play music and watch for Position property changes

# Some phones don't send position events via AVRCP
# In this case, client-side estimation will be used (acceptable)
```

---

### ⚠️ **DLNA (Client-Side Only)**

#### Setup
1. Cast to "Plum Audio" from DLNA app (BubbleUPnP, etc.)
2. Play music

#### Diagnostic Commands

```bash
# Monitor DLNA control script logs
docker exec plum-snapcast-server tail -f /tmp/dlna-control-script.log

# Check gmrender-resurrect is running
docker exec plum-snapcast-server supervisorctl status gmrender-resurrect

# View metadata file (written by external monitor)
docker exec plum-snapcast-server cat /tmp/dlna-metadata.json | jq
```

#### Expected Behavior
- ✅ Duration extracted from metadata (if available)
- ⚠️ Position is CLIENT-SIDE ESTIMATION only
- ❌ NO server position tracking (not implemented yet)
- ❌ NO seek support (not implemented yet)
- ℹ️ Timeline works but drifts without server sync

#### Test Cases
1. **Duration Display**: Verify duration shows if metadata includes it
2. **Client Estimation**: Position increments via client-side timer
3. **Drift Check**: Compare GUI position to actual playback (may drift)

#### Note
DLNA position tracking and seek will be implemented in a follow-up commit using UPnP GetPositionInfo() and Seek() SOAP calls.

---

## Frontend Testing

### Browser Console Checks

Open browser console (F12) and look for:

```javascript
// Position update logs
[WebSocket] Stream <id> playback state: ...

// Seek command logs
Seek to <position>s (<ms>ms) for stream <id>

// Position sync logs (if verbose logging enabled)
[App] Position update: stream=<id>, position=<ms>
```

### Visual Indicators

1. **Timeline Bar**: Should fill smoothly, matching playback
2. **Time Display**: Current/Total time in format MM:SS
3. **Hover Effect**: Timeline height increases on hover (if seekable)
4. **Cursor**: Pointer cursor on timeline (if seekable), default otherwise
5. **Smooth Updates**: Position should not jump or reset unexpectedly

---

## Common Issues & Solutions

### Issue: Position stuck at 0:00

**Possible Causes:**
- Control script not sending position updates
- Frontend not receiving WebSocket messages
- Position property not in stream properties

**Diagnostics:**
```bash
# Check control script is sending position
docker exec plum-snapcast-server tail -50 /tmp/<source>-control-script.log | grep position

# Check WebSocket connection in browser console
# Should see: Plugin.Stream.Player.Properties events with position field

# Verify position in stream properties via snapcast API
echo '{"jsonrpc":"2.0","method":"Server.GetStatus","id":1}' | \
  docker exec -i plum-snapcast-server nc localhost 1705 | jq '.result.server.streams[].properties.position'
```

---

### Issue: Seek doesn't work

**Possible Causes:**
- Source doesn't support seeking
- canSeek is false
- Control script seek method not implemented

**Diagnostics:**
```bash
# Check canSeek capability
echo '{"jsonrpc":"2.0","method":"Server.GetStatus","id":1}' | \
  docker exec -i plum-snapcast-server nc localhost 1705 | jq '.result.server.streams[].properties.canSeek'

# Check seek command in logs after clicking timeline
docker exec plum-snapcast-server tail -20 /tmp/<source>-control-script.log | grep -i seek

# Verify frontend sent seek command (browser console)
# Should see: "Seek to <time>s" message
```

---

### Issue: Timeline jumps or resets unexpectedly

**Possible Causes:**
- Position updates conflicting with client-side estimation
- Track change detected incorrectly
- WebSocket reconnection

**Diagnostics:**
```bash
# Check for duplicate position updates
docker exec plum-snapcast-server tail -100 /tmp/<source>-control-script.log | grep -E "position|Position" | wc -l

# Monitor WebSocket stability in browser console
# Look for disconnect/reconnect messages
```

---

## Performance Metrics

### Expected Update Frequencies

| Source | Position Updates | Method |
|--------|------------------|--------|
| Spotify | ~1 second | D-Bus events |
| Plexamp | ~2 seconds | HTTP polling |
| AirPlay | ~0.5-1 second | prgr metadata |
| Bluetooth | Variable | AVRCP events |
| DLNA | Client-side only | 1 second timer |

### Latency Targets

- **Seek Response**: < 500ms from click to audio change
- **Position Accuracy**: ± 1 second
- **GUI Updates**: Smooth 1fps minimum (no stuttering)

---

## Quick Test Script

Save as `test-timeline.sh`:

```bash
#!/bin/bash

echo "=== Plum-Snapcast Timeline Feature Test ==="
echo ""

echo "1. Checking containers..."
docker ps | grep plum

echo ""
echo "2. Checking control scripts..."
docker exec plum-snapcast-server ps aux | grep control-script

echo ""
echo "3. Recent log activity (last 5 lines each):"
for source in spotify airplay bluetooth dlna plexamp; do
    echo "--- $source ---"
    docker exec plum-snapcast-server tail -5 /tmp/${source}-control-script.log 2>/dev/null || echo "Not available"
done

echo ""
echo "4. Snapcast streams with position info:"
echo '{"jsonrpc":"2.0","method":"Server.GetStatus","id":1}' | \
  docker exec -i plum-snapcast-server nc localhost 1705 | \
  jq -r '.result.server.streams[] | "Stream: \(.id) | Position: \(.properties.position // 0)ms | canSeek: \(.properties.canSeek // false)"'

echo ""
echo "=== Test Complete ==="
echo "Open browser to http://$(hostname -I | awk '{print $1}'):3000"
echo "Play audio from any source and verify timeline displays"
```

Run with: `bash test-timeline.sh`

---

## Next Steps (DLNA Enhancement)

Future commit will add:
- UPnP GetPositionInfo() polling for real position
- UPnP Seek() action for interactive seeking
- Estimated implementation: ~100-150 lines

This will bring DLNA to feature parity with Spotify/Plexamp.
