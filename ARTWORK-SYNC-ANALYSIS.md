# Artwork Synchronization Issue Analysis

## Problem Statement
Artwork is not staying in sync with track metadata. Sometimes artwork updates correctly, sometimes it doesn't. Page reload or play/pause sometimes fixes it, but not consistently.

## Root Cause Identified

### Issue #1: Artwork Preservation Across Track Changes ⚠️ **PRIMARY ISSUE**

**Location:** `backend/scripts/airplay-control-script.py` lines 656-660

```python
# Merge new metadata with existing, preserving artUrl if not in new data
if self.last_metadata and not metadata.get("artUrl") and self.last_metadata.get("artUrl"):
    # Preserve existing artUrl if new metadata doesn't have it
    metadata["artUrl"] = self.last_metadata["artUrl"]
    log(f"[DEBUG] Preserved existing artUrl: {metadata['artUrl']}")
```

**What happens:**
1. User plays Track A (has artwork A)
2. User skips to Track B
3. Shairport-sync sends Track B metadata (title/artist/album) FIRST
4. Control script receives metadata WITHOUT artwork
5. Script preserves artwork A from previous track
6. Frontend receives Track B metadata with artwork A ❌ **WRONG ARTWORK**
7. Seconds later, artwork B arrives
8. Control script sends update with correct artwork B
9. Frontend may or may not re-render depending on timing

**Why this is problematic:**
- Shows wrong artwork for several seconds
- User sees Track B info with Track A artwork (confusing)
- Better to show NO artwork briefly than WRONG artwork

### Issue #2: Multiple Metadata Updates Per Track

**What happens:**
When a new track plays, shairport-sync sends metadata in this order:
1. Title, Artist, Album fields (separate XML items)
2. Cover art PICT chunks (can be 200KB+ of base64 data)
3. PICT end signal

The control script sends a metadata update for EACH field change:
- Update 1: Title arrives → Send update (no artwork)
- Update 2: Artist arrives → Send update (no artwork)
- Update 3: Album arrives → Send update (no artwork)
- Update 4: Artwork complete → Send update (with artwork)

**Result:** Frontend receives 4 updates per track, only the last one has artwork.

### Issue #3: Change Detection Logic

**Location:** `backend/scripts/airplay-control-script.py` lines 662-674

The script checks if metadata changed before sending:
```python
should_send = (
    not self.last_metadata or
    is_new_track or
    self.last_metadata.get("album") != metadata.get("album") or
    self.last_metadata.get("artUrl") != metadata.get("artUrl")
)
```

This means if ONLY artwork changes (title/artist/album same), it WILL send an update. This logic is correct.

However, the preservation logic (Issue #1) means artUrl rarely changes because it's being preserved from the old track.

## Data Flow Diagram

```
┌─────────────────┐
│   iOS Device    │
│  (AirPlay)      │
└────────┬────────┘
         │ AirPlay Protocol
         ▼
┌─────────────────────────────────────────────────────────┐
│              Shairport-Sync                             │
│  - Receives audio + metadata                            │
│  - Writes XML to /tmp/shairport-sync-metadata pipe      │
│  - Metadata arrives in sequence:                        │
│    1. Title (minm)                                      │
│    2. Artist (asar)                                     │
│    3. Album (asal)                                      │
│    4. PICT chunks (base64 artwork data)                 │
│    5. PICT end signal                                   │
└────────┬────────────────────────────────────────────────┘
         │ XML Metadata Pipe
         ▼
┌─────────────────────────────────────────────────────────┐
│      airplay-control-script.py                          │
│  - Reads pipe, parses XML                               │
│  - Collects PICT chunks                                 │
│  - On PICT end: decode, hash, save to disk              │
│  - ⚠️  PRESERVES old artwork if new metadata has none   │
│  - Sends Plugin.Stream.Player.Properties                │
└────────┬────────────────────────────────────────────────┘
         │ JSON-RPC Notification
         ▼
┌─────────────────────────────────────────────────────────┐
│              Snapcast Server                            │
│  - Receives notification                                │
│  - Updates stream.properties                            │
│  - Broadcasts to WebSocket clients                      │
└────────┬────────────────────────────────────────────────┘
         │ WebSocket
         ▼
┌─────────────────────────────────────────────────────────┐
│              Frontend (App.tsx)                         │
│  - Receives notification (real-time)                    │
│  - Also polls Server.GetStatus every 3s                 │
│  - Extracts artUrl from:                                │
│    - stream.properties.artUrl (priority 1)              │
│    - metadata['mpris:artUrl'] (priority 2)              │
│    - metadata.artUrl (priority 3)                       │
│  - Adds /snapcast-api proxy prefix                      │
│  - Updates state if artwork URL changed                 │
└────────┬────────────────────────────────────────────────┘
         │ HTTP Request
         ▼
┌─────────────────────────────────────────────────────────┐
│       Snapcast HTTP Server (nginx proxy)                │
│  - Serves /coverart/{hash}.jpg                          │
│  - Files in /usr/share/snapserver/snapweb/coverart/     │
└─────────────────────────────────────────────────────────┘
```

## Proposed Fixes

### Fix #1: Remove Artwork Preservation (RECOMMENDED)

**File:** `backend/scripts/airplay-control-script.py`

**Remove lines 656-660:**
```python
# DELETE THIS:
if self.last_metadata and not metadata.get("artUrl") and self.last_metadata.get("artUrl"):
    metadata["artUrl"] = self.last_metadata["artUrl"]
    log(f"[DEBUG] Preserved existing artUrl: {metadata['artUrl']}")
```

**Rationale:**
- Better to show NO artwork briefly than WRONG artwork
- Artwork typically arrives within 1-2 seconds
- Frontend has a default placeholder image
- Users won't notice brief absence, but WILL notice wrong artwork

### Fix #2: Send Artwork Separately (ALTERNATIVE)

Instead of preserving, clear artwork on new track:
```python
if is_new_track:
    # Clear artwork on new track - it will arrive shortly
    if not metadata.get("artUrl"):
        log(f"[DEBUG] New track without artwork, clearing old artwork")
        # Don't preserve - let it be None
```

### Fix #3: Batch Metadata Updates (ADVANCED)

Add a small delay (100ms) after receiving metadata to collect all fields before sending:
- Buffer incoming metadata fields
- On new field, restart timer
- When timer expires, send complete metadata
- This reduces updates from 4 to 1 per track

## Testing Instructions

### Test 1: Run Debug Script
```bash
docker exec plum-snapcast-server python3 /app/scripts/debug-artwork-sync.py
```

This will analyze:
- How many times artwork was preserved
- Timing between metadata and artwork arrival
- Which tracks had artwork, which didn't

### Test 2: Monitor Artwork Flow
```bash
docker exec plum-snapcast-server bash /app/scripts/test-artwork-flow.sh
```

This will:
- Check coverart directory
- Show recent artwork files
- Monitor for new artwork being created

### Test 3: Live Log Monitoring
```bash
docker exec plum-snapcast-server tail -f /tmp/airplay-control-script.log | grep -E "New track|artUrl|Preserved"
```

Look for:
- "New track:" messages
- "Preserved existing artUrl" (this is the problem!)
- "Cover art saved" messages
- Time gap between "New track" and "Cover art complete"

### Test 4: Frontend Console
Open browser dev tools, filter console for "artwork" or "artUrl"

Look for:
- Multiple metadata updates for same track
- Artwork URL changes
- Whether state updates trigger re-render

## Verification After Fix

After applying the fix:

1. **No artwork preservation:**
   ```bash
   docker logs plum-snapcast-server 2>&1 | grep "Preserved existing artUrl"
   ```
   Should return NO results

2. **Artwork arrives for each track:**
   ```bash
   docker logs plum-snapcast-server 2>&1 | grep -E "New track:|Cover art complete"
   ```
   Each "New track" should be followed by "Cover art complete" within 1-2 seconds

3. **Frontend updates correctly:**
   - Play a track, note artwork
   - Skip to next track
   - Should see default artwork briefly
   - Then correct artwork appears within 1-2 seconds
   - Never see previous track's artwork

## Additional Considerations

### Browser Caching
Artwork URLs are based on MD5 hash of image data. Same artwork = same filename = browser cache hit. This is GOOD for performance but means:
- If artwork doesn't change, browser won't refetch
- This is correct behavior
- Not related to sync issue

### WebSocket vs Polling
Frontend receives metadata via two paths:
1. WebSocket notifications (real-time, < 100ms)
2. Periodic polling Server.GetStatus (every 3s)

Both paths extract artwork correctly. The polling is a backup in case WebSocket notifications are missed.

### Snapcast Property Filtering
Snapcast server may filter certain stream properties. The control script sends artwork in THREE places:
1. `metadata["mpris:artUrl"]` (MPRIS standard field)
2. `properties["artUrl"]` (top-level property)
3. Writes to `/usr/share/snapserver/snapweb/airplay-artwork.json` (fallback file)

This redundancy ensures artwork reaches frontend via at least one path.
