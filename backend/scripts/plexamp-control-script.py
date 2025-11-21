#!/usr/bin/env python3
"""
Snapcast Control Script for Plexamp Headless
Monitors Plexamp HTTP API for metadata and provides playback control

Based on proven pattern from spotify-control-script.py:
- Thread-safe metadata storage with atomic updates
- Playback state tracking (Playing/Paused/Stopped)
- Control command handling via HTTP API
- Complete properties response for Snapcast
- Album artwork caching to web root
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Optional
from xml.etree import ElementTree as ET

# Configuration
LOG_FILE = "/tmp/plexamp-control-script.log"
PLEXAMP_API_URL = "http://127.0.0.1:32500"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
COVER_ART_DIR = "/usr/share/snapserver/snapweb/coverart"
POLL_INTERVAL = 2.0  # Poll Plexamp API every 2 seconds

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


class PlexampMetadataMonitor:
    """Monitor Plexamp HTTP API for metadata and playback state"""

    def __init__(self, store: MetadataStore, on_update_callback):
        self.store = store
        self.on_update = on_update_callback
        self.api_url = PLEXAMP_API_URL
        self.running = False
        self.poll_thread = None
        self.last_track_key = None
        log("[Plexamp] Monitor initialized")

    def _http_get(self, path: str) -> Optional[str]:
        """Make HTTP GET request to Plexamp API"""
        try:
            url = f"{self.api_url}{path}"
            req = urllib.request.Request(url, headers={'Accept': 'application/xml'})
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            log(f"[Error] HTTP GET {path} failed: {e}")
            return None

    def _http_post(self, path: str) -> bool:
        """Make HTTP POST request to Plexamp API"""
        try:
            url = f"{self.api_url}{path}"
            req = urllib.request.Request(url, method='POST')
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except Exception as e:
            log(f"[Error] HTTP POST {path} failed: {e}")
            return False

    def _download_cover_art(self, cover_url: str) -> Optional[str]:
        """Download cover art from Plex server and save to web root"""
        if not cover_url:
            return None

        try:
            # Handle relative URLs (add Plex server URL prefix)
            if cover_url.startswith('/'):
                # For now, we'll store the relative path
                # The frontend can construct the full URL using the Plex server address
                # Or we can download from localhost if Plexamp has access
                full_url = f"{self.api_url}{cover_url}"
            else:
                full_url = cover_url

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
            log(f"[Artwork] Downloading from: {full_url[:100]}")
            req = urllib.request.Request(full_url, headers={'User-Agent': 'Snapcast/1.0'})
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
            # Return the original URL as fallback
            return cover_url if not cover_url.startswith('/') else None

    def _parse_timeline(self, xml_data: str) -> Optional[Dict]:
        """Parse Plexamp timeline XML and extract metadata"""
        try:
            root = ET.fromstring(xml_data)

            # Look for Timeline elements (music type)
            for timeline in root.findall('Timeline'):
                if timeline.get('type') == 'music':
                    state = timeline.get('state', 'stopped').lower()

                    # Map Plex states to our format
                    state_map = {
                        'playing': 'Playing',
                        'paused': 'Paused',
                        'stopped': 'Stopped'
                    }
                    playback_status = state_map.get(state, 'Stopped')

                    # Get position (in milliseconds)
                    position = int(timeline.get('time', 0))

                    # Get track key to detect track changes
                    track_key = timeline.get('key')

                    result = {
                        'playback_status': playback_status,
                        'position': position,
                        'track_key': track_key
                    }

                    # Check if this is a new track
                    if track_key and track_key != self.last_track_key:
                        self.last_track_key = track_key
                        log(f"[Timeline] New track detected: {track_key}")

                        # Fetch full track metadata
                        metadata = self._fetch_track_metadata(track_key)
                        if metadata:
                            result.update(metadata)

                    return result

            log("[Timeline] No music timeline found")
            return None

        except Exception as e:
            log(f"[Error] Timeline parsing failed: {e}")
            return None

    def _fetch_track_metadata(self, track_key: str) -> Optional[Dict]:
        """Fetch full track metadata from Plex API"""
        try:
            # Fetch track details
            xml_data = self._http_get(track_key)
            if not xml_data:
                return None

            root = ET.fromstring(xml_data)

            # Find Track element
            track = root.find('.//Track')
            if track is None:
                log("[Metadata] No Track element found")
                return None

            metadata = {}

            # Extract metadata from Track element
            title = track.get('title')
            if title:
                metadata['title'] = title
                log(f"[Metadata] Title: {title}")

            # Artist (grandparentTitle in Plex music hierarchy)
            artist = track.get('grandparentTitle') or track.get('originalTitle')
            if artist:
                metadata['artist'] = artist
                log(f"[Metadata] Artist: {artist}")

            # Album (parentTitle in Plex music hierarchy)
            album = track.get('parentTitle')
            if album:
                metadata['album'] = album
                log(f"[Metadata] Album: {album}")

            # Duration (in milliseconds)
            duration = track.get('duration')
            if duration:
                metadata['duration'] = int(duration)
                log(f"[Metadata] Duration: {duration}ms")

            # Album art (thumb attribute)
            thumb = track.get('thumb') or track.get('parentThumb') or track.get('grandparentThumb')
            if thumb:
                log(f"[Metadata] Album Art URL: {thumb}")
                local_art_url = self._download_cover_art(thumb)
                if local_art_url:
                    metadata['artUrl'] = local_art_url

            return metadata

        except Exception as e:
            log(f"[Error] Metadata fetch failed: {e}")
            return None

    def _poll_loop(self):
        """Background thread that polls Plexamp timeline"""
        log("[Plexamp] Starting timeline polling...")

        while self.running:
            try:
                # Poll timeline endpoint
                xml_data = self._http_get('/player/timeline/poll?wait=0')

                if xml_data:
                    timeline_data = self._parse_timeline(xml_data)

                    if timeline_data:
                        # Update store with new data
                        self.store.update(**timeline_data)

                        # Notify parent
                        if self.on_update:
                            self.on_update()

                # Sleep before next poll
                time.sleep(POLL_INTERVAL)

            except Exception as e:
                log(f"[Error] Poll loop error: {e}")
                time.sleep(POLL_INTERVAL)

    def start(self):
        """Start monitoring Plexamp"""
        log("[Plexamp] Starting metadata monitoring...")
        self.running = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    def stop(self):
        """Stop monitoring"""
        log("[Plexamp] Stopping metadata monitoring...")
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=5)

    def play(self):
        """Send play command"""
        success = self._http_post('/player/playback/play')
        if success:
            log("[Control] Sent Play command")
            self.store.update(playback_status="Playing")
        return success

    def pause(self):
        """Send pause command"""
        success = self._http_post('/player/playback/pause')
        if success:
            log("[Control] Sent Pause command")
            self.store.update(playback_status="Paused")
        return success

    def next_track(self):
        """Skip to next track"""
        success = self._http_post('/player/playback/skipNext')
        if success:
            log("[Control] Sent Next command")
        return success

    def previous_track(self):
        """Skip to previous track"""
        success = self._http_post('/player/playback/skipPrevious')
        if success:
            log("[Control] Sent Previous command")
        return success

    def is_available(self):
        """Check if Plexamp is available"""
        # Try to get timeline to check if Plexamp is running
        xml_data = self._http_get('/player/timeline/poll?wait=0')
        return xml_data is not None


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.store = MetadataStore()
        self.plexamp_monitor = PlexampMetadataMonitor(self.store, self.send_update)
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
        can_control = self.plexamp_monitor.is_available()

        # Notification params: include stream ID and all properties
        params = {
            "id": self.stream_id,  # Include stream ID so frontend knows which stream to update

            # Playback state
            "playbackStatus": playback_status,
            "loopStatus": "none",
            "shuffle": False,
            "volume": 100,
            "mute": False,
            "rate": 1.0,
            "position": position,

            # Control capabilities
            "canGoNext": can_control,
            "canGoPrevious": can_control,
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
                can_control = self.plexamp_monitor.is_available()

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
                    "canGoNext": can_control,
                    "canGoPrevious": can_control,
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

                if not self.plexamp_monitor.is_available():
                    # Return error if Plexamp not available
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Control not available (Plexamp not connected)"
                        }
                    }
                    print(json.dumps(error_response), file=sys.stdout, flush=True)
                    return

                # Execute command via HTTP API and update state
                success = False
                if command == "play":
                    success = self.plexamp_monitor.play()
                elif command == "pause":
                    success = self.plexamp_monitor.pause()
                elif command == "playPause":
                    # Toggle state
                    current_state = self.store.get_all().get("playback_status", "Paused")
                    if current_state == "Playing":
                        success = self.plexamp_monitor.pause()
                    else:
                        success = self.plexamp_monitor.play()
                elif command == "next":
                    success = self.plexamp_monitor.next_track()
                elif command == "previous" or command == "prev":
                    success = self.plexamp_monitor.previous_track()
                else:
                    log(f"[Warning] Unknown control command: {command}")

                if success:
                    self.send_update()

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
        log("[Main] Plexamp Control Script starting...")

        # Start metadata monitor in background thread
        self.plexamp_monitor.start()

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
            self.plexamp_monitor.stop()


if __name__ == "__main__":
    # Parse command line arguments passed by Snapcast
    parser = argparse.ArgumentParser(description='Plexamp metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default='Plexamp', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    log(f"[Main] Starting with args: stream={args.stream}, host={args.snapcast_host}, port={args.snapcast_port}")

    script = SnapcastControlScript(stream_id=args.stream)
    script.run()
