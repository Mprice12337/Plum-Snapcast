#!/usr/bin/env python3
"""
Snapcast Control Script for AirPlay Metadata
Reads metadata from shairport-sync pipe and provides it to Snapcast via JSON-RPC

Based on proven pattern from shairport-metadatareader-python:
- Private/public state separation
- Atomic updates only at bundle markers (mden/pcen)
- Independent metadata and artwork state machines
"""

import argparse
import base64
import json
import sys
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


class MetadataParser:
    """
    Parse shairport-sync metadata using atomic bundle pattern.

    Pattern (from shairport-metadatareader-python):
    - Accumulate in PRIVATE state (_tmp_metadata, _tmp_artwork)
    - Publish ATOMICALLY to PUBLIC state (metadata, artwork)
    - Only publish at bundle boundaries (mden, pcen)
    """

    def __init__(self):
        # === PRIVATE STATE (accumulating during bundle) ===
        self._tmp_metadata = {}  # Accumulates between mdst...mden
        self._tmp_artwork_data = []  # Accumulates PICT chunks between pcst...pcen

        # === PUBLIC STATE (published atomically) ===
        self.metadata = {}  # Published at mden
        self.artwork = None  # Published at pcen (data URL or None)

        # === STATE FLAGS ===
        self._in_metadata_bundle = False  # Between mdst and mden
        self._in_artwork_bundle = False  # Between pcst and pcen
        self._last_artwork_filename = None  # Track which cache file we loaded

        # === TRACKING ===
        self._current_track_id = None  # mper value for track change detection

    def parse_item(self, item_xml: str) -> Optional[Dict]:
        """
        Parse one XML item and update internal state.
        Returns update dict when bundle completes, None otherwise.
        """
        try:
            root = ET.fromstring(item_xml)

            # Extract type and code
            type_elem = root.find("type")
            code_elem = root.find("code")
            if code_elem is None:
                return None

            item_type = bytes.fromhex(type_elem.text).decode('ascii', errors='ignore') if type_elem is not None else ""
            code = bytes.fromhex(code_elem.text).decode('ascii', errors='ignore')

            # Extract data
            data_elem = root.find("data")
            encoding = data_elem.get("encoding", "") if data_elem is not None else ""
            data_text = (data_elem.text or "").strip() if data_elem is not None else ""

            decoded = ""
            if encoding == "base64" and data_text:
                try:
                    decoded = base64.b64decode(data_text).decode('utf-8', errors='ignore')
                except:
                    decoded = ""

            # ===== METADATA BUNDLE MARKERS =====
            if code == "mdst":
                # Metadata bundle start - prepare to accumulate
                self._in_metadata_bundle = True
                # DON'T clear _tmp_metadata! Let it accumulate
                log(f"[Bundle] Metadata START")
                return None

            elif code == "mden":
                # Metadata bundle end - ATOMIC PUBLISH
                self._in_metadata_bundle = False

                if self._tmp_metadata:
                    # ATOMIC: swap entire dict at once
                    self.metadata = self._tmp_metadata.copy()

                    # Log what we published
                    title = self.metadata.get('title', 'Unknown')
                    artist = self.metadata.get('artist', 'Unknown')
                    album = self.metadata.get('album', 'Unknown')
                    track_id = self.metadata.get('track_id', 'Unknown')
                    log(f"[Bundle] Metadata END - Published: {title} - {artist}")
                    log(f"[Bundle]   Album: {album}, Track ID: {track_id[:5]}...")

                    # Clear tmp storage
                    self._tmp_metadata = {}

                    # Return complete metadata update
                    return {
                        'type': 'metadata',
                        'data': {
                            'title': self.metadata.get('title', ''),
                            'artist': self.metadata.get('artist', ''),
                            'album': self.metadata.get('album', ''),
                            'artwork_url': self.artwork  # Current artwork (may be from previous track)
                        }
                    }
                else:
                    log(f"[Bundle] Metadata END - No data accumulated")
                    self._tmp_metadata = {}
                return None

            # ===== METADATA FIELDS (accumulate during bundle) =====
            if self._in_metadata_bundle:
                if code == "mper" and decoded:  # Track ID (persistent ID)
                    track_id = decoded.strip()
                    if track_id:
                        self._tmp_metadata['track_id'] = track_id

                        # Detect track change
                        if self._current_track_id and self._current_track_id != track_id:
                            log(f"[Track] CHANGE detected: {self._current_track_id[:5]}... → {track_id[:5]}...")
                            # Clear artwork on track change
                            self.artwork = None
                        elif not self._current_track_id:
                            log(f"[Track] First track: {track_id[:5]}...")

                        self._current_track_id = track_id

                elif code == "minm" and decoded.strip():  # Title
                    self._tmp_metadata['title'] = decoded.strip()
                    log(f"[Field] Title: {decoded.strip()}")

                elif code == "asar" and decoded.strip():  # Artist
                    self._tmp_metadata['artist'] = decoded.strip()
                    log(f"[Field] Artist: {decoded.strip()}")

                elif code == "asal" and decoded.strip():  # Album
                    self._tmp_metadata['album'] = decoded.strip()
                    log(f"[Field] Album: {decoded.strip()}")

            # ===== ARTWORK BUNDLE MARKERS =====
            if item_type == "ssnc":
                if code == "pcst":
                    # Artwork bundle start
                    self._in_artwork_bundle = True
                    self._tmp_artwork_data = []
                    log(f"[Artwork] START marker")
                    return None

                elif code == "pcen":
                    # Artwork bundle end - ATOMIC PUBLISH
                    self._in_artwork_bundle = False
                    log(f"[Artwork] END marker")

                    # Load from cache (shairport-sync writes to disk)
                    artwork_url = self._load_artwork_from_cache()
                    if artwork_url:
                        self.artwork = artwork_url
                        log(f"[Artwork] Published ({len(artwork_url)} chars)")

                        # Send updated metadata with new artwork
                        if self.metadata.get('title'):
                            return {
                                'type': 'metadata',
                                'data': {
                                    'title': self.metadata.get('title', ''),
                                    'artist': self.metadata.get('artist', ''),
                                    'album': self.metadata.get('album', ''),
                                    'artwork_url': self.artwork
                                }
                            }
                    return None

        except ET.ParseError:
            # Expected when buffer cuts mid-XML
            pass
        except Exception as e:
            log(f"[Error] Parse exception: {e}")

        return None

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
            if self._last_artwork_filename == newest_file.name:
                return self.artwork  # Return existing

            # Read and encode
            with open(newest_file, 'rb') as f:
                image_data = f.read()

            import mimetypes
            mime_type = mimetypes.guess_type(str(newest_file))[0] or 'image/jpeg'
            data_url = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('ascii')}"

            self._last_artwork_filename = newest_file.name
            log(f"[Artwork] Loaded from cache: {newest_file.name} ({len(image_data)} bytes)")

            return data_url

        except Exception as e:
            log(f"[Error] Artwork load failed: {e}")
            return None


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.metadata_parser = MetadataParser()
        self.last_metadata = {}
        log(f"[Init] Initialized for stream: {stream_id}")

    def send_notification(self, method: str, params: Dict):
        """Send JSON-RPC notification to Snapcast via stdout"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        print(json.dumps(notification), file=sys.stdout, flush=True)
        log(f"[Snapcast] Sent: {method}")

    def send_metadata_update(self, metadata: Dict):
        """Send Plugin.Stream.Player.Properties with metadata"""
        meta_obj = {}

        if metadata.get("title"):
            meta_obj["title"] = metadata["title"]
        if metadata.get("artist"):
            meta_obj["artist"] = metadata["artist"]
        if metadata.get("album"):
            meta_obj["album"] = metadata["album"]
        if metadata.get("artwork_url"):
            meta_obj["artUrl"] = metadata["artwork_url"]

        if meta_obj:
            properties = {
                "id": self.stream_id,
                "metadata": meta_obj
            }
            self.send_notification("Plugin.Stream.Player.Properties", properties)

            # Log what we sent
            log(f"[Snapcast] Metadata update: {list(meta_obj.keys())}")
            log(f"[Snapcast]   → {metadata.get('title', 'N/A')} - {metadata.get('artist', 'N/A')}")

            self.last_metadata = metadata.copy()

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")

            if method == "Plugin.Stream.Player.GetProperties":
                # Return current metadata
                meta_obj = {}
                if self.last_metadata:
                    if self.last_metadata.get("title"):
                        meta_obj["title"] = self.last_metadata["title"]
                    if self.last_metadata.get("artist"):
                        meta_obj["artist"] = self.last_metadata["artist"]
                    if self.last_metadata.get("album"):
                        meta_obj["album"] = self.last_metadata["album"]
                    if self.last_metadata.get("artwork_url"):
                        meta_obj["artUrl"] = self.last_metadata["artwork_url"]

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"metadata": meta_obj}
                }
                print(json.dumps(response), file=sys.stdout, flush=True)

        except Exception as e:
            log(f"[Error] Command handler: {e}")

    def monitor_metadata_pipe(self):
        """Monitor shairport-sync metadata pipe"""
        log("[Init] Starting metadata pipe monitor")

        # Wait for pipe
        while not Path(METADATA_PIPE).exists():
            log(f"[Init] Waiting for pipe: {METADATA_PIPE}")
            time.sleep(1)

        log(f"[Init] Pipe found: {METADATA_PIPE}")

        # LINE-BY-LINE reading (like Python library)
        tmp = ""
        try:
            while True:
                with open(METADATA_PIPE, 'r') as pipe:
                    for line in pipe:
                        strip_line = line.strip()

                        if strip_line.endswith("</item>"):
                            # Complete item
                            item_xml = tmp + strip_line
                            result = self.metadata_parser.parse_item(item_xml)

                            if result and result['type'] == 'metadata':
                                self.send_metadata_update(result['data'])

                            tmp = ""

                        elif strip_line.startswith("<item>"):
                            # New item starting
                            if tmp:
                                # Previous item incomplete - try to close it
                                item_xml = tmp + "</item>"
                                result = self.metadata_parser.parse_item(item_xml)
                                if result and result['type'] == 'metadata':
                                    self.send_metadata_update(result['data'])

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
        import threading
        monitor_thread = threading.Thread(target=self.monitor_metadata_pipe, daemon=True)
        monitor_thread.start()

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
