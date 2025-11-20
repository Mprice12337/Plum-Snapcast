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
from pathlib import Path
from typing import Dict, Optional

# Configuration
LOG_FILE = "/tmp/dlna-control-script.log"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
COVER_ART_DIR = "/usr/share/snapserver/snapweb/coverart"
METADATA_FILE = "/tmp/dlna-metadata.json"

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

        # DLNA/UPnP supports basic playback controls
        can_control = playback_status != "Stopped"

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

            # Control capabilities (limited for DLNA)
            "canGoNext": False,  # DLNA doesn't typically support skip
            "canGoPrevious": False,
            "canPlay": can_control,
            "canPause": can_control,
            "canSeek": False,
            "canControl": can_control,

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
                can_control = playback_status != "Stopped"

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

                    # Control capabilities
                    "canGoNext": False,
                    "canGoPrevious": False,
                    "canPlay": can_control,
                    "canPause": can_control,
                    "canSeek": False,
                    "canControl": can_control,

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

                # DLNA control is handled by the controller, not the renderer
                # We can only report status changes, not actively control playback

                # Send success response
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
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
