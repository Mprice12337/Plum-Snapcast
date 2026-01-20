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
PLEXAMP_TOKEN_FILE = "/tmp/plexamp-state/.local/share/Plexamp/Settings/%40Plexamp%3Auser%3Atoken"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
COVER_ART_DIR = "/usr/share/snapserver/snapweb/coverart"
POLL_INTERVAL = 2.0  # Poll PlayQueue.json every 2 seconds

# Playback API configuration (for real-time position tracking independent of Snapcast)
PLAYBACK_API_PORT = int(os.getenv("FEDERATION_API_PORT", "5001"))
PLAYBACK_API_URL = f"http://localhost:{PLAYBACK_API_PORT}/api/playback"

# Plexamp HTTP API for timeline
PLEXAMP_API_PORT = 32500
PLEXAMP_TIMELINE_URL = f"http://localhost:{PLEXAMP_API_PORT}/player/timeline/poll?wait=0"

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


def post_playback_position(stream_id: str, position_ms: int, duration_ms: int,
                           playback_status: str = "playing", **extra):
    """
    POST position update to playback API (non-blocking).

    Sends position data to our API for remote endpoint timeline sync.
    """
    def _post():
        try:
            # URL-encode the stream_id for the path
            encoded_stream_id = urllib.request.quote(stream_id, safe='')
            url = f"{PLAYBACK_API_URL}/{encoded_stream_id}"

            data = {
                "position": position_ms,
                "duration": duration_ms,
                "playback_status": playback_status,
                **extra
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    log(f"[PlaybackAPI] Posted position: {position_ms}ms / {duration_ms}ms ({playback_status})")
                else:
                    log(f"[PlaybackAPI] Unexpected status: {response.status}")

        except urllib.error.URLError as e:
            # API might not be ready yet - this is expected during startup
            log(f"[PlaybackAPI] Failed to post (API may not be ready): {e.reason}")
        except Exception as e:
            log(f"[PlaybackAPI] Error posting position: {e}")

    # Run in background thread to avoid blocking metadata processing
    thread = threading.Thread(target=_post, daemon=True)
    thread.start()


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
        self.token_file = PLEXAMP_TOKEN_FILE
        self.running = False
        self.poll_thread = None
        self.last_track_id = None
        self.last_mtime = 0
        self.plex_server_uris = []  # List of URIs to try (local IPs first, then plex.direct)
        self.working_uri = None  # Last URI that worked for artwork
        self.plex_token = self._load_plex_token()  # Load authentication token
        log(f"[Plexamp] Monitor initialized, watching: {self.state_file}")
        if self.plex_token:
            log(f"[Plexamp] Plex token loaded (length: {len(self.plex_token)})")

    def _load_plex_token(self) -> Optional[str]:
        """Load Plex authentication token from Plexamp settings.

        First tries to get the server's accessToken from resources file,
        falls back to user token if not found.
        """
        try:
            # Try to get server accessToken from resources first
            if os.path.exists(self.resources_file):
                with open(self.resources_file, 'r') as f:
                    resources = json.load(f)
                if isinstance(resources, dict):
                    for server_id, resource in resources.items():
                        if resource.get('provides') == 'server':
                            token = resource.get('accessToken')
                            if token:
                                log(f"[Plex] Using server accessToken from resources")
                                return token

            # Fallback to user token file
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    token = f.read().strip()
                    if token and len(token) > 0:
                        log(f"[Plex] Using user token from token file")
                        return token

            log("[Plex] No authentication token found")
            return None
        except Exception as e:
            log(f"[Error] Failed to load Plex token: {e}")
            return None

    def _get_plex_server_uris(self) -> list:
        """Extract all Plex server URIs from resources file, prioritizing local IPs"""
        if self.plex_server_uris:
            return self.plex_server_uris

        try:
            import os
            if not os.path.exists(self.resources_file):
                log(f"[Error] Resources file not found: {self.resources_file}")
                return []

            with open(self.resources_file, 'r') as f:
                resources = json.load(f)

            all_uris = []
            local_uris = []
            remote_uris = []

            def collect_uris(resource):
                if resource.get('provides') == 'server' and 'connections' in resource:
                    for conn in resource['connections']:
                        uri = conn.get('uri')
                        if uri:
                            # Prioritize local IPs (192.168.x.x, 10.x.x.x, etc.)
                            if conn.get('local') or '192.168.' in uri or '10.' in uri or '172.' in uri:
                                local_uris.append(uri)
                            else:
                                remote_uris.append(uri)

            # Resources can be dict or list
            if isinstance(resources, dict):
                for server_id, resource in resources.items():
                    collect_uris(resource)
            elif isinstance(resources, list):
                for resource in resources:
                    collect_uris(resource)

            # Local URIs first, then remote (plex.direct, etc.)
            all_uris = local_uris + remote_uris

            if all_uris:
                self.plex_server_uris = all_uris
                log(f"[Plex] Found {len(all_uris)} server URIs (local: {len(local_uris)}, remote: {len(remote_uris)})")
                for i, uri in enumerate(all_uris):
                    log(f"[Plex]   [{i+1}] {uri}")
                return all_uris

            log("[Error] Could not find Plex server URI in resources")
            return []

        except Exception as e:
            log(f"[Error] Failed to read Plex server URI: {e}")
            return []

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
        """Download cover art from Plex server and save to web root.
        Tries multiple server URIs, prioritizing local IPs for reliability.
        """
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

            # Handle absolute URLs directly
            if not cover_url.startswith('/'):
                full_urls = [cover_url]
            else:
                # Get all Plex server URIs to try
                server_uris = self._get_plex_server_uris()
                if not server_uris:
                    log("[Error] Cannot download artwork: no Plex server URIs")
                    return None

                # If we have a known working URI, try it first
                if self.working_uri and self.working_uri in server_uris:
                    uris_to_try = [self.working_uri] + [u for u in server_uris if u != self.working_uri]
                else:
                    uris_to_try = server_uris

                full_urls = [f"{uri}{cover_url}" for uri in uris_to_try]

            # Try each URL until one works
            import ssl
            ssl_context = ssl._create_unverified_context()

            for full_url in full_urls:
                try:
                    # Add Plex token if available
                    if self.plex_token:
                        separator = '&' if '?' in full_url else '?'
                        authed_url = f"{full_url}{separator}X-Plex-Token={self.plex_token}"
                    else:
                        authed_url = full_url

                    # Shorter timeout (5s) so we fail fast and try next URI
                    log(f"[Artwork] Trying: {full_url[:80]}...")
                    req = urllib.request.Request(authed_url, headers={'User-Agent': 'Snapcast/1.0'})
                    with urllib.request.urlopen(req, timeout=5, context=ssl_context) as response:
                        cover_data = response.read()

                    # Success! Save to web root
                    with open(cover_path, "wb") as f:
                        f.write(cover_data)

                    # Make sure the file is readable by the web server
                    os.chmod(cover_path, 0o644)

                    # Remember this working URI for next time
                    if cover_url.startswith('/'):
                        base_uri = full_url.replace(cover_url, '')
                        self.working_uri = base_uri
                        log(f"[Artwork] ✓ Downloaded {len(cover_data)} bytes from {base_uri[:50]}")
                    else:
                        log(f"[Artwork] ✓ Downloaded {len(cover_data)} bytes")

                    return f"/coverart/{filename}"

                except urllib.error.URLError as e:
                    log(f"[Artwork] Failed ({full_url[:50]}...): {e.reason}")
                    continue
                except Exception as e:
                    log(f"[Artwork] Failed ({full_url[:50]}...): {e}")
                    continue

            # All local downloads failed - return full external URL for browser to fetch directly
            # Use the NESTED photo transcode endpoint format that Plexamp uses:
            # /photo/:/transcode?url=/photo/:/transcode?url=/library/metadata/xxx/thumb/xxx
            log(f"[Artwork] Local download failed, returning external URL for browser")

            # Get the preferred server URI (first available)
            server_uris = self._get_plex_server_uris()
            if server_uris and self.plex_token:
                server_uri = server_uris[0]

                # Build nested transcode URL like Plexamp does:
                # Inner: /photo/:/transcode?width=300&height=300&url=/library/metadata/.../thumb/...&format=jpeg&X-Plex-Token=xxx
                # Outer: /photo/:/transcode?width=300&height=300&url={inner_encoded}&format=jpeg&X-Plex-Token=xxx
                inner_url = f"/photo/:/transcode?width=300&height=300&url={urllib.request.quote(cover_url, safe='')}&format=jpeg&X-Plex-Token={self.plex_token}"
                outer_url = f"{server_uri}/photo/:/transcode?width=300&height=300&url={urllib.request.quote(inner_url, safe='')}&format=jpeg&X-Plex-Token={self.plex_token}"

                log(f"[Artwork] External URL: {server_uri}/photo/:/transcode?...")
                return outer_url

            return None

        except Exception as e:
            log(f"[Error] Artwork download failed: {e}")
            return None

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

                # Duration (Plex provides milliseconds, convert to seconds for Snapcast)
                duration_ms = track.get('duration')
                if duration_ms:
                    duration_s = int(duration_ms) // 1000  # Convert ms to seconds
                    result['duration'] = duration_s
                    log(f"[Metadata] Duration: {duration_ms}ms ({duration_s}s)")

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
        """Background thread that polls PlayQueue.json file for metadata and timeline API for position.

        PlayQueue.json: Provides track metadata (title, artist, album, artwork, duration)
        Timeline API: Provides current position and playback state (with wait=0 to avoid deadlock)

        State detection:
        - Playing/Paused: From timeline API state field
        - Stopped: PlayQueue.json doesn't exist or timeline state is stopped
        - Position: From timeline API time field (milliseconds)
        """
        log("[Plexamp] Starting PlayQueue + Timeline monitoring")

        last_has_queue = False
        last_playback_status = "Stopped"
        last_volume = 100
        last_position_s = 0

        while self.running:
            try:
                metadata_updated = False
                position_updated = False

                # Read PlayQueue.json for metadata
                playqueue_data = self._read_playqueue()

                if playqueue_data:
                    # Parse and extract metadata
                    metadata = self._parse_playqueue(playqueue_data)

                    if metadata:
                        # Update store with new data
                        self.store.update(**metadata)
                        metadata_updated = True

                        if not last_has_queue:
                            log("[PlayQueue] Queue detected")
                        last_has_queue = True
                else:
                    # No queue data means stopped
                    if last_has_queue:
                        log("[PlayQueue] Playback stopped (no queue)")
                        self.store.update(playback_status='Stopped', position=0)
                        metadata_updated = True
                        last_playback_status = "Stopped"
                    last_has_queue = False

                # Fetch timeline from Plexamp HTTP API for position/state/volume
                # Using commandID=1&wait=0 for Plexamp compatibility
                if last_has_queue:
                    timeline = self.get_timeline()
                    if timeline:
                        playback_status = timeline.get('playback_status', 'Stopped')
                        position_ms = timeline.get('position', 0)
                        duration_ms = timeline.get('duration', 0)
                        volume = timeline.get('volume', 100)

                        # Convert position from ms to seconds for Snapcast
                        # (Snapcast expects position in seconds to match duration)
                        position_s = position_ms // 1000

                        # Update store with position (seconds)/state/volume
                        self.store.update(
                            playback_status=playback_status,
                            position=position_s,  # Store in seconds
                            volume=volume
                        )

                        # Only send Snapcast notification when values actually change
                        # This prevents frontend flickering from constant updates
                        if playback_status != last_playback_status:
                            log(f"[Timeline] State changed: {last_playback_status} → {playback_status}")
                            last_playback_status = playback_status
                            metadata_updated = True

                        if volume != last_volume:
                            log(f"[Timeline] Volume changed: {last_volume}% → {volume}%")
                            last_volume = volume
                            metadata_updated = True

                        # Update position tracking (for playback API, not Snapcast notification)
                        last_position_s = position_s

                        # Post to playback API for remote endpoint sync
                        # Use duration from store if not in timeline (metadata has it)
                        store_data = self.store.get_all()
                        if duration_ms == 0 and store_data.get('duration'):
                            # Duration is in seconds in store (converted from ms earlier)
                            duration_ms = store_data['duration'] * 1000

                        post_playback_position(
                            stream_id="Plexamp",
                            position_ms=position_ms,
                            duration_ms=duration_ms,
                            playback_status=playback_status.lower()
                        )
                        position_updated = True
                    else:
                        log("[Timeline] Failed to get timeline data")

                # Send notification on metadata/state changes
                if metadata_updated:
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
                # Note: Position/state will be updated by PlayQueue.json monitor
                # Avoid HTTP API polling here to prevent deadlock
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
                # Note: Position/state will be updated by PlayQueue.json monitor
                # Avoid HTTP API polling here to prevent deadlock
                return response.status == 200
        except Exception as e:
            log(f"[Control] Previous command failed: {e}")
            return False

    def get_timeline(self) -> Optional[Dict]:
        """Query Plexamp HTTP API for current timeline (position, duration, state, volume)"""
        try:
            # commandID=1 is required for Plexamp to return timeline data
            req = urllib.request.Request('http://127.0.0.1:32500/player/timeline/poll?commandID=1&wait=0')
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
                    volume = elem.get('volume')  # Volume 0-100

                    result = {}

                    # Map state to our format
                    state_map = {
                        'playing': 'Playing',
                        'paused': 'Paused',
                        'stopped': 'Stopped'
                    }
                    result['playback_status'] = state_map.get(state.lower(), 'Stopped')

                    # Position (milliseconds)
                    if time_ms:
                        result['position'] = int(time_ms)

                    # Duration (milliseconds)
                    if duration_ms:
                        result['duration'] = int(duration_ms)

                    # Volume (0-100)
                    if volume:
                        result['volume'] = int(volume)

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
        volume = state_data.get("volume", 100)  # Volume from timeline API
        can_control = self.plexamp_monitor.is_available()

        # Notification params: include stream ID and all properties
        params = {
            "id": self.stream_id,  # Include stream ID so frontend knows which stream to update

            # Playback state
            "playbackStatus": playback_status,
            "loopStatus": "none",
            "shuffle": False,
            "volume": volume,  # Source volume from Plexamp
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
            log(f"[Snapcast] Metadata → {title} - {artist_str} [{playback_status}] vol={volume}% (stream={self.stream_id})")
            if "artUrl" in meta_obj:
                log(f"[Snapcast]   Artwork: {meta_obj['artUrl']}")
        else:
            log(f"[Snapcast] State → [{playback_status}] vol={volume}% (stream={self.stream_id})")

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
                volume = state_data.get("volume", 100)  # Volume from timeline API
                can_control = self.plexamp_monitor.is_available()

                # Build complete properties response per Snapcast Stream Plugin API
                properties = {
                    # Playback state
                    "playbackStatus": playback_status,
                    "loopStatus": "none",
                    "shuffle": False,
                    "volume": volume,  # Source volume from Plexamp
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
                log(f"[Snapcast] GetProperties → status={playback_status}, vol={volume}%, canControl={can_control}, metadata keys: {list(meta_obj.keys())}")

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
