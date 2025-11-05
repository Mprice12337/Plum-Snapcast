#!/usr/bin/env python3
"""
Snapcast Control Script for Spotify Connect (Librespot)
Monitors metadata from librespot event handler and provides playback control
"""

import argparse
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
METADATA_FILE = "/tmp/spotify-metadata.json"
COVER_ART_DIR = "/tmp/spotify/.cache/coverart"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
LOG_FILE = "/tmp/spotify-control-script.log"
LIBRESPOT_CONTROL_PIPE = "/tmp/librespot-control"

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


class SpotifyMetadataMonitor:
    """Monitor Spotify metadata from librespot event handler"""

    def __init__(self):
        self.last_metadata = {}
        self.last_mtime = 0

    def get_metadata(self) -> Optional[Dict]:
        """Check for new metadata from event handler"""
        try:
            if not Path(METADATA_FILE).exists():
                return None

            # Check if file was modified
            mtime = os.path.getmtime(METADATA_FILE)
            if mtime <= self.last_mtime:
                return None

            self.last_mtime = mtime

            # Read metadata
            with open(METADATA_FILE, 'r') as f:
                metadata = json.load(f)

            # Only return metadata for track change events
            event = metadata.get('event', '')
            if event in ['start', 'load', 'change']:
                return metadata

            return None

        except Exception as e:
            log(f"Error reading metadata: {e}")
            return None


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.metadata_monitor = SpotifyMetadataMonitor()
        self.last_metadata = {}
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

    def _write_artwork_json(self, metadata: Dict):
        """Write current artwork URL to JSON file for frontend to fetch"""
        try:
            artwork_file = Path(SNAPCAST_WEB_ROOT) / "spotify-artwork.json"
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

    def _download_cover_art(self, cover_url: str) -> Optional[str]:
        """Download cover art from Spotify and save to web root"""
        if not cover_url:
            return None

        try:
            # Create a filename from the URL
            import hashlib
            url_hash = hashlib.md5(cover_url.encode()).hexdigest()
            filename = f"{url_hash}.jpg"

            # Save to Snapcast web root so it's accessible via HTTP
            web_cover_dir = Path(SNAPCAST_WEB_ROOT) / "coverart"
            web_cover_dir.mkdir(parents=True, exist_ok=True)
            web_cover_path = web_cover_dir / filename

            # Check if already downloaded
            if web_cover_path.exists():
                log(f"[DEBUG] Cover art already cached: {filename}")
                return f"/coverart/{filename}"

            # Download cover art
            log(f"[DEBUG] Downloading cover art from: {cover_url[:100]}")
            req = urllib.request.Request(cover_url, headers={'User-Agent': 'Snapcast/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                cover_data = response.read()

            # Save to web root
            with open(web_cover_path, "wb") as f:
                f.write(cover_data)

            # Make sure the file is readable by the web server
            os.chmod(web_cover_path, 0o644)

            # Also save to cache directory for backup
            cover_dir = Path(COVER_ART_DIR)
            cover_dir.mkdir(parents=True, exist_ok=True)
            cache_path = cover_dir / filename
            with open(cache_path, "wb") as f:
                f.write(cover_data)

            # Return HTTP URL that's accessible from browser
            log(f"[DEBUG] Cover art saved to {web_cover_path} ({len(cover_data)} bytes)")
            return f"/coverart/{filename}"

        except Exception as e:
            log(f"Error downloading cover art: {e}")
            return None

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

        if metadata.get("track_id"):
            meta_obj["mpris:trackid"] = f"spotify:track:{metadata['track_id']}"

        if metadata.get("duration_ms"):
            # Duration in microseconds (MPRIS standard)
            try:
                meta_obj["mpris:length"] = int(metadata["duration_ms"]) * 1000
            except:
                pass

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

        # Write artwork JSON for frontend
        if metadata.get("artUrl"):
            self._write_artwork_json(metadata)

    def send_playback_command(self, command: str):
        """Send playback command to librespot via control pipe"""
        try:
            # Librespot doesn't have a built-in control interface via pipe
            # We need to use D-Bus MPRIS interface instead
            # For now, just log the command
            log(f"[DEBUG] Playback command received: {command}")
            log(f"[WARNING] Playback control via D-Bus MPRIS not yet implemented")
            # TODO: Implement D-Bus MPRIS control
            # import dbus
            # bus = dbus.SessionBus()
            # player = bus.get_object('org.mpris.MediaPlayer2.spotifyd', '/org/mpris/MediaPlayer2')
            # player_iface = dbus.Interface(player, 'org.mpris.MediaPlayer2.Player')
            # if command == "play":
            #     player_iface.Play()
            # elif command == "pause":
            #     player_iface.Pause()
            # elif command == "next":
            #     player_iface.Next()
            # elif command == "previous":
            #     player_iface.Previous()
        except Exception as e:
            log(f"Error sending playback command: {e}")

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")
            params = request.get("params", {})

            log(f"[DEBUG] Received command: {method} with params: {params}")

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
                    if self.last_metadata.get("track_id"):
                        meta_obj["mpris:trackid"] = f"spotify:track:{self.last_metadata['track_id']}"
                    if self.last_metadata.get("duration_ms"):
                        try:
                            meta_obj["mpris:length"] = int(self.last_metadata["duration_ms"]) * 1000
                        except:
                            pass

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

            # Handle playback control commands
            elif method == "Plugin.Stream.Player.Control":
                command = params.get("command", "")
                log(f"[DEBUG] Control command: {command}")
                self.send_playback_command(command)

                # Send response
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                }
                response_str = json.dumps(response)
                print(response_str, file=sys.stdout, flush=True)

        except json.JSONDecodeError:
            log(f"[DEBUG] Invalid JSON: {line}")
        except Exception as e:
            log(f"[DEBUG] Error handling command: {e}")

    def monitor_metadata(self):
        """Monitor metadata file in background thread"""
        log("[DEBUG] Starting metadata monitor")

        while True:
            try:
                # Check for new metadata
                metadata = self.metadata_monitor.get_metadata()

                if metadata:
                    log(f"[DEBUG] New metadata: {metadata.get('title')} - {metadata.get('artist')}")

                    # Download cover art if available
                    cover_url = metadata.get("cover_url")
                    if cover_url:
                        art_url = self._download_cover_art(cover_url)
                        if art_url:
                            metadata["artUrl"] = art_url

                    # Update last metadata
                    self.last_metadata = metadata

                    # Send metadata update
                    self.send_metadata_update(metadata)

                time.sleep(0.5)  # Poll every 500ms

            except Exception as e:
                log(f"[DEBUG] Error in metadata monitor: {e}")
                time.sleep(1)

    def run(self):
        """Main event loop"""
        log("[DEBUG] Spotify Control Script starting...")

        # Start metadata monitor in background thread
        metadata_thread = threading.Thread(target=self.monitor_metadata, daemon=True)
        metadata_thread.start()

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


if __name__ == "__main__":
    # Parse command line arguments passed by Snapcast
    parser = argparse.ArgumentParser(description='Spotify metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default='Spotify', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    log(f"[DEBUG] Starting with args: stream={args.stream}, host={args.snapcast_host}, port={args.snapcast_port}")

    script = SnapcastControlScript(stream_id=args.stream)
    script.run()
