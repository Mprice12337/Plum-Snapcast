# AirPlay Metadata Handling

## Overview

This document explains how Plum-Snapcast handles AirPlay metadata from shairport-sync, processes it reliably, and displays it in the web interface.

## Architecture

```
AirPlay Device (iPhone/Mac)
        ↓
   shairport-sync
   (receives audio + metadata)
        ↓
   /tmp/shairport-sync-metadata
   (XML-formatted pipe)
        ↓
   process-airplay-metadata.py
   (parser with mper/bundle logic)
        ↓
   Snapcast Stream Properties
   (via JSON-RPC API)
        ↓
   Frontend WebSocket
   (real-time updates)
        ↓
   React UI Components
   (display in browser)
```

## The Metadata Problem

AirPlay metadata arrives **asynchronously** and **out of order**. Common issues include:

- **Timing Issues**: Artist might arrive before title, or vice versa
- **Empty Values**: AirPlay sends empty strings during transitions
- **Stale Data**: Metadata from previous tracks can linger
- **Partial Updates**: Only some fields update, leaving old data mixed with new

## The Solution: mper + Metadata Bundles

After researching working implementations (mikebrady/shairport-sync-metadata-reader and AlainGourves/shairport-metadata-display), we use AirPlay's built-in control codes:

### 1. Track Detection via `mper`

**`mper`** = DMAP Persistent Track ID (unique identifier for each track)

- **When received**: Definitive track change
- **Action**: Clear ALL metadata, start fresh
- **Why**: Eliminates stale data from previous tracks

```python
if code == "mper":
    track_id = decode_metadata(data)
    if current_track_id and current_track_id != track_id:
        # NEW TRACK - clear everything
        clear_all_metadata()
        current_track_id = track_id
```

### 2. Metadata Bundles via `mdst`/`mden`

**`mdst`** = Metadata Bundle Start
**`mden`** = Metadata Bundle End

- **When received**: AirPlay is sending a batch of metadata
- **Action**: Collect in pending state, apply atomically on bundle end
- **Why**: Prevents partial updates and mixed data

```python
if code == "mdst":  # Bundle start
    in_bundle = True
    pending_metadata = {}

# Collect metadata during bundle
if in_bundle and code in ["minm", "asar", "asal"]:
    pending_metadata[code] = value

if code == "mden":  # Bundle end
    in_bundle = False
    # Apply all pending metadata at once
    apply_metadata(pending_metadata)
```

### 3. Cover Art Handling

Shairport-sync caches artwork to disk when `cover_art_cache_directory` is configured:

- **Cache Location**: `/tmp/shairport-sync/.cache/coverart/`
- **Markers**: `pcst` (picture start) and `pcen` (picture end)
- **Files**: `cover-<hash>.jpg` or `cover-<hash>.png`

```python
if code == "pcen":  # Picture complete
    # Load newest file from cache
    cache_files = list_cache_files()
    newest = max(cache_files, key=lambda f: f.mtime)
    artwork_data = read_file(newest)
    encode_and_store(artwork_data)
```

## Metadata Codes Reference

### Core Metadata (type=`core`)

| Code | Description | Example |
|------|-------------|---------|
| `minm` | Track title/name | "Bohemian Rhapsody" |
| `asar` | Artist name | "Queen" |
| `asal` | Album name | "A Night at the Opera" |
| `asgn` | Genre | "Rock" |

### Control Messages (type=`ssnc`)

| Code | Description | Purpose |
|------|-------------|---------|
| `mper` | Persistent Track ID | **Track change detection** |
| `mdst` | Metadata bundle start | **Begin collecting metadata** |
| `mden` | Metadata bundle end | **Apply collected metadata** |
| `pbeg` | Playback begin | Stream started |
| `pend` | Playback end | Stream stopped |
| `pcst` | Picture start | Cover art incoming |
| `pcen` | Picture end | **Cover art complete** |
| `prgr` | Progress | Current position/duration |

## Implementation Details

### Metadata Parser State Machine

```python
class MetadataParser:
    def __init__(self):
        self.current_track_id = None
        self.in_metadata_bundle = False
        self.pending_metadata = {}
        self.current_metadata = {
            "title": None,
            "artist": None,
            "album": None,
            "artwork": None
        }
```

### Processing Flow

1. **Read XML from pipe**: Parse `<item>` elements with type/code/data
2. **Decode data**: Base64 decode, handle encoding
3. **Check for track change**: If `mper` changed, clear all metadata
4. **Handle bundles**: Collect during `mdst...mden`, apply atomically
5. **Update artwork**: On `pcen`, load from cache
6. **Push to Snapcast**: Set stream properties via JSON-RPC

### Snapcast Integration

Metadata is stored in Snapcast stream properties:

```json
{
  "stream_id": "airplay",
  "properties": {
    "metadata": {
      "title": "Song Name",
      "artist": "Artist Name",
      "album": "Album Name",
      "artwork": "data:image/jpeg;base64,/9j/4AAQ..."
    }
  }
}
```

**Set via JSON-RPC**:
```bash
curl -X POST http://localhost:1780/jsonrpc -d '{
  "jsonrpc": "2.0",
  "method": "Stream.SetProperty",
  "params": {
    "id": "airplay",
    "property": "metadata.title",
    "value": "Song Name"
  },
  "id": 1
}'
```

### Frontend Consumption

Frontend reads stream properties from `Server.GetStatus`:

```typescript
interface Stream {
  id: string;
  properties: {
    metadata?: {
      title?: string;
      artist?: string;
      album?: string;
      artwork?: string; // data URL
    };
  };
}

// Extract metadata
const metadata = stream.properties?.metadata || {};
const title = metadata.title || "Unknown Track";
const artist = metadata.artist || "Unknown Artist";
```

## Key Design Decisions

### ✅ Why Trust `mper` for Track Changes

- **Definitive**: DMAP persistent ID is unique per track
- **Reliable**: Always sent by iTunes/Music app
- **Early**: Arrives before other metadata, perfect for clearing
- **Proven**: Used by working implementations

### ✅ Why Use Metadata Bundles

- **Atomic**: All fields update together, no partial states
- **Ordered**: AirPlay sends batches in correct order
- **Complete**: Guarantees all available metadata is included
- **Race-free**: No timing dependencies

### ❌ Why NOT Use Timestamps

- **Unreliable**: Arrival time varies based on network/processing
- **Race conditions**: Artist before/after title is unpredictable
- **False positives**: Same artist on multiple tracks appears "stale"
- **Complex**: Requires arbitrary timeout values and guesswork

### ❌ Why NOT Use Title-Based Detection

- **Empty values**: AirPlay sends empty strings during transitions
- **Duplicates**: Same song can be played multiple times
- **Incomplete**: Title alone doesn't guarantee new track

## Testing Metadata Handling

### Debug Server

The debug server provides HTTP endpoints for testing:

```bash
# View metadata as plain text
curl http://localhost:8080/metadata

# View album artwork (JPEG/PNG)
curl http://localhost:8080/artwork > cover.jpg

# Get JSON status
curl http://localhost:8080/status
```

### Log Monitoring

Watch real-time metadata processing:

```bash
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf tail -f airplay-metadata-handler
```

Expected output:
```
[Metadata] NEW TRACK DETECTED via mper
[Metadata] Track ID: 1234567890ABCDEF
[Metadata] >>> Metadata bundle START
[Metadata] Title (pending): Song Name
[Metadata] Artist (pending): Artist Name
[Metadata] Album (pending): Album Name
[Metadata] >>> Metadata bundle END
[Snapcast] Set metadata.title = Song Name
[Snapcast] Set metadata.artist = Artist Name
[Snapcast] Set metadata.album = Album Name
[Cover Art] Loaded from cache: cover-abc123.jpg (176KB)
[Snapcast] Set metadata.artwork (176KB data URL)
```

### Test Cases

1. **Track Change**: Skip to next track → all metadata updates
2. **Same Artist**: Play multiple tracks by same artist → artist updates correctly
3. **Pause/Resume**: Pause and resume → metadata unchanged
4. **Empty Fields**: Play track with missing album → shows "Unknown Album"
5. **Album Art**: Switch tracks → artwork updates automatically

## Troubleshooting

### No Metadata Updates

```bash
# Check metadata pipe exists
docker exec plum-snapcast-server ls -l /tmp/shairport-sync-metadata

# Check handler is running
docker exec plum-snapcast-server supervisorctl status airplay-metadata-handler

# Check for errors
docker exec plum-snapcast-server supervisorctl tail airplay-metadata-handler
```

### Stale Metadata

- **Symptom**: Old track info mixed with new track info
- **Check**: Look for `mper` messages in logs
- **Cause**: Track ID not being detected or handled
- **Fix**: Verify parser extracts and compares `mper` correctly

### No Artwork

```bash
# Check cache directory
docker exec plum-snapcast-server ls -lh /tmp/shairport-sync/.cache/coverart/

# Should show: cover-<hash>.jpg files with recent timestamps
```

### Frontend Not Updating

- **Check WebSocket**: Open browser console, verify WS connected
- **Check stream properties**: `Server.GetStatus` should include metadata
- **Check React state**: Verify `useEffect` triggers on stream changes

## Configuration

### Shairport-Sync

```conf
metadata = {
    enabled = "yes";
    include_cover_art = "yes";
    cover_art_cache_directory = "/tmp/shairport-sync/.cache/coverart";
    pipe_name = "/tmp/shairport-sync-metadata";
    pipe_timeout = 5000;
};
```

### Supervisord

```ini
[program:airplay-metadata-handler]
command=/usr/bin/python3 -u /app/scripts/process-airplay-metadata.py
user=snapcast
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
```

## References

- [Shairport-Sync Metadata Format](https://github.com/mikebrady/shairport-sync-metadata-reader)
- [Working Implementation](https://github.com/AlainGourves/shairport-metadata-display)
- [Snapcast JSON-RPC API](https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/v2_0_0.md)
- [DMAP Specification](https://en.wikipedia.org/wiki/Digital_Media_Access_Protocol)
