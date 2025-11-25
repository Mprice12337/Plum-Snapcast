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
PLEXAMP_STATE_FILE = "/tmp/plexamp-state/.local/share/Plexamp/PlayQueue.json"
PLEXAMP_RESOURCES_FILE = "/tmp/plexamp-state/.local/share/Plexamp/Settings/%40Plexamp%3Aresources"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
COVER_ART_DIR = "/usr/share/snapserver/snapweb/coverart"
POLL_INTERVAL = 2.0  # Poll PlayQueue.json every 2 seconds

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
    """Monitor Plexamp PlayQueue.json file for metadata and playback state"""

    def __init__(self, store: MetadataStore, on_update_callback):
        self.store = store
        self.on_update = on_update_callback
        self.state_file = PLEXAMP_STATE_FILE
        self.resources_file = PLEXAMP_RESOURCES_FILE
        self.running = False
        self.poll_thread = None
        self.last_track_id = None
        self.last_mtime = 0
        self.plex_server_uri = None
        log(f"[Plexamp] Monitor initialized, watching: {self.state_file}")

    def _get_plex_server_uri(self) -> Optional[str]:
        """Extract Plex server URI from resources file"""
        if self.plex_server_uri:
            return self.plex_server_uri

        try:
            import os
            if not os.path.exists(self.resources_file):
                log(f"[Error] Resources file not found: {self.resources_file}")
                return None

            with open(self.resources_file, 'r') as f:
                resources = json.load(f)

            # Resources is a dict with server IDs as keys
            if isinstance(resources, dict):
                for server_id, resource in resources.items():
                    if resource.get('provides') == 'server' and 'connections' in resource:
                        for conn in resource['connections']:
                            if 'uri' in conn:
                                self.plex_server_uri = conn['uri']
                                log(f"[Plex] Found server URI: {self.plex_server_uri}")
                                return self.plex_server_uri

            # Fallback: also handle list format (in case structure changes)
            elif isinstance(resources, list):
                for resource in resources:
                    if resource.get('provides') == 'server' and 'connections' in resource:
                        for conn in resource['connections']:
                            if 'uri' in conn:
                                self.plex_server_uri = conn['uri']
                                log(f"[Plex] Found server URI: {self.plex_server_uri}")
                                return self.plex_server_uri

            log("[Error] Could not find Plex server URI in resources")
            return None

        except Exception as e:
            log(f"[Error] Failed to read Plex server URI: {e}")
            return None

    def _read_playqueue(self) -> Optional[Dict]:
        """Read and parse PlayQueue.json file"""
        try:
            import os
            if not os.path.exists(self.state_file):
                return None

            # Check if file has changed
            mtime = os.path.getmtime(self.state_file)

            with open(self.state_file, 'r') as f:
                data = json.load(f)

            # Update last modification time
            self.last_mtime = mtime
            return data
        except FileNotFoundError:
            log(f"[Error] PlayQueue file not found: {self.state_file}")
            return None
        except json.JSONDecodeError as e:
            log(f"[Error] Failed to parse PlayQueue JSON: {e}")
            return None
        except Exception as e:
            log(f"[Error] Failed to read PlayQueue: {e}")
            return None

    def _download_cover_art(self, cover_url: str) -> Optional[str]:
        """Download cover art from Plex server and save to web root"""
        if not cover_url:
            return None

        try:
            # Get Plex server URI
            server_uri = self._get_plex_server_uri()
            if not server_uri:
                log("[Error] Cannot download artwork: no Plex server URI")
                return None

            # Handle relative URLs (add Plex server URL prefix)
            if cover_url.startswith('/'):
                full_url = f"{server_uri}{cover_url}"
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

            # Download cover art (disable SSL verification for self-signed Plex certs)
            log(f"[Artwork] Downloading from: {full_url[:100]}")
            import ssl
            ssl_context = ssl._create_unverified_context()
            req = urllib.request.Request(full_url, headers={'User-Agent': 'Snapcast/1.0'})
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
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

    def _parse_playqueue(self, playqueue_data: Dict) -> Optional[Dict]:
        """Parse PlayQueue.json and extract current track metadata"""
        try:
            # Navigate the nested structure
            if 'data' not in playqueue_data or 'MediaContainer' not in playqueue_data['data']:
                log("[PlayQueue] Invalid structure: missing data.MediaContainer")
                return None

            container = playqueue_data['data']['MediaContainer']

            # Get currently selected track
            if 'Metadata' not in container or not container['Metadata']:
                log("[PlayQueue] No tracks in queue")
                return None

            # Currently playing track is the first in the Metadata array
            track = container['Metadata'][0]
            track_id = track.get('playQueueItemID')

            result = {}

            # Check if this is a new track
            if track_id and track_id != self.last_track_id:
                self.last_track_id = track_id
                log(f"[PlayQueue] New track detected: {track_id}")

                # Extract metadata
                title = track.get('title')
                if title:
                    result['title'] = title
                    log(f"[Metadata] Title: {title}")

                # Artist (grandparentTitle in Plex music hierarchy)
                artist = track.get('grandparentTitle')
                if artist:
                    result['artist'] = artist
                    log(f"[Metadata] Artist: {artist}")

                # Album (parentTitle in Plex music hierarchy)
                album = track.get('parentTitle')
                if album:
                    result['album'] = album
                    log(f"[Metadata] Album: {album}")

                # Duration (in milliseconds)
                duration = track.get('duration')
                if duration:
                    result['duration'] = int(duration)
                    log(f"[Metadata] Duration: {duration}ms")

                # Album art
                thumb = track.get('thumb') or track.get('parentThumb') or track.get('grandparentThumb')
                if thumb:
                    log(f"[Metadata] Album Art URL: {thumb}")
                    # Download artwork from Plex server
                    local_art_url = self._download_cover_art(thumb)
                    if local_art_url:
                        result['artUrl'] = local_art_url

            # Note: Playback state and position are now retrieved separately via timeline API
            # Don't set them here to avoid overwriting timeline data

            return result if result else None

        except Exception as e:
            log(f"[Error] PlayQueue parsing failed: {e}")
            import traceback
            log(traceback.format_exc())
            return None

    def _poll_loop(self):
        """Background thread that polls PlayQueue.json file and timeline API

        Continuously polls position and sends updates to frontend:
        - Every 5 seconds during normal playback
        - Immediately when position jumps (seek/scrub detected)
        - On track change
        """
        log("[Plexamp] Starting PlayQueue monitoring...")

        last_position = None
        last_sent_position = None
        update_counter = 0

        while self.running:
            try:
                metadata_updated = False

                # Read PlayQueue.json for metadata
                playqueue_data = self._read_playqueue()

                if playqueue_data:
                    # Parse and extract metadata
                    metadata = self._parse_playqueue(playqueue_data)

                    if metadata:
                        # Update store with new data
                        self.store.update(**metadata)
                        metadata_updated = True

                # Query timeline API for position and playback state
                timeline = self.get_timeline()
                if timeline:
                    position_ms = timeline.get('position')
                    playback_status = timeline.get('playback_status', 'Stopped')

                    # Always update store with latest position
                    self.store.update(**timeline)

                    # Check if position jumped (seek or mid-track start)
                    position_jumped = False
                    if position_ms and last_position is not None:
                        # Expected position is last_position + 1 second (1000ms) for 1Hz polling
                        # But we poll every 2s, so expect +2000ms
                        expected_position = last_position + (POLL_INTERVAL * 1000)
                        # Position jumped if it's more than 3 seconds off from expected
                        position_jumped = abs(position_ms - expected_position) > 3000

                    # Send update if:
                    # 1. Every 5 polls (~10 seconds at 2s intervals)
                    # 2. Position jumped (seek or mid-track start)
                    # 3. First update (last_sent_position is None)
                    # 4. Metadata changed (new track)
                    update_counter += 1
                    should_send = (
                        update_counter >= 5 or
                        position_jumped or
                        last_sent_position is None or
                        metadata_updated
                    )

                    if should_send and playback_status != 'Stopped':
                        reason = "periodic" if update_counter >= 5 else (
                            "jumped" if position_jumped else (
                                "metadata" if metadata_updated else "initial"
                            )
                        )
                        log(f"[Timeline] Position update: {position_ms}ms ({reason})")
                        if self.on_update:
                            self.on_update()

                        last_sent_position = position_ms
                        update_counter = 0

                    last_position = position_ms
                elif metadata_updated:
                    # Send update for metadata even without timeline
                    if self.on_update:
                        self.on_update()

                # Sleep before next poll
                time.sleep(POLL_INTERVAL)

            except Exception as e:
                log(f"[Error] Poll loop error: {e}")
                import traceback
                log(traceback.format_exc())
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
        """Send play command via Plexamp HTTP API"""
        try:
            req = urllib.request.Request('http://127.0.0.1:32500/player/playback/play')
            with urllib.request.urlopen(req, timeout=2) as response:
                log(f"[Control] Play command sent (status={response.status})")
                return response.status == 200
        except Exception as e:
            log(f"[Control] Play command failed: {e}")
            return False

    def pause(self):
        """Send pause command via Plexamp HTTP API"""
        try:
            req = urllib.request.Request('http://127.0.0.1:32500/player/playback/pause')
            with urllib.request.urlopen(req, timeout=2) as response:
                log(f"[Control] Pause command sent (status={response.status})")
                return response.status == 200
        except Exception as e:
            log(f"[Control] Pause command failed: {e}")
            return False

    def next_track(self):
        """Skip to next track via Plexamp HTTP API"""
        try:
            req = urllib.request.Request('http://127.0.0.1:32500/player/playback/skipNext')
            with urllib.request.urlopen(req, timeout=2) as response:
                log(f"[Control] Next command sent (status={response.status})")

                # Immediately poll timeline to update position/state after command
                time.sleep(0.1)  # Brief delay for Plexamp to process command
                timeline = self.get_timeline()
                if timeline:
                    self.store.update(**timeline)
                    log("[Control] Updated position after next track command")

                return response.status == 200
        except Exception as e:
            log(f"[Control] Next command failed: {e}")
            return False

    def previous_track(self):
        """Skip to previous track via Plexamp HTTP API"""
        try:
            req = urllib.request.Request('http://127.0.0.1:32500/player/playback/skipPrevious')
            with urllib.request.urlopen(req, timeout=2) as response:
                log(f"[Control] Previous command sent (status={response.status})")

                # Immediately poll timeline to update position/state after command
                time.sleep(0.1)  # Brief delay for Plexamp to process command
                timeline = self.get_timeline()
                if timeline:
                    self.store.update(**timeline)
                    log("[Control] Updated position after previous track command")

                return response.status == 200
        except Exception as e:
            log(f"[Control] Previous command failed: {e}")
            return False

    def get_timeline(self) -> Optional[Dict]:
        """Query Plexamp HTTP API for current timeline (position and state)"""
        try:
            req = urllib.request.Request('http://127.0.0.1:32500/player/timeline/poll?wait=0')
            with urllib.request.urlopen(req, timeout=2) as response:
                data = response.read().decode('utf-8')
                timeline = ET.fromstring(data)

                # Parse timeline XML
                # <MediaContainer>
                #   <Timeline ... time="12345" duration="234567" state="playing" />
                # </MediaContainer>
                for elem in timeline.findall('.//Timeline[@type="music"]'):
                    state = elem.get('state', 'stopped')  # playing, paused, stopped
                    time_ms = elem.get('time')  # Current position in milliseconds
                    duration_ms = elem.get('duration')  # Track duration in milliseconds

                    result = {}

                    # Map state to our format
                    state_map = {
                        'playing': 'Playing',
                        'paused': 'Paused',
                        'stopped': 'Stopped'
                    }
                    result['playback_status'] = state_map.get(state.lower(), 'Stopped')

                    # Position
                    if time_ms:
                        result['position'] = int(time_ms)
                        log(f"[Timeline] Position: {time_ms}ms, State: {result['playback_status']}")

                    return result

                return None

        except Exception as e:
            # Don't log every failed poll (keeps logs clean)
            return None

    def seek(self, position_ms: int):
        """Seek to specific position via Plexamp HTTP API"""
        try:
            # Plexamp seek API expects offset in milliseconds
            req = urllib.request.Request(f'http://127.0.0.1:32500/player/playback/seekTo?offset={position_ms}')
            with urllib.request.urlopen(req, timeout=2) as response:
                log(f"[Control] Seek to {position_ms}ms (status={response.status})")
                # Update position in store
                self.store.update(position=position_ms)
                return response.status == 200
        except Exception as e:
            log(f"[Control] Seek command failed: {e}")
            return False

    def is_available(self):
        """Check if Plexamp is available"""
        # Check if PlayQueue.json file exists
        import os
        return os.path.exists(self.state_file)


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

            # Control capabilities (via Plexamp HTTP API)
            "canGoNext": can_control,
            "canGoPrevious": can_control,
            "canPlay": can_control,
            "canPause": can_control,
            "canSeek": can_control,  # Plexamp supports seeking via HTTP API
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

                    # Control capabilities (via Plexamp HTTP API)
                    "canGoNext": can_control,
                    "canGoPrevious": can_control,
                    "canPlay": can_control,
                    "canPause": can_control,
                    "canSeek": can_control,  # Plexamp supports seeking via HTTP API
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
                log(f"[Snapcast] GetProperties → status={playback_status}, canControl={can_control}, canPlay={can_control}, canPause={can_control}, metadata keys: {list(meta_obj.keys())}")

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
                elif command == "seek":
                    # Seek to specific position (in milliseconds)
                    position = params.get("position", 0)
                    log(f"[Control] Seeking to position: {position}ms")
                    success = self.plexamp_monitor.seek(position)
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
