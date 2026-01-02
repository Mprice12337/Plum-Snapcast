#!/usr/bin/env python3
"""
Snapcast Control Script for Spotify Connect (Librespot)
Monitors librespot D-Bus MPRIS interface for metadata and provides playback control

Based on proven pattern from bluetooth-control-script.py:
- Thread-safe metadata storage with atomic updates
- Playback state tracking (Playing/Paused/Stopped)
- Control command handling via D-Bus MPRIS
- Complete properties response for Snapcast
- Album artwork download and caching
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

# Configuration
LOG_FILE = "/tmp/spotify-control-script.log"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
COVER_ART_DIR = "/usr/share/snapserver/snapweb/coverart"

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
    log("[Warning] D-Bus not available - Spotify features disabled")


def get_spotifyd_pid(instance_id: str) -> Optional[str]:
    """
    Get PID of spotifyd process for specific instance.
    Used for MPRIS service name detection (org.mpris.MediaPlayer2.spotifyd.instance[PID])
    """
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"spotifyd.*spotifyd-{instance_id}.conf"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            # Return first PID if multiple found
            return result.stdout.strip().split('\n')[0]
    except:
        pass
    return None


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


class SpotifyMetadataMonitor:
    """Monitor librespot D-Bus MPRIS interface for Spotify metadata and playback state"""

    def __init__(self, store: MetadataStore, on_update_callback, instance_id: Optional[str] = None):
        self.store = store
        self.on_update = on_update_callback
        self.instance_id = instance_id  # Instance ID for multi-instance mode
        self.player_interface = None
        self.player_properties = None
        self.bus = None

        if not DBUS_AVAILABLE:
            log("[Spotify] D-Bus not available - monitoring disabled")
            return

        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
        log(f"[Spotify] D-Bus monitor initialized (instance: {instance_id or 'default'})")

    def _download_cover_art(self, cover_url: str) -> Optional[str]:
        """Download cover art from Spotify and save to web root"""
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

    def _extract_metadata_from_dict(self, metadata_dict: Dict) -> Dict:
        """Extract metadata from MPRIS metadata properties"""
        result = {}

        try:
            # MPRIS metadata fields
            if 'xesam:title' in metadata_dict:
                result['title'] = str(metadata_dict['xesam:title'])
                log(f"[Metadata] Title: {result['title']}")

            if 'xesam:artist' in metadata_dict:
                # Artist can be an array
                artists = metadata_dict['xesam:artist']
                if isinstance(artists, (list, tuple)) and artists:
                    result['artist'] = ', '.join(str(a) for a in artists)
                else:
                    result['artist'] = str(artists)
                log(f"[Metadata] Artist: {result['artist']}")

            if 'xesam:album' in metadata_dict:
                result['album'] = str(metadata_dict['xesam:album'])
                log(f"[Metadata] Album: {result['album']}")

            if 'mpris:artUrl' in metadata_dict:
                art_url = str(metadata_dict['mpris:artUrl'])
                log(f"[Metadata] Album Art URL: {art_url[:100]}")

                # Download and cache the artwork
                local_art_url = self._download_cover_art(art_url)
                if local_art_url:
                    result['artUrl'] = local_art_url

            if 'mpris:length' in metadata_dict:
                # MPRIS length is in microseconds
                length_us = int(metadata_dict['mpris:length'])
                result['duration'] = length_us // 1_000_000  # Convert to seconds
                log(f"[Metadata] Duration: {result['duration']}s")

        except Exception as e:
            log(f"[Error] Metadata extraction failed: {e}")

        return result

    def _extract_playback_status(self, status_str: str) -> str:
        """Convert MPRIS playback status to our format"""
        # MPRIS statuses: "Playing", "Paused", "Stopped"
        status_map = {
            "playing": "Playing",
            "paused": "Paused",
            "stopped": "Stopped",
        }
        return status_map.get(status_str.lower(), "Stopped")

    def _properties_changed_handler(self, interface, changed, invalidated, sender):
        """Handle D-Bus PropertiesChanged signals"""
        try:
            # We're interested in MediaPlayer2.Player interface
            if interface != 'org.mpris.MediaPlayer2.Player':
                return

            # If we don't have a player interface yet, try to find it now
            # (This handles the case where spotifyd registers after script startup)
            if not self.player_interface:
                log("[DBus] Received properties but no player interface - scanning now")
                self._scan_for_players()

            log(f"[DBus] Properties changed: {list(changed.keys())}")

            updated = False

            # Check if Metadata changed
            if 'Metadata' in changed:
                metadata_dict = changed['Metadata']
                log(f"[DBus] Metadata changed: {list(metadata_dict.keys())}")

                metadata = self._extract_metadata_from_dict(metadata_dict)

                if metadata:
                    # Update store with new metadata
                    self.store.update(**metadata)
                    updated = True

            # Check if playback status changed
            if 'PlaybackStatus' in changed:
                status = self._extract_playback_status(str(changed['PlaybackStatus']))
                log(f"[DBus] Status changed: {status}")
                self.store.update(playback_status=status)
                updated = True

            # Check if position changed
            if 'Position' in changed:
                position_us = int(changed['Position'])
                position_s = position_us // 1_000_000
                log(f"[DBus] Position changed: {position_s}s")
                self.store.update(position=position_s)
                # Trigger update for position changes to keep frontend in sync
                if self.on_update:
                    self.on_update()

            # Notify parent if anything changed
            if updated and self.on_update:
                self.on_update()

        except Exception as e:
            log(f"[Error] Properties changed handler failed: {e}")

    def _scan_for_players(self):
        """Scan for existing spotifyd player on D-Bus with instance-aware detection"""
        if not self.bus:
            return

        try:
            # Multi-instance support: Try PID-based naming for instances 2+
            mpris_names_to_try = []

            if self.instance_id:
                # Get spotifyd PID for this instance
                instance_pid = get_spotifyd_pid(self.instance_id)

                if instance_pid:
                    # Try PID-based name first (instance 2+)
                    pid_based_name = f"org.mpris.MediaPlayer2.spotifyd.instance{instance_pid}"
                    mpris_names_to_try.append(pid_based_name)
                    log(f"[DBus] Trying PID-based MPRIS name: {pid_based_name}")

                # Fallback to base name (instance 1)
                base_name = "org.mpris.MediaPlayer2.spotifyd"
                mpris_names_to_try.append(base_name)
                log(f"[DBus] Fallback to base MPRIS name: {base_name}")
            else:
                # Single-instance mode: Try common names
                mpris_names_to_try = [
                    "org.mpris.MediaPlayer2.spotifyd",
                    "org.mpris.MediaPlayer2.librespot"
                ]

            # Try each potential MPRIS name
            for mpris_name in mpris_names_to_try:
                try:
                    player_obj = self.bus.get_object(mpris_name, '/org/mpris/MediaPlayer2')
                    self.player_interface = dbus.Interface(player_obj, 'org.mpris.MediaPlayer2.Player')
                    self.player_properties = dbus.Interface(player_obj, 'org.freedesktop.DBus.Properties')
                    log(f"[DBus] ✓ Connected to player: {mpris_name}")

                    # Get initial metadata
                    try:
                        metadata = self.player_properties.Get('org.mpris.MediaPlayer2.Player', 'Metadata')
                        if metadata:
                            extracted = self._extract_metadata_from_dict(metadata)
                            if extracted:
                                self.store.update(**extracted)

                        status = self.player_properties.Get('org.mpris.MediaPlayer2.Player', 'PlaybackStatus')
                        if status:
                            self.store.update(playback_status=self._extract_playback_status(str(status)))
                    except:
                        pass

                    # Notify that control is available
                    if self.on_update:
                        self.on_update()

                    return  # Successfully connected
                except dbus.DBusException as e:
                    log(f"[DBus] Couldn't connect to {mpris_name}: {e}")
                    continue

            log("[DBus] No Spotify player found yet (will monitor for connections)")

        except Exception as e:
            log(f"[Error] Player scan failed: {e}")

    def _poll_position(self):
        """Background thread that polls position updates from D-Bus

        IMPORTANT: spotifyd has a bug where PlaybackStatus property doesn't update
        when pausing/resuming from remote Spotify clients (phone/desktop app).
        See: https://github.com/Spotifyd/spotifyd/issues/668

        Workaround: Infer playback state from position changes:
        - If position stops advancing for 2+ seconds → Paused
        - If position starts advancing again → Playing
        """
        log("[DBus] Position polling thread started (with playback state inference)")
        last_position_value = None
        last_position_change_time = time.time()
        position_stall_count = 0

        while True:
            try:
                current_status_in_store = self.store.get_all().get("playback_status", "Stopped")

                if self.player_properties:
                    try:
                        # Always poll position (even when paused, to detect resume)
                        position_us = self.player_properties.Get('org.mpris.MediaPlayer2.Player', 'Position')
                        position_s = int(position_us) // 1_000_000

                        # Detect playback state from position changes (spotifyd bug workaround)
                        position_is_advancing = False
                        if last_position_value is not None:
                            position_delta = position_s - last_position_value

                            # Position advanced by ~1 second (accounting for poll interval)
                            if 0 < position_delta <= 2:
                                position_is_advancing = True
                                position_stall_count = 0
                                last_position_change_time = time.time()
                            # Position jumped (seek/track change)
                            elif abs(position_delta) > 2:
                                position_is_advancing = True
                                position_stall_count = 0
                                last_position_change_time = time.time()
                            # Position stalled (not advancing)
                            else:
                                position_stall_count += 1

                        # Infer playback state from position behavior
                        inferred_status = current_status_in_store

                        if position_is_advancing and current_status_in_store != "Playing":
                            # Position is advancing but we think it's paused → must be playing
                            inferred_status = "Playing"
                            log(f"[State] Position advancing → Playing (spotifyd bug workaround)")
                        elif position_stall_count >= 2 and current_status_in_store == "Playing":
                            # Position stalled for 2+ seconds while playing → must be paused
                            inferred_status = "Paused"
                            log(f"[State] Position stalled {position_stall_count}s → Paused (spotifyd bug workaround)")

                        # Update playback state if it changed
                        if inferred_status != current_status_in_store:
                            self.store.update(playback_status=inferred_status)
                            if self.on_update:
                                self.on_update()
                            current_status_in_store = inferred_status

                        # Update position in store
                        self.store.update(position=position_s)

                        # Send position update to frontend if it changed significantly
                        if last_position_value is None:
                            # Initial connection
                            log(f"[DBus] Position: {position_s}s (initial)")
                            if self.on_update:
                                self.on_update()
                        elif abs(position_s - last_position_value) > 2:
                            # Position changed significantly (seek or track change)
                            if position_s < 5:
                                reason = "track_change"
                            else:
                                reason = "seek"
                            log(f"[DBus] Position: {last_position_value}s → {position_s}s ({reason})")
                            if self.on_update:
                                self.on_update()

                        last_position_value = position_s

                    except Exception as e:
                        log(f"[DBus] Position polling error: {e}")

                # Poll every second
                time.sleep(1)

            except Exception as e:
                log(f"[DBus] Position polling error: {e}")
                time.sleep(1)

        log("[DBus] Position polling thread stopped")

    def start(self):
        """Start monitoring D-Bus for Spotify metadata"""
        if not DBUS_AVAILABLE:
            return

        log("[Spotify] Starting metadata monitoring...")

        try:
            # Subscribe to PropertiesChanged signals from MPRIS
            self.bus.add_signal_receiver(
                self._properties_changed_handler,
                dbus_interface='org.freedesktop.DBus.Properties',
                signal_name='PropertiesChanged',
                sender_keyword='sender'
            )

            log("[Spotify] Subscribed to MPRIS D-Bus signals")

            # Try to find existing player
            self._scan_for_players()

            # Start background position polling
            poll_thread = threading.Thread(target=self._poll_position, daemon=True)
            poll_thread.start()
            log("[Spotify] Started position polling thread")

        except Exception as e:
            log(f"[Error] Failed to start monitoring: {e}")

    def play(self):
        """Send play command via MPRIS"""
        if self.player_interface:
            try:
                self.player_interface.Play()
                log("[Control] Sent Play command")
                self.store.update(playback_status="Playing")
            except Exception as e:
                log(f"[Error] Play failed: {e}")

    def pause(self):
        """Send pause command via MPRIS"""
        if self.player_interface:
            try:
                self.player_interface.Pause()
                log("[Control] Sent Pause command")
                self.store.update(playback_status="Paused")
            except Exception as e:
                log(f"[Error] Pause failed: {e}")

    def next_track(self):
        """Skip to next track"""
        if self.player_interface:
            try:
                self.player_interface.Next()
                log("[Control] Sent Next command")

                # Immediately poll position to update after track change
                time.sleep(0.1)  # Brief delay for Spotify to process command
                try:
                    position_us = self.player_properties.Get('org.mpris.MediaPlayer2.Player', 'Position')
                    position_ms = int(position_us) // 1000
                    self.store.update(position=position_ms)
                    log(f"[Control] Updated position after next track: {position_ms}ms")
                except Exception:
                    pass

            except Exception as e:
                log(f"[Error] Next failed: {e}")

    def previous_track(self):
        """Skip to previous track"""
        if self.player_interface:
            try:
                self.player_interface.Previous()
                log("[Control] Sent Previous command")

                # Immediately poll position to update after track change
                time.sleep(0.1)  # Brief delay for Spotify to process command
                try:
                    position_us = self.player_properties.Get('org.mpris.MediaPlayer2.Player', 'Position')
                    position_ms = int(position_us) // 1000
                    self.store.update(position=position_ms)
                    log(f"[Control] Updated position after previous track: {position_ms}ms")
                except Exception:
                    pass

            except Exception as e:
                log(f"[Error] Previous failed: {e}")

    def seek(self, position_ms: int):
        """Seek to a specific position in milliseconds"""
        if self.player_interface:
            try:
                # MPRIS SetPosition takes track ID and position in microseconds
                # We'll use Seek with relative offset instead for simplicity
                current_position = self.store.get_all().get("position", 0)
                offset_ms = position_ms - current_position
                offset_us = offset_ms * 1000

                self.player_interface.Seek(dbus.Int64(offset_us))
                log(f"[Control] Seek to {position_ms}ms (offset: {offset_ms}ms)")

                # Update store with new position
                self.store.update(position=position_ms)
            except Exception as e:
                log(f"[Error] Seek failed: {e}")

    def is_available(self):
        """Check if control is available"""
        return self.player_interface is not None

    def stop(self):
        """Stop monitoring"""
        pass  # D-Bus loop handled by main script


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str, instance_id: Optional[str] = None):
        self.stream_id = stream_id
        self.instance_id = instance_id
        self.store = MetadataStore()
        self.spotify_monitor = SpotifyMetadataMonitor(self.store, self.send_update, instance_id=instance_id)
        log(f"[Init] Initialized for stream: {stream_id} (instance: {instance_id or 'default'})")

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
        can_control = self.spotify_monitor.is_available()

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
            "canSeek": can_control,  # Spotify supports seeking via MPRIS
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
                can_control = self.spotify_monitor.is_available()

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
                    "canSeek": can_control,  # Spotify supports seeking via MPRIS
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

                if not self.spotify_monitor.is_available():
                    # Return error if D-Bus not available
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Control not available (Spotify not connected)"
                        }
                    }
                    print(json.dumps(error_response), file=sys.stdout, flush=True)
                    return

                # Execute command via D-Bus and update state
                if command == "play":
                    self.spotify_monitor.play()
                    self.send_update()
                elif command == "pause":
                    self.spotify_monitor.pause()
                    self.send_update()
                elif command == "playPause":
                    # Toggle state
                    current_state = self.store.get_all().get("playback_status", "Paused")
                    if current_state == "Playing":
                        self.spotify_monitor.pause()
                    else:
                        self.spotify_monitor.play()
                    self.send_update()
                elif command == "next":
                    self.spotify_monitor.next_track()
                    self.send_update()
                elif command == "previous" or command == "prev":
                    self.spotify_monitor.previous_track()
                    self.send_update()
                elif command == "seek":
                    # Seek to specific position (in milliseconds)
                    position = params.get("position", 0)
                    log(f"[Control] Seeking to position: {position}ms")
                    self.spotify_monitor.seek(position)
                    self.send_update()
                else:
                    log(f"[Warning] Unknown control command: {command}")

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
        log("[Main] Spotify Control Script starting...")

        # Start metadata monitor in background thread
        if DBUS_AVAILABLE:
            monitor_thread = threading.Thread(target=self._run_dbus_loop, daemon=True)
            monitor_thread.start()
            self.spotify_monitor.start()

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

    def _run_dbus_loop(self):
        """Run D-Bus main loop in background thread"""
        if not DBUS_AVAILABLE:
            return

        try:
            log("[DBus] Starting GLib main loop...")
            loop = GLib.MainLoop()
            loop.run()
        except Exception as e:
            log(f"[DBus] Main loop error: {e}")


if __name__ == "__main__":
    # Parse command line arguments passed by Snapcast
    parser = argparse.ArgumentParser(description='Spotify metadata control script for Snapcast')
    parser.add_argument('--instance-id', required=False, help='Instance ID for multi-instance mode (1, 2, 3, etc.)')
    parser.add_argument('--stream', required=False, default='Spotify', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    # Multi-instance support: override log file path
    if args.instance_id:
        globals()['LOG_FILE'] = f"/tmp/spotify-control-script-{args.instance_id}.log"
        log(f"[Init] Multi-instance control script: instance={args.instance_id}")

    log(f"[Main] Starting with args: stream={args.stream}, instance={args.instance_id or 'default'}, host={args.snapcast_host}, port={args.snapcast_port}")

    script = SnapcastControlScript(stream_id=args.stream, instance_id=args.instance_id)
    script.run()
