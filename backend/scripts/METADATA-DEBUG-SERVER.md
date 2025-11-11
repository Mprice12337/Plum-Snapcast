# AirPlay Metadata Debug Server

This debug server provides simple HTTP endpoints to inspect AirPlay metadata in real-time.

## Overview

The metadata debug server reads from the same shairport-sync metadata pipe and exposes the data through HTTP endpoints for easy inspection and debugging.

## Endpoints

### 1. `/metadata` - Text Display
**URL:** `http://<raspberry-pi-ip>:8080/metadata`

Shows current metadata in plain text format:
```
AirPlay Metadata Debug
==================================================

Title:   Song Title
Artist:  Artist Name
Album:   Album Name

Artwork: Available
Format:  jpeg

Last Updated: 2025-11-11 12:34:56

==================================================
```

### 2. `/artwork` - Album Art Image
**URL:** `http://<raspberry-pi-ip>:8080/artwork`

Returns the current album artwork as a JPEG or PNG image. You can:
- View it directly in a browser
- Embed it in an `<img>` tag: `<img src="http://<ip>:8080/artwork">`
- Download it for inspection

If no artwork is available, returns a 404 with a message.

### 3. `/status` - JSON Status
**URL:** `http://<raspberry-pi-ip>:8080/status`

Returns metadata in JSON format:
```json
{
  "title": "Song Title",
  "artist": "Artist Name",
  "album": "Album Name",
  "has_artwork": true,
  "artwork_format": "jpeg",
  "last_updated": "2025-11-11 12:34:56",
  "endpoints": {
    "/metadata": "Plain text metadata display",
    "/artwork": "Album artwork image",
    "/status": "This JSON status"
  }
}
```

## Usage

### Quick Test

1. **Play something via AirPlay** to your Plum Audio device from iPhone/Mac

2. **Check metadata in browser:**
   ```
   http://<your-pi-ip>:8080/metadata
   ```

3. **View album art:**
   ```
   http://<your-pi-ip>:8080/artwork
   ```

### Command Line Testing

```bash
# Get metadata as text
curl http://<your-pi-ip>:8080/metadata

# Get JSON status
curl http://<your-pi-ip>:8080/status

# Download album artwork
curl http://<your-pi-ip>:8080/artwork -o artwork.jpg

# Auto-refresh metadata (useful for testing)
watch -n 2 'curl -s http://<your-pi-ip>:8080/metadata'
```

### From Your Desktop

If you're on the same network as your Raspberry Pi:

```bash
# macOS/Linux - display metadata
curl http://raspberrypi.local:8080/metadata

# macOS - open artwork in default image viewer
curl http://raspberrypi.local:8080/artwork -o /tmp/artwork.jpg && open /tmp/artwork.jpg

# Create a live-updating HTML page
cat > /tmp/airplay-debug.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <title>AirPlay Debug</title>
    <style>
        body { font-family: monospace; padding: 20px; }
        img { max-width: 300px; border: 1px solid #ccc; }
        pre { background: #f5f5f5; padding: 15px; }
    </style>
</head>
<body>
    <h1>AirPlay Metadata Debug</h1>
    <h2>Album Artwork</h2>
    <img id="artwork" src="http://raspberrypi.local:8080/artwork" />
    <h2>Metadata</h2>
    <pre id="metadata">Loading...</pre>
    <script>
        setInterval(() => {
            fetch('http://raspberrypi.local:8080/status')
                .then(r => r.json())
                .then(d => {
                    document.getElementById('metadata').textContent = JSON.stringify(d, null, 2);
                    document.getElementById('artwork').src =
                        'http://raspberrypi.local:8080/artwork?' + Date.now();
                });
        }, 2000);
    </script>
</body>
</html>
EOF
open /tmp/airplay-debug.html
```

## How It Works

1. **Metadata Pipe Reader**: A background thread continuously reads from `/tmp/shairport-sync-metadata`

2. **XML Parsing**: Parses shairport-sync's XML metadata format to extract:
   - Title (`minm` code)
   - Artist (`asar` code)
   - Album (`asal` code)
   - Cover art (`PICT` code with base64 data)

3. **Thread-Safe Storage**: Stores the latest metadata in memory with thread locks

4. **HTTP Server**: Serves the data through simple HTTP endpoints on port 8080

## Troubleshooting

### Server Not Starting

Check supervisord status:
```bash
docker exec plum-snapcast-server supervisorctl status metadata-debug-server
```

View logs:
```bash
docker exec plum-snapcast-server tail -f /var/log/supervisord/metadata-debug-server.log
```

### No Metadata Appearing

1. **Check if metadata pipe exists:**
   ```bash
   docker exec plum-snapcast-server ls -la /tmp/shairport-sync-metadata
   ```

2. **Verify shairport-sync is running:**
   ```bash
   docker exec plum-snapcast-server ps aux | grep shairport
   ```

3. **Check shairport-sync config:**
   ```bash
   docker exec plum-snapcast-server cat /app/config/shairport-sync.conf | grep -A 5 metadata
   ```

   Should show:
   ```
   metadata = {
       enabled = "yes";
       include_cover_art = "yes";
       pipe_name = "/tmp/shairport-sync-metadata";
   };
   ```

4. **Play something via AirPlay** - metadata only appears during active playback

### Port 8080 Not Accessible

Since the container uses `network_mode: host`, port 8080 should be directly accessible. If not:

1. **Check if server is listening:**
   ```bash
   docker exec plum-snapcast-server netstat -tlnp | grep 8080
   ```

2. **Check firewall on Raspberry Pi:**
   ```bash
   sudo iptables -L -n | grep 8080
   ```

## Technical Details

- **Language**: Python 3 (uses only stdlib, no external dependencies)
- **Port**: 8080 (HTTP only, no HTTPS)
- **Process Manager**: Supervisord (`/app/supervisord/metadata-debug-server.ini`)
- **Log Location**: `/var/log/supervisord/metadata-debug-server.log`
- **Source Code**: `/app/scripts/metadata-debug-server.py`

## Integration with Main Application

This debug server is independent of the main Snapcast metadata processor. It:

- **Does NOT** update Snapcast stream properties
- **Only reads** from the metadata pipe (non-destructive)
- **Runs in parallel** with the main metadata processor
- **Can be disabled** by removing or commenting out the supervisord config

To disable the debug server without rebuilding:
```bash
docker exec plum-snapcast-server supervisorctl stop metadata-debug-server
docker exec plum-snapcast-server supervisorctl remove metadata-debug-server
```

## Development Notes

Based on the shairport-sync metadata reader:
- Repository: https://github.com/mikebrady/shairport-sync-metadata-reader
- Metadata format: XML items with 4-character codes
- Cover art: Sent in base64-encoded chunks
- Codes used:
  - `asar` - Artist
  - `minm` - Title
  - `asal` - Album
  - `PICT` - Cover art chunks
  - `ssnc` - Control messages (playback start/end)
