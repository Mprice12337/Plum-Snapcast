#!/usr/bin/env python3
"""
Snapcast Control Script for AirPlay Metadata
Reads metadata from shairport-sync pipe and provides it to Snapcast via JSON-RPC
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
COVER_ART_DIR = "/tmp/shairport-sync/.cache/coverart"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
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
    """Parse shairport-sync metadata format"""

    def __init__(self):
        self.current_metadata = {
            "title": None,
            "artist": None,
            "album": None,
            "artUrl": None
        }
        self.pending_cover_data = []

    def parse_item(self, item_xml: str) -> Optional[Dict[str, str]]:
        """Parse a complete XML item and return updated metadata if complete"""
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
                        decoded = data_text
                else:
                    decoded = data_text

            # Process based on type and code
            updated = False
            if item_type == "core" and code == "asar":  # Artist
                self.current_metadata["artist"] = decoded
                updated = True
                log(f"[DEBUG] Artist: {decoded}")
            elif item_type == "core" and code == "minm":  # Title/Track name
                self.current_metadata["title"] = decoded
                updated = True
                log(f"[DEBUG] Title: {decoded}")
            elif item_type == "core" and code == "asal":  # Album
                self.current_metadata["album"] = decoded
                updated = True
                log(f"[DEBUG] Album: {decoded}")
            elif item_type == "ssnc":  # Control messages and PICT data
                # Check the code for what type of message
                log(f"[DEBUG] Got ssnc message, code: '{code}', has_data: {len(data_text) > 0}")
                if code == "PICT":
                    if encoding == "base64" and data_text:
                        # This is a PICT data chunk
                        self.pending_cover_data.append(data_text)
                        log(f"[DEBUG] Collected PICT chunk ({len(data_text)} chars), total chunks: {len(self.pending_cover_data)}")
                    else:
                        # This is the PICT end signal (no data)
                        if self.pending_cover_data:
                            log(f"[DEBUG] PICT end signal with {len(self.pending_cover_data)} chunks")
                            self._save_cover_art()
                            self.pending_cover_data = []
                            # Cover art is complete - return it even if we already sent basic metadata
                            if self.current_metadata.get("artUrl"):
                                log(f"[DEBUG] Cover art complete, sending update")
                                return self.current_metadata.copy()
                        else:
                            log(f"[DEBUG] PICT end signal but no chunks collected")

            if updated and self._is_complete():
                return self.current_metadata.copy()

        except ET.ParseError as e:
            log(f"XML Parse error: {e}")
        except Exception as e:
            log(f"Error parsing metadata: {e}")

        return None

    def _save_cover_art(self):
        """Save cover art to file and store HTTP URL"""
        if not self.pending_cover_data:
            return

        try:
            # Combine all chunks and decode
            cover_data_b64 = "".join(self.pending_cover_data)
            cover_data = base64.b64decode(cover_data_b64)

            # Use a hash of the data as filename to avoid duplicates
            import hashlib
            cover_hash = hashlib.md5(cover_data).hexdigest()
            filename = f"{cover_hash}.jpg"

            # Save to Snapcast web root so it's accessible via HTTP
            web_cover_dir = Path(SNAPCAST_WEB_ROOT) / "coverart"
            web_cover_dir.mkdir(parents=True, exist_ok=True)
            web_cover_path = web_cover_dir / filename

            with open(web_cover_path, "wb") as f:
                f.write(cover_data)

            # Make sure the file is readable by the web server
            import os
            os.chmod(web_cover_path, 0o644)

            # Also save to cache directory for backup
            cover_dir = Path(COVER_ART_DIR)
            cover_dir.mkdir(parents=True, exist_ok=True)
            cache_path = cover_dir / filename
            with open(cache_path, "wb") as f:
                f.write(cover_data)

            # Store HTTP URL that's accessible from browser
            # Using relative path so it works regardless of hostname
            self.current_metadata["artUrl"] = f"/coverart/{filename}"
            log(f"[DEBUG] Cover art saved to {web_cover_path} ({len(cover_data)} bytes)")
            log(f"[DEBUG] Cover art URL: /coverart/{filename}")

        except Exception as e:
            log(f"Error processing cover art: {e}")

    def _is_complete(self) -> bool:
        """Check if we have enough metadata to update"""
        return (self.current_metadata["title"] is not None and
                self.current_metadata["artist"] is not None)

    def reset(self):
        """Reset current metadata"""
        self.current_metadata = {
            "title": None,
            "artist": None,
            "album": None,
            "artUrl": None
        }
        self.pending_cover_data = []


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.metadata_parser = MetadataParser()
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
            artwork_file = Path(SNAPCAST_WEB_ROOT) / "airplay-artwork.json"
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

            # Also add artUrl as a top-level property (not just in metadata)
            # since Snapcast might filter metadata fields but preserve top-level properties
            if metadata.get("artUrl"):
                properties["artUrl"] = metadata["artUrl"]

            # Send Plugin.Stream.Player.Properties
            self.send_notification("Plugin.Stream.Player.Properties", properties)
            log(f"[DEBUG] Sent metadata update: {list(meta_obj.keys())}")
            if metadata.get("artUrl"):
                log(f"[DEBUG] Also sent top-level artUrl: {metadata['artUrl']}")

        # Since Snapcast filters out artUrl, write it to a JSON file
        # that the frontend can fetch via HTTP
        if metadata.get("artUrl"):
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
                        # Use MPRIS standard field name for artwork
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

    def monitor_metadata_pipe(self):
        """Monitor shairport-sync metadata pipe in background thread"""
        log("[DEBUG] Starting metadata pipe monitor")

        # Wait for pipe to exist
        while not Path(METADATA_PIPE).exists():
            log(f"[DEBUG] Waiting for metadata pipe: {METADATA_PIPE}")
            time.sleep(1)

        log(f"[DEBUG] Metadata pipe found: {METADATA_PIPE}")

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
                            metadata = self.metadata_parser.parse_item(item_xml)

                            # If we got complete metadata, send update
                            if metadata:
                                # Check if this is a new track (title or artist changed)
                                is_new_track = (
                                    not self.last_metadata or
                                    self.last_metadata.get("title") != metadata.get("title") or
                                    self.last_metadata.get("artist") != metadata.get("artist")
                                )

                                if is_new_track:
                                    log(f"[DEBUG] New track: {metadata.get('title')} - {metadata.get('artist')}")

                                self.last_metadata = metadata
                                self.send_metadata_update(metadata)

                                # Only reset parser after we've processed cover art
                                # Don't reset on new track - cover art for previous track may still be arriving
                                if metadata.get("artUrl"):
                                    log(f"[DEBUG] Track complete with cover art, resetting parser")
                                    self.metadata_parser.reset()
                                else:
                                    # Don't reset - keep collecting (cover art may still be coming)
                                    log(f"[DEBUG] Keeping parser state to collect cover art")

                        # Keep buffer from growing too large (but allow for large cover art ~200KB)
                        # Look for the last complete item boundary and discard everything before it
                        if len(buffer) > 500000:  # Increased from 100KB to 500KB for cover art
                            last_item_end = buffer.rfind("</item>")
                            if last_item_end != -1:
                                buffer = buffer[last_item_end + len("</item>"):]
                                log(f"[DEBUG] Buffer trimmed to {len(buffer)} chars")
                            else:
                                # No complete items, just keep enough for cover art
                                buffer = buffer[-250000:]
                                log("[DEBUG] Buffer overflow, kept last 250KB")

                    except Exception as e:
                        log(f"[DEBUG] Error processing chunk: {e}")

        except Exception as e:
            log(f"[DEBUG] Fatal error in metadata monitor: {e}")

    def run(self):
        """Main event loop"""
        log("[DEBUG] AirPlay Control Script starting...")

        # Start metadata pipe monitor in background thread
        metadata_thread = threading.Thread(target=self.monitor_metadata_pipe, daemon=True)
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
    parser = argparse.ArgumentParser(description='AirPlay metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default='Airplay', help='Stream ID')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    log(f"[DEBUG] Starting with args: stream={args.stream}, host={args.snapcast_host}, port={args.snapcast_port}")

    script = SnapcastControlScript(stream_id=args.stream)
    script.run()
