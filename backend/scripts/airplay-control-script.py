#!/usr/bin/env python3
"""
Snapcast Control Script for AirPlay Metadata
Reads metadata from shairport-sync pipe and provides it to Snapcast via JSON-RPC

Uses proven metadata handling approach:
- mper (persistent track ID) for definitive track detection
- mdst/mden for metadata bundle handling
- No timestamp-based freshness checks
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


class MetadataParser:
    """Parse shairport-sync metadata using mper/mdst/mden approach"""

    def __init__(self):
        # Current track state
        self.current = {
            "title": None,
            "artist": None,
            "album": None,
            "track_id": None,  # mper - persistent track ID
            "artwork_url": None
        }

        # Metadata bundle state
        self.in_metadata_bundle = False
        self.bundle_track_id = None  # Track which track this bundle belongs to
        self.pending_metadata = {
            "title": None,
            "artist": None,
            "album": None
        }

        # Cover art state
        self.in_picture = False
        self.last_loaded_cache_file = None

    def parse_item(self, item_xml: str) -> Optional[Dict[str, any]]:
        """
        Parse a complete XML item and return metadata update if available.

        Returns:
            Dict with 'type' and 'data' keys:
            - {'type': 'metadata', 'data': {...}} - Full metadata update
            - {'type': 'artwork', 'data': '...'} - Artwork data URL
            - None - No update to send
        """
        try:
            root = ET.fromstring(item_xml)

            # Get the type and code
            type_elem = root.find("type")
            code_elem = root.find("code")

            if code_elem is None:
                return None

            # Decode type and code from hex
            item_type = bytes.fromhex(type_elem.text).decode('ascii', errors='ignore') if type_elem is not None else ""
            code = bytes.fromhex(code_elem.text).decode('ascii', errors='ignore')

            # Get the data
            data_elem = root.find("data")
            encoding = ""
            data_text = ""
            decoded = ""

            if data_elem is not None:
                encoding = data_elem.get("encoding", "")
                data_text = (data_elem.text or "").strip()

                # Decode based on encoding
                if encoding == "base64" and data_text:
                    try:
                        decoded = base64.b64decode(data_text).decode('utf-8', errors='ignore')
                    except:
                        decoded = ""

            # === TRACK DETECTION via mper ===
            if code == "mper":  # Persistent Track ID - DEFINITIVE track change indicator
                if decoded and decoded.strip():
                    track_id = decoded.strip()

                    # Check if this is a NEW track
                    if self.current["track_id"] and self.current["track_id"] != track_id:
                        log(f"[Metadata] NEW TRACK DETECTED via mper")
                        log(f"[Metadata] Previous ID: {self.current['track_id'][:5]}...")
                        log(f"[Metadata] New ID: {track_id[:5]}...")

                        # Clear ALL metadata for new track
                        self.current = {
                            "title": None,
                            "artist": None,
                            "album": None,
                            "track_id": track_id,
                            "artwork_url": None
                        }
                        # IMPORTANT: Clear pending metadata to prevent old track data from being applied
                        self.pending_metadata = {
                            "title": None,
                            "artist": None,
                            "album": None
                        }
                        # Exit any in-progress bundle (it's from the old track)
                        self.in_metadata_bundle = False
                        self.bundle_track_id = None

                        # Return cleared metadata
                        return {
                            'type': 'metadata',
                            'data': {
                                "title": "",
                                "artist": "",
                                "album": "",
                                "artwork_url": None
                            }
                        }
                    elif not self.current["track_id"]:
                        # First track
                        self.current["track_id"] = track_id
                        log(f"[Metadata] Initial track ID: {track_id[:5]}...")

            # === METADATA BUNDLE HANDLING ===
            if code == "mdst":  # Metadata bundle start
                # Only start bundle if we have a track ID
                if not self.current["track_id"]:
                    log(f"[Metadata] Skipping bundle start - no track ID yet")
                    return None

                log(f"[Metadata] >>> Metadata bundle START (track: {self.current['track_id'][:5]}...)")
                self.in_metadata_bundle = True
                self.bundle_track_id = self.current["track_id"]  # Remember which track this bundle is for
                self.pending_metadata = {
                    "title": None,
                    "artist": None,
                    "album": None
                }
                return None

            # Collect metadata during bundle (only if we have a track ID)
            if self.in_metadata_bundle and self.current["track_id"]:
                if code == "minm" and decoded:  # Title
                    # Ignore empty titles
                    if decoded.strip():
                        self.pending_metadata["title"] = decoded
                        log(f"[Metadata] Title (pending): {decoded}")

                elif code == "asar" and decoded:  # Artist
                    if decoded.strip():
                        self.pending_metadata["artist"] = decoded
                        log(f"[Metadata] Artist (pending): {decoded}")

                elif code == "asal" and decoded:  # Album
                    if decoded.strip():
                        self.pending_metadata["album"] = decoded
                        log(f"[Metadata] Album (pending): {decoded}")

            if code == "mden":  # Metadata bundle end
                self.in_metadata_bundle = False

                # Check if this bundle belongs to the current track
                if self.bundle_track_id != self.current["track_id"]:
                    log(f"[Metadata] >>> Metadata bundle END - SKIPPING (bundle from old track)")
                    self.pending_metadata = {"title": None, "artist": None, "album": None}
                    self.bundle_track_id = None
                    return None

                log(f"[Metadata] >>> Metadata bundle END (track: {self.current['track_id'][:5]}...)")

                # Only apply metadata if we have a track ID (prevents applying to unknown tracks)
                if not self.current["track_id"]:
                    log(f"[Metadata] Skipping bundle - no track ID yet")
                    self.pending_metadata = {"title": None, "artist": None, "album": None}
                    self.bundle_track_id = None
                    return None

                # Apply all pending metadata atomically
                has_update = False

                if self.pending_metadata["title"]:
                    self.current["title"] = self.pending_metadata["title"]
                    log(f"[Metadata] Applied title: {self.current['title']}")
                    has_update = True

                if self.pending_metadata["artist"]:
                    self.current["artist"] = self.pending_metadata["artist"]
                    log(f"[Metadata] Applied artist: {self.current['artist']}")
                    has_update = True

                if self.pending_metadata["album"]:
                    self.current["album"] = self.pending_metadata["album"]
                    log(f"[Metadata] Applied album: {self.current['album']}")
                    has_update = True

                # Clear pending state
                self.pending_metadata = {
                    "title": None,
                    "artist": None,
                    "album": None
                }
                self.bundle_track_id = None  # Bundle processed

                # If we got title, schedule artwork check
                if self.current["title"] and has_update:
                    self._schedule_artwork_check()

                # Return full metadata update if we have at least title
                if has_update and self.current["title"]:
                    return {
                        'type': 'metadata',
                        'data': {
                            "title": self.current["title"],
                            "artist": self.current["artist"] or "",
                            "album": self.current["album"] or "",
                            "artwork_url": self.current["artwork_url"]
                        }
                    }

            # === COVER ART HANDLING ===
            if item_type == "ssnc":
                if code == "pcst":  # Picture start
                    self.in_picture = True
                    log(f"[Cover Art] Picture start marker received")

                elif code == "pcen":  # Picture end
                    self.in_picture = False
                    log(f"[Cover Art] Picture end marker received")

                    # Load from cache (shairport-sync writes to disk)
                    artwork_result = self._load_cover_art_from_cache()
                    if artwork_result:
                        return artwork_result

        except ET.ParseError as e:
            # XML parse errors are common when buffer cuts items mid-stream
            # Only log occasionally to avoid spam
            import random
            if random.random() < 0.1:  # Log 10% of parse errors
                log(f"[XML] Parse error (suppressing most): {e}")
        except Exception as e:
            log(f"[Error] Error parsing metadata: {e}")
            import traceback
            log(f"[Error] {traceback.format_exc()}")

        return None

    def _schedule_artwork_check(self):
        """Schedule a delayed check for cover art (gives cache time to update)"""
        def delayed_check():
            time.sleep(0.5)  # Wait 500ms for cache to write
            self._load_cover_art_from_cache()

        threading.Thread(target=delayed_check, daemon=True).start()

    def _load_cover_art_from_cache(self, force=False) -> Optional[Dict]:
        """
        Load cover art from shairport-sync cache directory.
        Returns artwork update dict if new artwork loaded, None otherwise.
        """
        try:
            cache_dir = Path(COVER_ART_CACHE_DIR)

            if not cache_dir.exists():
                return None

            # Find all cover art files
            cover_files = list(cache_dir.glob("cover-*.jpg")) + list(cache_dir.glob("cover-*.png"))

            if not cover_files:
                return None

            # Get the most recently modified file
            newest_file = max(cover_files, key=lambda p: p.stat().st_mtime)

            # Skip if we already loaded this file (unless forced)
            if not force and self.last_loaded_cache_file == newest_file.name:
                return None

            # Read the file
            with open(newest_file, 'rb') as f:
                image_data = f.read()

            # Encode as data URL
            import mimetypes
            mime_type = mimetypes.guess_type(str(newest_file))[0] or 'image/jpeg'
            cover_data_b64 = base64.b64encode(image_data).decode('ascii')
            data_url = f"data:{mime_type};base64,{cover_data_b64}"

            # Update state
            self.current["artwork_url"] = data_url
            self.last_loaded_cache_file = newest_file.name

            log(f"[Cover Art] Loaded from cache: {newest_file.name} ({len(image_data)} bytes)")

            # Return artwork update
            return {
                'type': 'artwork',
                'data': data_url
            }

        except Exception as e:
            log(f"[Error] Error loading cover art from cache: {e}")
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
        notification_str = json.dumps(notification)
        # Write to stdout for Snapcast to read
        print(notification_str, file=sys.stdout, flush=True)
        log(f"[Snapcast] Sent notification: {method}")

    def send_metadata_update(self, metadata: Dict):
        """Send Plugin.Stream.Player.Properties with metadata"""
        # Build metadata dict for Snapcast
        meta_obj = {}

        if metadata.get("title"):
            meta_obj["title"] = metadata["title"]

        if metadata.get("artist"):
            meta_obj["artist"] = metadata["artist"]

        if metadata.get("album"):
            meta_obj["album"] = metadata["album"]

        if metadata.get("artwork_url"):
            # Store artwork as artUrl (Snapcast standard)
            meta_obj["artUrl"] = metadata["artwork_url"]

        if meta_obj:
            # Build the properties object with stream ID
            properties = {
                "id": self.stream_id,  # Include stream ID for frontend
                "metadata": meta_obj
            }

            # Send Plugin.Stream.Player.Properties
            self.send_notification("Plugin.Stream.Player.Properties", properties)

            # Log what we sent
            fields = list(meta_obj.keys())
            log(f"[Snapcast] Updated metadata fields: {fields}")
            if metadata.get("title"):
                log(f"[Snapcast] → title: {metadata['title']}")
            if metadata.get("artist"):
                log(f"[Snapcast] → artist: {metadata['artist']}")
            if metadata.get("album"):
                log(f"[Snapcast] → album: {metadata['album']}")
            if metadata.get("artwork_url"):
                artwork_size = len(metadata['artwork_url'])
                log(f"[Snapcast] → artUrl: data URL ({artwork_size} chars)")

            # Update last metadata
            self.last_metadata = metadata.copy()

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")

            log(f"[Snapcast] Received command: {method}")

            # Respond to getProperties with current metadata
            if method == "Plugin.Stream.Player.GetProperties":
                # Build metadata object
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

                # Build result
                result = {"metadata": meta_obj}

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }
                response_str = json.dumps(response)
                print(response_str, file=sys.stdout, flush=True)
                log(f"[Snapcast] Sent GetProperties response with fields: {list(meta_obj.keys())}")

        except json.JSONDecodeError:
            log(f"[Error] Invalid JSON from Snapcast: {line[:100]}")
        except Exception as e:
            log(f"[Error] Error handling command: {e}")

    def monitor_metadata_pipe(self):
        """Monitor shairport-sync metadata pipe in background thread"""
        log("[Init] Starting metadata pipe monitor")

        # Wait for pipe to exist
        while not Path(METADATA_PIPE).exists():
            log(f"[Init] Waiting for metadata pipe: {METADATA_PIPE}")
            time.sleep(1)

        log(f"[Init] Metadata pipe found: {METADATA_PIPE}")

        buffer = ""
        try:
            with open(METADATA_PIPE, 'rb') as pipe:
                while True:
                    try:
                        # Read available data
                        chunk = pipe.read(4096)
                        if not chunk:
                            time.sleep(0.1)
                            continue

                        # Decode and add to buffer
                        try:
                            buffer += chunk.decode('utf-8', errors='ignore')
                        except:
                            continue

                        # Process all complete items in buffer
                        while "<item>" in buffer and "</item>" in buffer:
                            start_idx = buffer.find("<item>")
                            end_idx = buffer.find("</item>", start_idx)

                            if end_idx == -1:
                                break

                            end_idx += len("</item>")
                            item_xml = buffer[start_idx:end_idx]
                            buffer = buffer[end_idx:]

                            # Parse the item
                            result = self.metadata_parser.parse_item(item_xml)

                            # If we got an update, send to Snapcast
                            if result:
                                if result['type'] == 'metadata':
                                    # Full metadata update
                                    self.send_metadata_update(result['data'])

                                elif result['type'] == 'artwork':
                                    # Just artwork update - merge with current metadata
                                    if self.last_metadata:
                                        updated_metadata = self.last_metadata.copy()
                                        updated_metadata['artwork_url'] = result['data']
                                        self.send_metadata_update(updated_metadata)
                                    else:
                                        # No metadata yet, just store artwork
                                        self.send_metadata_update({'artwork_url': result['data']})

                        # Keep buffer from growing too large
                        # Need larger buffer to handle cover art data (can be 200KB+)
                        if len(buffer) > 500000:  # 500KB limit
                            # Find the last complete </item> tag
                            last_item_end = buffer.rfind("</item>")
                            if last_item_end != -1:
                                # Keep everything after the last complete item
                                buffer = buffer[last_item_end + len("</item>"):]
                                log(f"[Buffer] Trimmed buffer to {len(buffer)} bytes")
                            else:
                                # No complete items found - keep last 250KB to avoid cutting data
                                buffer = buffer[-250000:]
                                log("[Warning] Buffer overflow without complete items, kept last 250KB")

                    except Exception as e:
                        log(f"[Error] Error processing chunk: {e}")

        except Exception as e:
            log(f"[Error] Fatal error in metadata monitor: {e}")
            import traceback
            log(f"[Error] {traceback.format_exc()}")

    def run(self):
        """Main event loop"""
        log("[Init] AirPlay Control Script starting...")

        # Start metadata pipe monitor in background thread
        metadata_thread = threading.Thread(target=self.monitor_metadata_pipe, daemon=True)
        metadata_thread.start()

        # Send Plugin.Stream.Ready notification to tell Snapcast we're ready
        self.send_notification("Plugin.Stream.Ready", {})
        log("[Init] Sent Plugin.Stream.Ready notification")

        # Process commands from stdin (from Snapcast)
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
    # Parse command line arguments passed by Snapcast
    parser = argparse.ArgumentParser(description='AirPlay metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default='Airplay', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    log(f"[Init] Starting with args: stream={args.stream}, host={args.snapcast_host}, port={args.snapcast_port}")

    script = SnapcastControlScript(stream_id=args.stream)
    script.run()
