#!/usr/bin/env python3
"""
Snapcast Control Script for AirPlay Metadata
Reads metadata from shairport-sync pipe and provides it to Snapcast via JSON-RPC

Based on proven pattern from metadata-debug-server.py:
- Thread-safe metadata storage with atomic updates
- mdst/mden bundle pattern with pending state
- Independent artwork handling
- Only send complete, consistent updates to Snapcast
- D-Bus integration for playback state and remote control
"""

import argparse
import base64
import json
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

# Configuration
METADATA_PIPE = "/tmp/shairport-sync-metadata"
COVER_ART_CACHE_DIR = "/tmp/shairport-sync/.cache/coverart"
LOG_FILE = "/tmp/airplay-control-script.log"

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
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    log("[Warning] D-Bus not available - playback controls disabled")


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
            "track_id": None,
            "artwork_url": None,
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

        Snapcast expects simple field names (NOT MPRIS format):
        - title (string)
        - artist (array of strings)
        - album (string)
        - artUrl (string)
        """
        with self.lock:
            # Only return if we have at least a title
            if self.data.get("title"):
                meta = {}

                # Snapcast metadata fields (simple names, not MPRIS)
                if self.data.get("title"):
                    meta["title"] = self.data["title"]

                if self.data.get("artist"):
                    # Snapcast expects artist as an array
                    meta["artist"] = [self.data["artist"]]

                if self.data.get("album"):
                    meta["album"] = self.data["album"]

                if self.data.get("artwork_url"):
                    meta["artUrl"] = self.data["artwork_url"]

                return meta
            return None


class MetadataParser:
    """
    Parse shairport-sync metadata using the proven pattern from debug server.

    Pattern:
    - Accumulate in pending_metadata during mdst...mden bundle
    - Apply atomically to store at mden
    - Handle artwork independently
    """

    def __init__(self, store: MetadataStore):
        self.store = store

        # Current state (what's been applied)
        self.current = {
            "title": None,
            "artist": None,
            "album": None,
            "track_id": None
        }

        # Pending state (accumulating during bundle)
        self.pending_metadata = {
            "title": None,
            "artist": None,
            "album": None
        }

        # Artwork handling
        self.pending_cover_data = []
        self.last_loaded_cache_file = None

        # Bundle state flags
        self.in_metadata_bundle = False
        self.in_artwork_bundle = False

    def parse_item(self, item_xml: str) -> bool:
        """
        Parse one XML item and update store.
        Returns True if store was updated (signals Snapcast notification needed).
        """
        try:
            root = ET.fromstring(item_xml)

            # Extract type and code
            type_elem = root.find("type")
            code_elem = root.find("code")
            if code_elem is None:
                return False

            item_type = bytes.fromhex(type_elem.text).decode('ascii', errors='ignore') if type_elem is not None else ""
            code = bytes.fromhex(code_elem.text).decode('ascii', errors='ignore')

            # Extract data
            data_elem = root.find("data")
            encoding = data_elem.get("encoding", "") if data_elem is not None else ""
            data_text = (data_elem.text or "").strip() if data_elem is not None else ""

            decoded = ""
            if encoding == "base64" and data_text and code != "PICT":
                try:
                    decoded = base64.b64decode(data_text).decode('utf-8', errors='ignore')
                except:
                    decoded = ""

            # ===== METADATA BUNDLE MARKERS (ssnc) =====
            if item_type == "ssnc":
                if code == "mdst":
                    # Metadata bundle START
                    log(f"[Bundle] Metadata START")
                    self.in_metadata_bundle = True
                    # Clear pending metadata for new bundle
                    self.pending_metadata = {
                        "title": None,
                        "artist": None,
                        "album": None
                    }
                    return False

                elif code == "mden":
                    # Metadata bundle END - ATOMIC APPLICATION
                    log(f"[Bundle] Metadata END")
                    self.in_metadata_bundle = False

                    updated = False

                    # Apply all pending metadata at once to both current and store
                    if self.pending_metadata["title"]:
                        self.current["title"] = self.pending_metadata["title"]
                        self.store.update(title=self.pending_metadata["title"])
                        log(f"[Bundle] Applied title: {self.pending_metadata['title']}")
                        updated = True

                    if self.pending_metadata["artist"]:
                        self.current["artist"] = self.pending_metadata["artist"]
                        self.store.update(artist=self.pending_metadata["artist"])
                        log(f"[Bundle] Applied artist: {self.pending_metadata['artist']}")
                        updated = True

                    if self.pending_metadata["album"]:
                        self.current["album"] = self.pending_metadata["album"]
                        self.store.update(album=self.pending_metadata["album"])
                        log(f"[Bundle] Applied album: {self.pending_metadata['album']}")
                        updated = True

                    # Signal update if we changed anything
                    return updated

                elif code == "pcst":
                    # Artwork bundle START
                    log(f"[Artwork] START")
                    self.in_artwork_bundle = True
                    self.pending_cover_data = []
                    return False

                elif code == "pcen":
                    # Artwork bundle END
                    log(f"[Artwork] END")
                    self.in_artwork_bundle = False

                    # Load from cache (shairport-sync writes to disk)
                    artwork_url = self._load_artwork_from_cache()
                    if artwork_url:
                        self.store.update(artwork_url=artwork_url)
                        log(f"[Artwork] Applied to store ({len(artwork_url)} chars)")
                        return True  # Signal update

                    return False

                elif code == "PICT":
                    # Artwork data (not used when caching is enabled)
                    if encoding == "base64" and data_text:
                        self.pending_cover_data.append(data_text)
                        log(f"[Artwork] Received PICT chunk ({len(data_text)} chars)")
                    return False

            # ===== METADATA FIELDS (core) =====
            if item_type == "core":
                if code == "mper" and decoded:  # Track ID (persistent ID)
                    track_id = decoded.strip()
                    if track_id:
                        # Detect track change
                        if self.current["track_id"] and self.current["track_id"] != track_id:
                            log(f"[Track] CHANGE: {self.current['track_id'][:8]}... → {track_id[:8]}...")
                            # Clear everything for new track
                            self.current = {
                                "title": None,
                                "artist": None,
                                "album": None,
                                "track_id": track_id
                            }
                            self.store.update(
                                title=None,
                                artist=None,
                                album=None,
                                track_id=track_id,
                                artwork_url=None
                            )
                            return True  # Signal update to clear Snapcast
                        else:
                            self.current["track_id"] = track_id
                            self.store.update(track_id=track_id)
                            log(f"[Track] ID: {track_id[:8]}...")

                elif code == "minm" and decoded.strip():  # Title
                    if self.in_metadata_bundle:
                        self.pending_metadata["title"] = decoded.strip()
                        log(f"[Field] Title (pending): {decoded.strip()}")
                    else:
                        # Immediate update (outside bundle)
                        self.current["title"] = decoded.strip()
                        self.store.update(title=decoded.strip())
                        log(f"[Field] Title (immediate): {decoded.strip()}")
                        return True

                elif code == "asar" and decoded.strip():  # Artist
                    if self.in_metadata_bundle:
                        self.pending_metadata["artist"] = decoded.strip()
                        log(f"[Field] Artist (pending): {decoded.strip()}")
                    else:
                        # Immediate update (outside bundle)
                        self.current["artist"] = decoded.strip()
                        self.store.update(artist=decoded.strip())
                        log(f"[Field] Artist (immediate): {decoded.strip()}")
                        return True

                elif code == "asal" and decoded.strip():  # Album
                    if self.in_metadata_bundle:
                        self.pending_metadata["album"] = decoded.strip()
                        log(f"[Field] Album (pending): {decoded.strip()}")
                    else:
                        # Immediate update (outside bundle)
                        self.current["album"] = decoded.strip()
                        self.store.update(album=decoded.strip())
                        log(f"[Field] Album (immediate): {decoded.strip()}")
                        return True

        except ET.ParseError:
            # Expected when buffer cuts mid-XML
            pass
        except Exception as e:
            log(f"[Error] Parse exception: {e}")

        return False

    def _load_artwork_from_cache(self) -> Optional[str]:
        """
        Load artwork from shairport-sync cache.
        Returns data URL or None.
        """
        try:
            cache_dir = Path(COVER_ART_CACHE_DIR)
            if not cache_dir.exists():
                return None

            # Find all cover files
            cover_files = list(cache_dir.glob("cover-*.jpg")) + list(cache_dir.glob("cover-*.png"))
            if not cover_files:
                return None

            # Get newest file
            newest_file = max(cover_files, key=lambda p: p.stat().st_mtime)

            # Skip if already loaded
            if self.last_loaded_cache_file == newest_file.name:
                return None  # No change

            # Read and encode
            with open(newest_file, 'rb') as f:
                image_data = f.read()

            import mimetypes
            mime_type = mimetypes.guess_type(str(newest_file))[0] or 'image/jpeg'
            data_url = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('ascii')}"

            self.last_loaded_cache_file = newest_file.name
            log(f"[Artwork] Loaded from cache: {newest_file.name} ({len(image_data)} bytes)")

            return data_url

        except Exception as e:
            log(f"[Error] Artwork load failed: {e}")
            return None


class DBusMonitor:
    """
    Monitor ShairportSync D-Bus interface for playback state changes.
    Provides remote control capabilities (play, pause, next, previous).
    """

    def __init__(self, store: MetadataStore, on_state_change_callback):
        self.store = store
        self.on_state_change = on_state_change_callback
        self.dbus_interface = None
        self.dbus_properties = None
        self.bus = None

        if not DBUS_AVAILABLE:
            log("[DBus] D-Bus Python bindings not available - control disabled")
            log("[DBus] Install py3-dbus and py3-gobject3 to enable controls")
            return

        # Start connection in background thread to avoid blocking
        connect_thread = threading.Thread(target=self._connect_with_retry, daemon=True)
        connect_thread.start()

    def _connect_with_retry(self):
        """Try to connect to ShairportSync D-Bus with retries"""
        max_retries = 10
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Initialize D-Bus main loop on first attempt
                if attempt == 0:
                    DBusGMainLoop(set_as_default=True)

                # Connect to system bus
                self.bus = dbus.SystemBus()

                # Get ShairportSync RemoteControl interface
                shairport = self.bus.get_object('org.gnome.ShairportSync', '/org/gnome/ShairportSync')
                self.dbus_interface = dbus.Interface(shairport, 'org.gnome.ShairportSync.RemoteControl')
                self.dbus_properties = dbus.Interface(shairport, 'org.freedesktop.DBus.Properties')

                # Subscribe to property changes
                self.dbus_properties.connect_to_signal('PropertiesChanged', self.on_properties_changed)

                log("[DBus] ✓ Connected to ShairportSync D-Bus interface")

                # Get initial playback state
                try:
                    playing = self.dbus_properties.Get('org.gnome.ShairportSync.RemoteControl', 'IsPlaying')
                    initial_state = "Playing" if playing else "Paused"
                    self.store.update(playback_status=initial_state)
                    log(f"[DBus] ✓ Initial playback state: {initial_state}")

                    # Notify parent that we're ready
                    if self.on_state_change:
                        self.on_state_change()
                except Exception as e:
                    log(f"[DBus] Could not get initial state: {e}")

                return  # Success!

            except dbus.exceptions.DBusException as e:
                if attempt < max_retries - 1:
                    log(f"[DBus] Connection attempt {attempt + 1}/{max_retries} failed: {e}")
                    log(f"[DBus] Retrying in {retry_delay}s (ShairportSync may not be ready yet)...")
                    time.sleep(retry_delay)
                else:
                    log(f"[DBus] ✗ Failed to connect after {max_retries} attempts: {e}")
                    log("[DBus] Control features disabled - check that ShairportSync is running")
                    self.dbus_interface = None
            except Exception as e:
                log(f"[DBus] ✗ Unexpected error during connection: {e}")
                self.dbus_interface = None
                break

    def on_properties_changed(self, interface_name, changed_properties, invalidated_properties):
        """Handle D-Bus property changes"""
        try:
            if 'IsPlaying' in changed_properties:
                is_playing = bool(changed_properties['IsPlaying'])
                new_status = "Playing" if is_playing else "Paused"
                log(f"[DBus] Playback state changed: {new_status}")
                self.store.update(playback_status=new_status)
                # Notify parent to send update to Snapcast
                if self.on_state_change:
                    self.on_state_change()
        except Exception as e:
            log(f"[DBus] Error handling property change: {e}")

    def play(self):
        """Send play command to ShairportSync"""
        if self.dbus_interface:
            try:
                self.dbus_interface.Play()
                log("[DBus] Sent Play command")
            except Exception as e:
                log(f"[DBus] Play failed: {e}")

    def pause(self):
        """Send pause command to ShairportSync"""
        if self.dbus_interface:
            try:
                self.dbus_interface.Pause()
                log("[DBus] Sent Pause command")
            except Exception as e:
                log(f"[DBus] Pause failed: {e}")

    def play_pause(self):
        """Toggle play/pause"""
        if self.dbus_interface:
            try:
                self.dbus_interface.PlayPause()
                log("[DBus] Sent PlayPause command")
            except Exception as e:
                log(f"[DBus] PlayPause failed: {e}")

    def next_track(self):
        """Skip to next track"""
        if self.dbus_interface:
            try:
                self.dbus_interface.Next()
                log("[DBus] Sent Next command")
            except Exception as e:
                log(f"[DBus] Next failed: {e}")

    def previous_track(self):
        """Skip to previous track"""
        if self.dbus_interface:
            try:
                self.dbus_interface.Previous()
                log("[DBus] Sent Previous command")
            except Exception as e:
                log(f"[DBus] Previous failed: {e}")

    def is_available(self):
        """Check if D-Bus control is available"""
        return self.dbus_interface is not None


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.store = MetadataStore()
        self.metadata_parser = MetadataParser(self.store)
        self.dbus_monitor = DBusMonitor(self.store, self.send_playback_state_update)
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

    def send_playback_state_update(self):
        """Send playback state update to Snapcast (called when D-Bus state changes)"""
        playback_status = self.store.get_all().get("playback_status", "Stopped")
        can_control = self.dbus_monitor.is_available()

        params = {
            "playbackStatus": playback_status,
            "canGoNext": can_control,
            "canGoPrevious": can_control,
            "canPlay": can_control,
            "canPause": can_control,
            "canControl": can_control,
        }
        self.send_notification("Plugin.Stream.Player.Properties", params)
        log(f"[Snapcast] Playback state → {playback_status}")

    def send_metadata_update(self):
        """Send Plugin.Stream.Player.Properties with current metadata from store"""
        meta_obj = self.store.get_metadata_for_snapcast()

        if meta_obj:
            # Get current playback state from store
            playback_status = self.store.get_all().get("playback_status", "Stopped")
            can_control = self.dbus_monitor.is_available()

            # Notification params: all properties FLAT (no "id" - stream is implicit)
            # Snapcast knows which stream this is for based on the control script attachment
            params = {
                # Playback state (same fields as GetProperties)
                "playbackStatus": playback_status,
                "loopStatus": "none",
                "shuffle": False,
                "volume": 100,
                "mute": False,
                "rate": 1.0,
                "position": 0,

                # Control capabilities (enable if D-Bus is available)
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

            # Log what we sent (check simple format keys)
            title = meta_obj.get('title', 'N/A')
            artist = meta_obj.get('artist', ['N/A'])
            artist_str = artist[0] if isinstance(artist, list) and artist else 'N/A'
            log(f"[Snapcast] Metadata → {title} - {artist_str} [{playback_status}]")
            if "artUrl" in meta_obj:
                log(f"[Snapcast]   Artwork: {len(meta_obj['artUrl'])} chars")

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")
            params = request.get("params", {})

            if method == "Plugin.Stream.Player.GetProperties":
                # Return COMPLETE properties object (not just metadata)
                # Snapcast requires all fields: playback state, control capabilities, AND metadata
                meta_obj = self.store.get_metadata_for_snapcast() or {}
                playback_status = self.store.get_all().get("playback_status", "Stopped")
                can_control = self.dbus_monitor.is_available()

                # Build complete properties response per Snapcast Stream Plugin API
                properties = {
                    # Playback state (from D-Bus if available)
                    "playbackStatus": playback_status,
                    "loopStatus": "none",
                    "shuffle": False,
                    "volume": 100,
                    "mute": False,
                    "rate": 1.0,
                    "position": 0,

                    # Control capabilities (enable if D-Bus available)
                    "canGoNext": can_control,
                    "canGoPrevious": can_control,
                    "canPlay": can_control,
                    "canPause": can_control,
                    "canSeek": False,
                    "canControl": can_control,

                    # Metadata (MPRIS format)
                    "metadata": meta_obj
                }

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": properties
                }
                print(json.dumps(response), file=sys.stdout, flush=True)
                log(f"[Snapcast] GetProperties → status={playback_status}, metadata keys: {list(meta_obj.keys())}")

            elif method == "Plugin.Stream.Control":
                # Handle playback control commands
                command = params.get("command", "")
                log(f"[Snapcast] Control command received: {command}")

                if not self.dbus_monitor.is_available():
                    # Return error if D-Bus not available
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Control not available (D-Bus not connected)"
                        }
                    }
                    print(json.dumps(error_response), file=sys.stdout, flush=True)
                    return

                # Execute command via D-Bus
                if command == "play":
                    self.dbus_monitor.play()
                elif command == "pause":
                    self.dbus_monitor.pause()
                elif command == "playPause":
                    self.dbus_monitor.play_pause()
                elif command == "next":
                    self.dbus_monitor.next_track()
                elif command == "previous" or command == "prev":
                    self.dbus_monitor.previous_track()
                else:
                    log(f"[Snapcast] Unknown control command: {command}")

                # Send success response
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                }
                print(json.dumps(response), file=sys.stdout, flush=True)

        except Exception as e:
            log(f"[Error] Command handler: {e}")
            if request_id:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }
                print(json.dumps(error_response), file=sys.stdout, flush=True)

    def monitor_metadata_pipe(self):
        """Monitor shairport-sync metadata pipe"""
        log("[Init] Starting metadata pipe monitor")

        # Wait for pipe
        while not Path(METADATA_PIPE).exists():
            log(f"[Init] Waiting for pipe: {METADATA_PIPE}")
            time.sleep(1)

        log(f"[Init] Pipe found: {METADATA_PIPE}")

        # LINE-BY-LINE reading
        tmp = ""
        try:
            while True:
                with open(METADATA_PIPE, 'r') as pipe:
                    for line in pipe:
                        strip_line = line.strip()

                        if strip_line.endswith("</item>"):
                            # Complete item
                            item_xml = tmp + strip_line
                            updated = self.metadata_parser.parse_item(item_xml)

                            # Send update to Snapcast if store was modified
                            if updated:
                                self.send_metadata_update()

                            tmp = ""

                        elif strip_line.startswith("<item>"):
                            # New item starting
                            if tmp:
                                # Previous item incomplete - try to close it
                                item_xml = tmp + "</item>"
                                updated = self.metadata_parser.parse_item(item_xml)
                                if updated:
                                    self.send_metadata_update()

                            tmp = strip_line

                        else:
                            # Middle of item
                            tmp += strip_line

        except Exception as e:
            log(f"[Error] Pipe monitor crashed: {e}")
            import traceback
            log(f"[Error] {traceback.format_exc()}")

    def run(self):
        """Main event loop"""
        log("[Init] AirPlay Control Script starting...")

        # Start metadata monitor in background
        monitor_thread = threading.Thread(target=self.monitor_metadata_pipe, daemon=True)
        monitor_thread.start()

        # Start D-Bus main loop in background (if available)
        if DBUS_AVAILABLE and self.dbus_monitor.is_available():
            dbus_loop = GLib.MainLoop()
            dbus_thread = threading.Thread(target=dbus_loop.run, daemon=True)
            dbus_thread.start()
            log("[Init] D-Bus event loop started")

        # Send ready notification
        self.send_notification("Plugin.Stream.Ready", {})
        log("[Init] Sent Plugin.Stream.Ready")

        # Process stdin commands
        log("[Init] Listening for commands on stdin...")
        try:
            for line in sys.stdin:
                line = line.strip()
                if line:
                    self.handle_command(line)
        except KeyboardInterrupt:
            log("[Init] Shutting down...")
        except Exception as e:
            log(f"[Error] Fatal error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='AirPlay metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default='Airplay', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    log(f"[Init] Starting with args: stream={args.stream}")

    script = SnapcastControlScript(stream_id=args.stream)
    script.run()
