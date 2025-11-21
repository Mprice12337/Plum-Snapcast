# DLNA/UPnP Implementation Summary

## Overview

DLNA/UPnP support enables streaming audio from any DLNA/UPnP control point (such as BubbleUPnP, mConnect, or Windows Media Player) to the Snapcast system via gmrender-resurrect.

## Architecture

```
DLNA Controller (Phone/Tablet/PC)
         ↓
   gmrender-resurrect (UPnP Media Renderer)
         ↓
   /tmp/dlna-fifo (FIFO pipe)
         ↓
   Snapcast Server
         ↓
   Audio Output
```

## Components

### 1. gmrender-resurrect
- **Purpose**: UPnP/DLNA media renderer
- **Source**: https://github.com/hzeller/gmrender-resurrect
- **Build**: Compiled from source in Dockerfile
- **Configuration**: Supervisord process with GStreamer audio pipeline
- **Output**: 44.1kHz, 16-bit stereo PCM to FIFO pipe

### 2. gmrender-metadata-bridge.py
- **Purpose**: Extract metadata from gmrender logs
- **Method**: Parses stdout logs in real-time using `tail -F`
- **Extracts**: Title, artist, album, artwork URL from DIDL-Lite XML
- **Output**: JSON file at `/tmp/dlna-metadata.json`
- **Pattern**: Based on HiFiBerry's dlna-mpris approach

### 3. dlna-control-script.py
- **Purpose**: Snapcast control script for DLNA stream
- **Features**:
  - Monitors metadata JSON file
  - Downloads and caches album artwork
  - Provides playback control via UPnP SOAP API
  - Dynamic port discovery for gmrender
  - Implements Snapcast Stream Plugin API

## Key Implementation Details

### UPnP Control
- **Control URL**: `/upnp/control/rendertransport1` (not `/upnp/control/AVTransport1`)
- **Service**: `urn:schemas-upnp-org:service:AVTransport:1`
- **Supported Actions**: Play, Pause, Stop
- **Discovery**: Device description at `http://IP:PORT/description.xml`

### Port Discovery
gmrender uses dynamically allocated ports (typically 49494). The control script discovers this via:
1. **Primary**: Parse `netstat` output for port pattern `:494`
2. **Fallback**: Socket connection test to common UPnP ports
3. **Network IP**: Detects actual interface IP (e.g., 192.168.7.122)

### Metadata Parsing
DIDL-Lite XML from gmrender logs contains namespace prefixes that must be stripped:
```python
# Strip namespace prefixes: dc:title → title, upnp:album → album
didl_xml = re.sub(r'<(/?)(\w+):', r'<\1', didl_xml)
```

### Album Artwork
- Artwork URLs extracted from UPnP metadata
- Downloaded and cached to `/usr/share/snapserver/snapweb/coverart/`
- Filename: MD5 hash of URL
- Served via Snapcast web server

## Configuration

### Environment Variables
- `DLNA_ENABLED`: Enable/disable DLNA renderer (0/1, default: 0)
- `DLNA_DEVICE_NAME`: Name shown in DLNA controllers (default: "Plum Audio")
- `DLNA_SOURCE_NAME`: Stream name in Snapcast UI (default: "DLNA")
- `DLNA_UUID`: Custom UPnP UUID (optional, auto-generated if not set)

### Supervisord Processes
```ini
[program:gmrender]
- Runs gmrender-resurrect with GStreamer pipeline
- Priority: 50
- Starts after avahi (5-second delay)

[program:gmrender-metadata-bridge]
- Monitors gmrender logs for metadata
- Priority: 55
- Starts after gmrender (10-second delay)
```

## Testing

### Compatible Controllers
- **BubbleUPnP** (Android/iOS) - Tested with Plex and Tidal sources
- **mConnect** (Android/iOS)
- **Windows Media Player**
- **Any DLNA/UPnP control point**

### Verification Commands
```bash
# Check gmrender is running
docker exec plum-snapcast-server ps aux | grep gmediarender

# Check port and IP
docker exec plum-snapcast-server netstat -tlnp | grep gmediarender

# Monitor control commands
docker exec plum-snapcast-server tail -f /tmp/dlna-control-script.log | grep -E "(Discovery|UPnP|Control)"

# Check metadata extraction
docker exec plum-snapcast-server cat /tmp/dlna-metadata.json
```

## Troubleshooting

### Issue: gmrender not discovered
**Solution**: Check netstat output shows gmrender listening:
```bash
docker exec plum-snapcast-server netstat -tlnp | grep gmediarender
```

### Issue: HTTP 404 on control commands
**Cause**: Wrong control URL path
**Solution**: Verify device description XML shows `/upnp/control/rendertransport1`

### Issue: No metadata showing
**Cause**: Metadata bridge not running or XML parsing error
**Solution**: Check bridge logs for "unbound prefix" errors

### Issue: Connection refused
**Cause**: gmrender binds to external interface IP, not localhost
**Solution**: Control script auto-detects correct IP via netstat

## Limitations

- **Skip Commands**: Not supported in UPnP renderer (controller-side only)
- **Seek**: Not implemented
- **Volume Control**: Handled by Snapcast, not gmrender
- **Playlist Management**: Controller responsibility

## Future Enhancements

Possible improvements:
- Dynamic control URL discovery from device description XML
- Support for additional UPnP services (RenderingControl)
- Seek position tracking and control
- Better error recovery and reconnection logic
