#!/usr/bin/env python3
"""
Snapcast Control Script for Bluetooth Metadata
Monitors BlueZ D-Bus for MPRIS/AVRCP metadata and provides it to Snapcast via JSON-RPC
"""

import argparse
import json
import sys
import threading
import time
from typing import Dict, Optional
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# Configuration
LOG_FILE = "/tmp/bluetooth-control-script.log"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"

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


class BluetoothMetadataMonitor:
    """Monitor BlueZ D-Bus for Bluetooth audio metadata"""

    def __init__(self, on_metadata_changed):
        self.on_metadata_changed = on_metadata_changed
        self.current_metadata = {
            "title": None,
            "artist": None,
            "album": None,
            "artUrl": None
        }
        self.current_player = None

        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

        log("[DEBUG] BlueZ metadata monitor initialized")

    def _extract_metadata_from_dict(self, metadata_dict: Dict) -> Dict:
        """Extract metadata from BlueZ MediaPlayer1 or MediaControl1 properties"""
        result = {}

        try:
            # MPRIS/AVRCP metadata fields
            if 'Title' in metadata_dict:
                result['title'] = str(metadata_dict['Title'])
                log(f"[DEBUG] Title: {result['title']}")

            if 'Artist' in metadata_dict:
                # Artist can be a string or array
                artist = metadata_dict['Artist']
                if isinstance(artist, str):
                    result['artist'] = artist
                elif hasattr(artist, '__iter__'):
                    result['artist'] = ', '.join(str(a) for a in artist)
                else:
                    result['artist'] = str(artist)
                log(f"[DEBUG] Artist: {result['artist']}")

            if 'Album' in metadata_dict:
                result['album'] = str(metadata_dict['Album'])
                log(f"[DEBUG] Album: {result['album']}")

            # Album art - BlueZ doesn't typically provide this via AVRCP
            # but some implementations might expose it
            if 'AlbumArt' in metadata_dict:
                result['artUrl'] = str(metadata_dict['AlbumArt'])
                log(f"[DEBUG] Album Art: {result['artUrl']}")

        except Exception as e:
            log(f"[DEBUG] Error extracting metadata: {e}")

        return result

    def _properties_changed_handler(self, interface, changed, invalidated, path):
        """Handle D-Bus PropertiesChanged signals"""
        try:
            # We're interested in MediaPlayer1 or MediaControl1 interfaces
            if interface not in ['org.bluez.MediaPlayer1', 'org.bluez.MediaControl1']:
                return

            log(f"[DEBUG] Properties changed on {path}: {list(changed.keys())}")

            # Check if Track metadata changed
            if 'Track' in changed:
                track_dict = changed['Track']
                log(f"[DEBUG] Track metadata changed: {list(track_dict.keys())}")

                metadata = self._extract_metadata_from_dict(track_dict)

                if metadata:
                    # Update current metadata
                    for key, value in metadata.items():
                        if value is not None:
                            self.current_metadata[key] = value

                    # Notify if we have at least title or artist
                    if self.current_metadata.get('title') or self.current_metadata.get('artist'):
                        log(f"[DEBUG] Sending metadata update")
                        self.on_metadata_changed(self.current_metadata.copy())

            # Some implementations send fields directly
            else:
                metadata = {}
                if 'Title' in changed:
                    metadata['title'] = str(changed['Title'])
                if 'Artist' in changed:
                    metadata['artist'] = str(changed['Artist'])
                if 'Album' in changed:
                    metadata['album'] = str(changed['Album'])

                if metadata:
                    for key, value in metadata.items():
                        self.current_metadata[key] = value

                    log(f"[DEBUG] Sending direct metadata update")
                    self.on_metadata_changed(self.current_metadata.copy())

        except Exception as e:
            log(f"[DEBUG] Error handling properties changed: {e}")

    def start(self):
        """Start monitoring D-Bus for Bluetooth metadata"""
        log("[DEBUG] Starting Bluetooth metadata monitoring...")

        try:
            # Subscribe to PropertiesChanged signals from BlueZ
            self.bus.add_signal_receiver(
                self._properties_changed_handler,
                dbus_interface='org.freedesktop.DBus.Properties',
                signal_name='PropertiesChanged',
                path_keyword='path'
            )

            log("[DEBUG] Subscribed to BlueZ D-Bus signals")

            # Try to find existing media players
            self._scan_for_players()

            # Start GLib main loop in a thread
            self.loop = GLib.MainLoop()
            self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
            self.loop_thread.start()

            log("[DEBUG] GLib main loop started")

        except Exception as e:
            log(f"[DEBUG] Error starting Bluetooth monitor: {e}")

    def _scan_for_players(self):
        """Scan for existing Bluetooth media players"""
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
                    log(f"[DEBUG] Found media player: {path}")
                    self.current_player = path

                    # Get current track if available
                    props = interfaces['org.bluez.MediaPlayer1']
                    if 'Track' in props:
                        metadata = self._extract_metadata_from_dict(props['Track'])
                        if metadata:
                            for key, value in metadata.items():
                                if value is not None:
                                    self.current_metadata[key] = value
                            log(f"[DEBUG] Initial metadata loaded")

        except Exception as e:
            log(f"[DEBUG] Error scanning for players: {e}")

    def stop(self):
        """Stop monitoring"""
        if hasattr(self, 'loop'):
            self.loop.quit()


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.last_metadata = {}
        self.bt_monitor = BluetoothMetadataMonitor(self.on_metadata_changed)
        log(f"[DEBUG] Initialized for stream: {stream_id}")

    def send_notification(self, method: str, params: Dict):
        """Send JSON-RPC notification to Snapcast via stdout"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        notification_str = json.dumps(notification)
        # Write to stdout for Snapcast to read
        print(notification_str, file=sys.stdout, flush=True)
        log(f"[DEBUG] Sent notification: {notification_str[:300]}")

    def on_metadata_changed(self, metadata: Dict):
        """Callback when Bluetooth metadata changes"""
        log(f"[DEBUG] Metadata changed: {metadata}")

        # Check if this is a new track
        is_new_track = (
            not self.last_metadata or
            self.last_metadata.get("title") != metadata.get("title") or
            self.last_metadata.get("artist") != metadata.get("artist")
        )

        if is_new_track:
            log(f"[DEBUG] New track: {metadata.get('title')} - {metadata.get('artist')}")

        self.last_metadata = metadata
        self.send_metadata_update(metadata)

    def _write_artwork_json(self, metadata: Dict):
        """Write current metadata to JSON file for frontend to fetch"""
        try:
            from pathlib import Path
            artwork_file = Path(SNAPCAST_WEB_ROOT) / "bluetooth-artwork.json"
            artwork_data = {
                "artUrl": metadata.get("artUrl"),
                "title": metadata.get("title"),
                "artist": metadata.get("artist"),
                "album": metadata.get("album"),
                "timestamp": time.time()
            }
            with open(artwork_file, 'w') as f:
                json.dump(artwork_data, f)
            log(f"[DEBUG] Wrote artwork JSON to {artwork_file}")
        except Exception as e:
            log(f"Error writing artwork JSON: {e}")

    def send_metadata_update(self, metadata: Dict):
        """Send Plugin.Stream.Player.Properties with metadata"""
        # Build metadata dict (nested under "metadata" key as per Snapcast spec)
        meta_obj = {}

        if metadata.get("title"):
            meta_obj["name"] = metadata["title"]  # Use "name" for title per Snapcast docs

        if metadata.get("artist"):
            # Artist should be an array
            artist = metadata["artist"]
            meta_obj["artist"] = [artist] if isinstance(artist, str) else artist

        if metadata.get("album"):
            meta_obj["album"] = metadata["album"]

        if metadata.get("artUrl"):
            # Use MPRIS standard field name for artwork
            meta_obj["mpris:artUrl"] = metadata["artUrl"]

        if meta_obj:
            # Build the properties object
            properties = {"metadata": meta_obj}

            # Also add artUrl as a top-level property
            if metadata.get("artUrl"):
                properties["artUrl"] = metadata["artUrl"]

            # Send Plugin.Stream.Player.Properties
            self.send_notification("Plugin.Stream.Player.Properties", properties)
            log(f"[DEBUG] Sent metadata update: {list(meta_obj.keys())}")
            if metadata.get("artUrl"):
                log(f"[DEBUG] Also sent top-level artUrl: {metadata['artUrl']}")

        # Write metadata to JSON file for frontend
        self._write_artwork_json(metadata)

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")

            log(f"[DEBUG] Received command: {method}")

            # Respond to getProperties with current metadata
            if method == "Plugin.Stream.Player.GetProperties":
                # Build metadata object (same format as notifications)
                meta_obj = {}
                if self.last_metadata:
                    if self.last_metadata.get("title"):
                        meta_obj["name"] = self.last_metadata["title"]
                    if self.last_metadata.get("artist"):
                        artist = self.last_metadata["artist"]
                        meta_obj["artist"] = [artist] if isinstance(artist, str) else artist
                    if self.last_metadata.get("album"):
                        meta_obj["album"] = self.last_metadata["album"]
                    if self.last_metadata.get("artUrl"):
                        meta_obj["mpris:artUrl"] = self.last_metadata["artUrl"]

                # Build result with metadata and top-level artUrl
                result = {"metadata": meta_obj}
                if self.last_metadata and self.last_metadata.get("artUrl"):
                    result["artUrl"] = self.last_metadata["artUrl"]

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }
                response_str = json.dumps(response)
                print(response_str, file=sys.stdout, flush=True)
                log(f"[DEBUG] Sent GetProperties response: {response_str[:300]}")

        except json.JSONDecodeError:
            log(f"[DEBUG] Invalid JSON: {line}")
        except Exception as e:
            log(f"[DEBUG] Error handling command: {e}")

    def run(self):
        """Main event loop"""
        log("[DEBUG] Bluetooth Control Script starting...")

        # Start Bluetooth metadata monitoring
        self.bt_monitor.start()

        # Send Plugin.Stream.Ready notification to tell Snapcast we're ready
        self.send_notification("Plugin.Stream.Ready", {})
        log("[DEBUG] Sent Plugin.Stream.Ready notification")

        # Process commands from stdin (from Snapcast)
        log("[DEBUG] Listening for commands on stdin...")
        try:
            for line in sys.stdin:
                line = line.strip()
                log(f"[DEBUG] Received from stdin: {line[:200] if line else '(empty)'}")
                if line:
                    self.handle_command(line)
        except KeyboardInterrupt:
            log("[DEBUG] Shutting down...")
        except Exception as e:
            log(f"[DEBUG] Fatal error: {e}")
        finally:
            self.bt_monitor.stop()


if __name__ == "__main__":
    # Parse command line arguments passed by Snapcast
    parser = argparse.ArgumentParser(description='Bluetooth metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default='Bluetooth', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    log(f"[DEBUG] Starting with args: stream={args.stream}, host={args.snapcast_host}, port={args.snapcast_port}")

    script = SnapcastControlScript(stream_id=args.stream)
    script.run()
