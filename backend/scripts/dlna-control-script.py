#!/usr/bin/env python3
"""
Snapcast Control Script for DLNA/UPnP (gmrender-resurrect)
Monitors UPnP AVTransport events for metadata and provides playback control

Architecture:
- gmrender-resurrect receives DLNA/UPnP streams from controllers
- GStreamer pipeline processes and outputs to FIFO pipe
- This script extracts metadata from UPnP events and provides control interface
- Snapcast reads from FIFO and serves to clients

Based on proven pattern from spotify-control-script.py:
- Thread-safe metadata storage with atomic updates
- Playback state tracking (Playing/Paused/Stopped)
- Control command handling via UPnP AVTransport
- Complete properties response for Snapcast
- Album artwork extraction from UPnP metadata
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
import socket
from pathlib import Path
from typing import Dict, Optional

# Configuration
LOG_FILE = "/tmp/dlna-control-script.log"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
COVER_ART_DIR = "/usr/share/snapserver/snapweb/coverart"
METADATA_FILE = "/tmp/dlna-metadata.json"

# Global for dynamically discovered gmrender port and host
_gmrender_host = None
_gmrender_port = None
_gmrender_control_url = None

# Set up logging to file
def log(message: str):
    """Log to both stderr and a file"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"{timestamp} {message}"
    print(log_msg, file=sys.stderr, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(log_msg + "\n")
    except:
        pass

def discover_gmrender_endpoint() -> tuple:
    """
    Discover the dynamically allocated host and port gmrender is listening on.

    Returns:
        Tuple of (host, port) if found, (None, None) otherwise
    """
    try:
        # Try to find gmrender's listening endpoint via netstat
        # Use head -1 to get only the first match (IPv4 address)
        # Extract the full "host:port" from column 4
        result = os.popen("netstat -tln 2>/dev/null | grep ':494' | head -1 | awk '{print $4}'").read().strip()
        if result and ':' in result:
            # Parse host:port
            parts = result.rsplit(':', 1)  # rsplit to handle IPv6 [::]:port format
            if len(parts) == 2:
                host = parts[0]
                port_str = parts[1]

                if port_str.isdigit():
                    port = int(port_str)
                    # Keep the IP as-is from netstat
                    # With host networking mode, we can reach gmrender at whatever IP it binds to
                    log(f"[Discovery] Found gmrender on {host}:{port} via netstat")
                    return (host, port)

        # Fallback: Get the actual network interface IP and try common ports
        log("[Discovery] netstat didn't find gmrender, trying fallback...")

        # Try to get the machine's actual IP address
        local_ip = None
        try:
            # Get IP by connecting to an external address (doesn't actually send data)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            log(f"[Discovery] Detected local IP: {local_ip}")
        except:
            pass

        # Try both localhost and the actual network IP
        hosts_to_try = ['127.0.0.1']
        if local_ip and local_ip != '127.0.0.1':
            hosts_to_try.append(local_ip)

        for host in hosts_to_try:
            for port in [49494, 49152, 49153, 49154]:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    if result == 0:
                        log(f"[Discovery] Found open port {host}:{port}, testing if it's gmrender...")
                        # Try to fetch device description
                        try:
                            with urllib.request.urlopen(f'http://{host}:{port}/', timeout=1) as response:
                                data = response.read().decode('utf-8')
                                if 'GMediaRender' in data or 'gmediarender' in data or 'AVTransport' in data:
                                    log(f"[Discovery] Confirmed gmrender on {host}:{port}")
                                    return (host, port)
                        except Exception as http_err:
                            log(f"[Discovery] HTTP check failed for {host}:{port}: {http_err}")
                except Exception as scan_error:
                    pass  # Don't log every failed connection attempt

        log("[Discovery] Could not discover gmrender endpoint")
        return (None, None)
    except Exception as e:
        log(f"[Discovery] Error discovering endpoint: {e}")
        import traceback
        log(traceback.format_exc())
        return (None, None)

def get_gmrender_control_url() -> Optional[str]:
    """Get gmrender control URL, discovering endpoint if needed"""
    global _gmrender_host, _gmrender_port, _gmrender_control_url

    if _gmrender_control_url:
        return _gmrender_control_url

    if not _gmrender_host or not _gmrender_port:
        _gmrender_host, _gmrender_port = discover_gmrender_endpoint()
        if not _gmrender_host or not _gmrender_port:
            return None

    _gmrender_control_url = f"http://{_gmrender_host}:{_gmrender_port}/upnp/control/rendertransport1"
    log(f"[Discovery] Using control URL: {_gmrender_control_url}")
    return _gmrender_control_url

def send_upnp_control(action: str) -> bool:
    """
    Send UPnP AVTransport control command to gmrender-resurrect

    Args:
        action: UPnP action (Play, Pause, Stop, etc.)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get gmrender control URL (discovers port on first call)
        control_url = get_gmrender_control_url()
        if not control_url:
            log(f"[UPnP] {action} command failed: gmrender port not found")
            return False

        soap_body = f'''<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:{action}>
  </s:Body>
</s:Envelope>'''

        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPAction': f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
            'Content-Length': str(len(soap_body))
        }

        request = urllib.request.Request(
            control_url,
            data=soap_body.encode('utf-8'),
            headers=headers,
            method='POST'
        )

        with urllib.request.urlopen(request, timeout=2) as response:
            status = response.getcode()
            if status == 200:
                log(f"[UPnP] {action} command sent successfully")
                return True
            else:
                log(f"[UPnP] {action} command failed with status {status}")
                return False

    except urllib.error.URLError as e:
        log(f"[UPnP] {action} command failed: {e}")
        # Reset cached URL on connection error (endpoint may have changed)
        global _gmrender_host, _gmrender_port, _gmrender_control_url
        _gmrender_host = None
        _gmrender_port = None
        _gmrender_control_url = None
        return False
    except Exception as e:
        log(f"[UPnP] {action} command error: {e}")
        return False

# Try to import D-Bus - graceful fallback if not available
try:
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    log("[Warning] D-Bus not available - DLNA control features disabled")


class MetadataStore:
    """
    Thread-safe storage for current metadata and playback state.
    This ensures atomic reads/writes and consistency.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "title": None,
            "artist": None,
            "album": None,
            "artUrl": None,
            "duration": None,
            "position": 0,
            "last_updated": None,
            "playback_status": "Stopped",  # "Playing", "Paused", or "Stopped"
        }

    def update(self, **kwargs):
        """Update metadata fields atomically"""
        with self.lock:
            self.data.update(kwargs)
            self.data["last_updated"] = time.time()
            log(f"[Store] Updated: {list(kwargs.keys())}")

    def get_all(self) -> Dict:
        """Get all metadata (returns a copy)"""
        with self.lock:
            return self.data.copy()

    def get_metadata_for_snapcast(self) -> Optional[Dict]:
        """
        Get metadata formatted for Snapcast.

        Snapcast expects simple field names:
        - title (string)
        - artist (array of strings)
        - album (string)
        - artUrl (string)
        """
        with self.lock:
            # Only return if we have at least a title
            if self.data.get("title"):
                meta = {}

                # Snapcast metadata fields (simple names)
                if self.data.get("title"):
                    meta["title"] = self.data["title"]

                if self.data.get("artist"):
                    # Snapcast expects artist as an array
                    artist = self.data["artist"]
                    meta["artist"] = [artist] if isinstance(artist, str) else artist

                if self.data.get("album"):
                    meta["album"] = self.data["album"]

                if self.data.get("artUrl"):
                    meta["artUrl"] = self.data["artUrl"]

                if self.data.get("duration"):
                    meta["duration"] = self.data["duration"]

                return meta
            return None


class DLNAMetadataMonitor:
    """Monitor gmrender-resurrect via metadata file for DLNA metadata and playback state"""

    def __init__(self, store: MetadataStore, on_update_callback):
        self.store = store
        self.on_update = on_update_callback
        self.running = False
        self.monitor_thread = None

        log("[DLNA] Metadata monitor initialized")

    def _download_cover_art(self, cover_url: str) -> Optional[str]:
        """Download cover art from URL and save to web root"""
        if not cover_url:
            return None

        try:
            # Create a filename from the URL
            url_hash = hashlib.md5(cover_url.encode()).hexdigest()
            filename = f"{url_hash}.jpg"

            # Save to Snapcast web root so it's accessible via HTTP
            cover_dir = Path(COVER_ART_DIR)
            cover_dir.mkdir(parents=True, exist_ok=True)
            cover_path = cover_dir / filename

            # Check if already downloaded
            if cover_path.exists():
                log(f"[Artwork] Cached: {filename}")
                return f"/coverart/{filename}"

            # Download cover art
            log(f"[Artwork] Downloading from: {cover_url[:100]}")
            req = urllib.request.Request(cover_url, headers={'User-Agent': 'Snapcast/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                cover_data = response.read()

            # Save to web root
            with open(cover_path, "wb") as f:
                f.write(cover_data)

            # Make sure the file is readable by the web server
            os.chmod(cover_path, 0o644)

            log(f"[Artwork] Downloaded: {len(cover_data)} bytes → /coverart/{filename}")
            return f"/coverart/{filename}"

        except Exception as e:
            log(f"[Error] Artwork download failed: {e}")
            return None

    def _parse_metadata_file(self) -> Optional[Dict]:
        """Parse metadata from JSON file written by gmrender or external monitor"""
        try:
            if not os.path.exists(METADATA_FILE):
                return None

            with open(METADATA_FILE, 'r') as f:
                data = json.load(f)

            result = {}

            if 'title' in data and data['title']:
                result['title'] = data['title']
                log(f"[Metadata] Title: {result['title']}")

            if 'artist' in data and data['artist']:
                result['artist'] = data['artist']
                log(f"[Metadata] Artist: {result['artist']}")

            if 'album' in data and data['album']:
                result['album'] = data['album']
                log(f"[Metadata] Album: {result['album']}")

            if 'artUrl' in data and data['artUrl']:
                art_url = data['artUrl']
                log(f"[Metadata] Album Art URL: {art_url[:100]}")

                # Download and cache the artwork if it's a URL
                if art_url.startswith('http'):
                    local_art_url = self._download_cover_art(art_url)
                    if local_art_url:
                        result['artUrl'] = local_art_url
                else:
                    result['artUrl'] = art_url

            if 'duration' in data and data['duration']:
                result['duration'] = int(data['duration'])
                log(f"[Metadata] Duration: {result['duration']}ms")

            if 'status' in data:
                result['playback_status'] = data['status']
                log(f"[Metadata] Status: {result['playback_status']}")

            return result if result else None

        except Exception as e:
            log(f"[Error] Metadata file parsing failed: {e}")
            return None

    def _monitor_metadata_file(self):
        """Monitor metadata file for changes"""
        last_mtime = 0
        last_metadata = None

        while self.running:
            try:
                if os.path.exists(METADATA_FILE):
                    mtime = os.path.getmtime(METADATA_FILE)
                    if mtime > last_mtime:
                        last_mtime = mtime
                        metadata = self._parse_metadata_file()

                        if metadata and metadata != last_metadata:
                            last_metadata = metadata
                            self.store.update(**metadata)

                            if self.on_update:
                                self.on_update()
            except Exception as e:
                log(f"[Error] Metadata monitoring error: {e}")

            time.sleep(0.5)  # Check every 500ms

    def start(self):
        """Start monitoring for DLNA metadata"""
        log("[DLNA] Starting metadata monitoring...")

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_metadata_file, daemon=True)
        self.monitor_thread.start()

        log("[DLNA] Metadata file monitoring started")

    def stop(self):
        """Stop monitoring"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.store = MetadataStore()
        self.dlna_monitor = DLNAMetadataMonitor(self.store, self.send_update)
        log(f"[Init] Initialized for stream: {stream_id}")

    def send_notification(self, method: str, params: Dict):
        """Send JSON-RPC notification to Snapcast via stdout"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        print(json.dumps(notification), file=sys.stdout, flush=True)
        log(f"[Snapcast] → {method}")

    def send_update(self):
        """Send Plugin.Stream.Player.Properties with current state and metadata"""
        meta_obj = self.store.get_metadata_for_snapcast() or {}
        state_data = self.store.get_all()
        playback_status = state_data.get("playback_status", "Stopped")
        position = state_data.get("position", 0)

        # DLNA/UPnP supports basic playback controls when content is loaded
        # We can control if we have metadata (track is loaded) or not stopped
        has_content = bool(meta_obj) or playback_status != "Stopped"

        # Notification params: include stream ID and all properties
        params = {
            "id": self.stream_id,

            # Playback state
            "playbackStatus": playback_status,
            "loopStatus": "none",
            "shuffle": False,
            "volume": 100,
            "mute": False,
            "rate": 1.0,
            "position": position,

            # Control capabilities - DLNA supports Play/Pause via UPnP AVTransport
            "canGoNext": False,  # Skip not supported in UPnP renderer
            "canGoPrevious": False,
            "canPlay": has_content,
            "canPause": has_content,
            "canSeek": False,
            "canControl": has_content,

            # Metadata (simple field names)
            "metadata": meta_obj
        }
        self.send_notification("Plugin.Stream.Player.Properties", params)

        # Log what we sent
        if meta_obj:
            title = meta_obj.get('title', 'N/A')
            artist = meta_obj.get('artist', ['N/A'])
            artist_str = artist[0] if isinstance(artist, list) and artist else 'N/A'
            log(f"[Snapcast] Metadata → {title} - {artist_str} [{playback_status}] (stream={self.stream_id})")
            if "artUrl" in meta_obj:
                log(f"[Snapcast]   Artwork: {meta_obj['artUrl']}")
        else:
            log(f"[Snapcast] State → [{playback_status}] (stream={self.stream_id})")

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")
            params = request.get("params", {})

            log(f"[Command] Received: {method} (id={request_id})")

            if method == "Plugin.Stream.Player.GetProperties":
                # Return COMPLETE properties object
                meta_obj = self.store.get_metadata_for_snapcast() or {}
                state_data = self.store.get_all()
                playback_status = state_data.get("playback_status", "Stopped")
                position = state_data.get("position", 0)
                has_content = bool(meta_obj) or playback_status != "Stopped"

                # Build complete properties response per Snapcast Stream Plugin API
                properties = {
                    # Playback state
                    "playbackStatus": playback_status,
                    "loopStatus": "none",
                    "shuffle": False,
                    "volume": 100,
                    "mute": False,
                    "rate": 1.0,
                    "position": position,

                    # Control capabilities - DLNA supports Play/Pause via UPnP AVTransport
                    "canGoNext": False,
                    "canGoPrevious": False,
                    "canPlay": has_content,
                    "canPause": has_content,
                    "canSeek": False,
                    "canControl": has_content,

                    # Metadata
                    "metadata": meta_obj
                }

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": properties
                }
                print(json.dumps(response), file=sys.stdout, flush=True)
                log(f"[Snapcast] GetProperties → status={playback_status}, metadata keys: {list(meta_obj.keys())}")

            elif method == "Plugin.Stream.Player.Control" or method == "Plugin.Stream.Control":
                # Handle playback control commands
                command = params.get("command", "")
                log(f"[Control] Received control command: {command} (params={params})")

                # Send UPnP AVTransport control command to gmrender
                success = False
                if command == "play":
                    success = send_upnp_control("Play")
                elif command == "pause":
                    success = send_upnp_control("Pause")
                elif command == "stop":
                    success = send_upnp_control("Stop")
                else:
                    log(f"[Control] Unsupported command: {command}")

                # Send response
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"success": success}
                }
                print(json.dumps(response), file=sys.stdout, flush=True)

        except json.JSONDecodeError:
            log(f"[Error] Invalid JSON: {line}")
        except Exception as e:
            log(f"[Error] Command handling failed: {e}")
            import traceback
            log(traceback.format_exc())

    def run(self):
        """Main event loop"""
        log("[Main] DLNA Control Script starting...")

        # Discover gmrender control port at startup
        log("[Main] Discovering gmrender UPnP control port...")
        control_url = get_gmrender_control_url()
        if control_url:
            log(f"[Main] gmrender ready for control at {control_url}")
        else:
            log("[Main] Warning: Could not discover gmrender port - controls may not work")

        # Start metadata monitor
        self.dlna_monitor.start()

        # Send Plugin.Stream.Ready notification
        self.send_notification("Plugin.Stream.Ready", {})
        log("[Main] Sent Plugin.Stream.Ready notification")

        # Process commands from stdin (from Snapcast)
        log("[Main] Listening for commands on stdin...")
        try:
            for line in sys.stdin:
                line = line.strip()
                if line:
                    self.handle_command(line)
        except KeyboardInterrupt:
            log("[Main] Shutting down...")
        except Exception as e:
            log(f"[Main] Fatal error: {e}")
            import traceback
            log(traceback.format_exc())
        finally:
            self.dlna_monitor.stop()


if __name__ == "__main__":
    # Parse command line arguments passed by Snapcast
    parser = argparse.ArgumentParser(description='DLNA/UPnP metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default='DLNA', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    log(f"[Main] Starting with args: stream={args.stream}, host={args.snapcast_host}, port={args.snapcast_port}")

    script = SnapcastControlScript(stream_id=args.stream)
    script.run()
