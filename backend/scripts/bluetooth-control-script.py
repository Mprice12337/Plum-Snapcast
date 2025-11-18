#!/usr/bin/env python3
"""
Snapcast Control Script for Bluetooth Metadata
Monitors BlueZ D-Bus for MPRIS/AVRCP metadata and provides it to Snapcast via JSON-RPC

Based on proven pattern from airplay-control-script.py:
- Thread-safe metadata storage with atomic updates
- Playback state tracking (Playing/Paused/Stopped)
- Control command handling via BlueZ D-Bus
- Complete properties response for Snapcast
"""

import argparse
import json
import sys
import threading
import time
from typing import Dict, Optional

# Configuration
LOG_FILE = "/tmp/bluetooth-control-script.log"

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
    log("[Warning] D-Bus not available - Bluetooth features disabled")


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

                return meta
            return None


class BluetoothMetadataMonitor:
    """Monitor BlueZ D-Bus for Bluetooth audio metadata and playback state"""

    def __init__(self, store: MetadataStore, on_update_callback):
        self.store = store
        self.on_update = on_update_callback
        self.current_player_path = None
        self.player_interface = None
        self.player_properties = None
        self.bus = None

        if not DBUS_AVAILABLE:
            log("[Bluetooth] D-Bus not available - monitoring disabled")
            return

        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        log("[Bluetooth] D-Bus monitor initialized")

    def _extract_metadata_from_dict(self, metadata_dict: Dict) -> Dict:
        """Extract metadata from BlueZ MediaPlayer1 Track properties"""
        result = {}

        try:
            # MPRIS/AVRCP metadata fields
            if 'Title' in metadata_dict:
                result['title'] = str(metadata_dict['Title'])
                log(f"[Metadata] Title: {result['title']}")

            if 'Artist' in metadata_dict:
                # Artist can be a string or array
                artist = metadata_dict['Artist']
                if isinstance(artist, str):
                    result['artist'] = artist
                elif hasattr(artist, '__iter__'):
                    result['artist'] = ', '.join(str(a) for a in artist)
                else:
                    result['artist'] = str(artist)
                log(f"[Metadata] Artist: {result['artist']}")

            if 'Album' in metadata_dict:
                result['album'] = str(metadata_dict['Album'])
                log(f"[Metadata] Album: {result['album']}")

            # Note: BlueZ typically doesn't provide album art via AVRCP
            # Most phone implementations don't support this
            if 'AlbumArt' in metadata_dict:
                result['artUrl'] = str(metadata_dict['AlbumArt'])
                log(f"[Metadata] Album Art: {result['artUrl']}")

        except Exception as e:
            log(f"[Error] Metadata extraction failed: {e}")

        return result

    def _extract_playback_status(self, status_str: str) -> str:
        """Convert MPRIS playback status to our format"""
        # MPRIS statuses: "playing", "paused", "stopped"
        status_map = {
            "playing": "Playing",
            "paused": "Paused",
            "stopped": "Stopped",
        }
        return status_map.get(status_str.lower(), "Stopped")

    def _properties_changed_handler(self, interface, changed, invalidated, path):
        """Handle D-Bus PropertiesChanged signals"""
        try:
            # We're interested in MediaPlayer1 interface
            if interface != 'org.bluez.MediaPlayer1':
                return

            log(f"[DBus] Properties changed on {path}: {list(changed.keys())}")

            # If we don't have a player interface yet, set it up now
            # This handles the case where bluetoothd wasn't ready during startup scan
            if self.player_interface is None and path:
                try:
                    log(f"[DBus] Setting up player interface for {path}")
                    player_obj = self.bus.get_object('org.bluez', path)
                    self.player_interface = dbus.Interface(player_obj, 'org.bluez.MediaPlayer1')
                    self.player_properties = dbus.Interface(player_obj, 'org.freedesktop.DBus.Properties')
                    self.current_player_path = path
                    log(f"[DBus] ✓ Player interface ready - controls enabled")

                    # Notify that control became available
                    if self.on_update:
                        self.on_update()
                except Exception as e:
                    log(f"[Error] Failed to setup player interface: {e}")

            updated = False

            # Check if Track metadata changed
            if 'Track' in changed:
                track_dict = changed['Track']
                log(f"[DBus] Track metadata changed: {list(track_dict.keys())}")

                metadata = self._extract_metadata_from_dict(track_dict)

                if metadata:
                    # Update store with new metadata
                    self.store.update(**metadata)
                    updated = True

            # Check if playback status changed
            if 'Status' in changed:
                status = self._extract_playback_status(str(changed['Status']))
                log(f"[DBus] Status changed: {status}")
                self.store.update(playback_status=status)
                updated = True

            # Notify parent if anything changed
            if updated and self.on_update:
                self.on_update()

        except Exception as e:
            log(f"[Error] Properties changed handler failed: {e}")

    def start(self):
        """Start monitoring D-Bus for Bluetooth metadata"""
        if not DBUS_AVAILABLE:
            return

        log("[Bluetooth] Starting metadata monitoring...")

        try:
            # Subscribe to PropertiesChanged signals from BlueZ
            self.bus.add_signal_receiver(
                self._properties_changed_handler,
                dbus_interface='org.freedesktop.DBus.Properties',
                signal_name='PropertiesChanged',
                path_keyword='path'
            )

            log("[Bluetooth] Subscribed to BlueZ D-Bus signals")

            # Try to find existing media players
            self._scan_for_players()

            # Start GLib main loop in a thread
            self.loop = GLib.MainLoop()
            self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
            self.loop_thread.start()

            log("[Bluetooth] GLib main loop started")

        except Exception as e:
            log(f"[Error] Failed to start Bluetooth monitor: {e}")

    def _scan_for_players(self):
        """Scan for existing Bluetooth media players"""
        if not DBUS_AVAILABLE:
            return

        try:
            # Get BlueZ object manager
            obj_manager = dbus.Interface(
                self.bus.get_object('org.bluez', '/'),
                'org.freedesktop.DBus.ObjectManager'
            )

            objects = obj_manager.GetManagedObjects()

            for path, interfaces in objects.items():
                # Look for MediaPlayer1 interfaces
                if 'org.bluez.MediaPlayer1' in interfaces:
                    log(f"[Bluetooth] Found media player: {path}")
                    self.current_player_path = path

                    # Get interfaces for control
                    player_obj = self.bus.get_object('org.bluez', path)
                    self.player_interface = dbus.Interface(player_obj, 'org.bluez.MediaPlayer1')
                    self.player_properties = dbus.Interface(player_obj, 'org.freedesktop.DBus.Properties')

                    # Get current track if available
                    props = interfaces['org.bluez.MediaPlayer1']
                    if 'Track' in props:
                        metadata = self._extract_metadata_from_dict(props['Track'])
                        if metadata:
                            self.store.update(**metadata)
                            log(f"[Bluetooth] Initial metadata loaded")

                    # Get current playback status
                    if 'Status' in props:
                        status = self._extract_playback_status(str(props['Status']))
                        self.store.update(playback_status=status)
                        log(f"[Bluetooth] Initial status: {status}")

        except Exception as e:
            log(f"[Error] Player scan failed: {e}")

    def play(self):
        """Send play command via BlueZ"""
        if self.player_interface:
            try:
                self.player_interface.Play()
                log("[Control] Sent Play command")
                self.store.update(playback_status="Playing")
            except Exception as e:
                log(f"[Error] Play failed: {e}")

    def pause(self):
        """Send pause command via BlueZ"""
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
            except Exception as e:
                log(f"[Error] Next failed: {e}")

    def previous_track(self):
        """Skip to previous track"""
        if self.player_interface:
            try:
                self.player_interface.Previous()
                log("[Control] Sent Previous command")
            except Exception as e:
                log(f"[Error] Previous failed: {e}")

    def is_available(self):
        """Check if control is available"""
        return self.player_interface is not None

    def stop(self):
        """Stop monitoring"""
        if hasattr(self, 'loop'):
            self.loop.quit()


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.store = MetadataStore()
        self.bt_monitor = BluetoothMetadataMonitor(self.store, self.send_update)
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
        playback_status = self.store.get_all().get("playback_status", "Stopped")
        can_control = self.bt_monitor.is_available()

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

        # Log what we sent
        if meta_obj:
            title = meta_obj.get('title', 'N/A')
            artist = meta_obj.get('artist', ['N/A'])
            artist_str = artist[0] if isinstance(artist, list) and artist else 'N/A'
            log(f"[Snapcast] Metadata → {title} - {artist_str} [{playback_status}] (stream={self.stream_id})")
            if "artUrl" in meta_obj:
                log(f"[Snapcast]   Artwork: {len(meta_obj['artUrl'])} chars")
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
                playback_status = self.store.get_all().get("playback_status", "Stopped")
                can_control = self.bt_monitor.is_available()

                # Build complete properties response per Snapcast Stream Plugin API
                properties = {
                    # Playback state
                    "playbackStatus": playback_status,
                    "loopStatus": "none",
                    "shuffle": False,
                    "volume": 100,
                    "mute": False,
                    "rate": 1.0,
                    "position": 0,

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

                if not self.bt_monitor.is_available():
                    # Return error if D-Bus not available
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Control not available (no Bluetooth player connected)"
                        }
                    }
                    print(json.dumps(error_response), file=sys.stdout, flush=True)
                    return

                # Execute command via D-Bus and update state
                if command == "play":
                    self.bt_monitor.play()
                    self.send_update()
                elif command == "pause":
                    self.bt_monitor.pause()
                    self.send_update()
                elif command == "playPause":
                    # Toggle state
                    current_state = self.store.get_all().get("playback_status", "Paused")
                    if current_state == "Playing":
                        self.bt_monitor.pause()
                    else:
                        self.bt_monitor.play()
                    self.send_update()
                elif command == "next":
                    self.bt_monitor.next_track()
                    self.send_update()
                elif command == "previous" or command == "prev":
                    self.bt_monitor.previous_track()
                    self.send_update()
                else:
                    log(f"[Snapcast] Unknown control command: {command}")

                # Send success response
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                }
                print(json.dumps(response), file=sys.stdout, flush=True)
                log(f"[Control] Sent success response for: {command}")

            else:
                # Unknown method
                log(f"[Command] WARNING: Unknown method '{method}'")
                if request_id:
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}"
                        }
                    }
                    print(json.dumps(error_response), file=sys.stdout, flush=True)

        except json.JSONDecodeError as e:
            log(f"[Error] Invalid JSON received: {e}")
        except Exception as e:
            log(f"[Error] Command handler exception: {e}")
            import traceback
            log(f"[Error] {traceback.format_exc()}")
            if 'request_id' in locals() and request_id:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }
                print(json.dumps(error_response), file=sys.stdout, flush=True)

    def run(self):
        """Main event loop"""
        log("[Init] Bluetooth Control Script starting...")

        # Start Bluetooth metadata monitoring
        self.bt_monitor.start()

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
        finally:
            self.bt_monitor.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Bluetooth metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default='Bluetooth', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    log(f"[Init] Starting with args: stream={args.stream}")

    script = SnapcastControlScript(stream_id=args.stream)
    script.run()
