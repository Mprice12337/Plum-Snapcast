#!/usr/bin/env python3
"""
Snapcast Control Script for AirPlay Metadata
Reads metadata from shairport-sync pipe and provides it to Snapcast via JSON-RPC
"""

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

class MetadataParser:
    """Parse shairport-sync metadata format"""

    def __init__(self):
        self.current_metadata = {
            "title": None,
            "artist": None,
            "album": None,
            "artData": None
        }
        self.pending_cover_data = []

    def parse_item(self, item_xml: str) -> Optional[Dict[str, str]]:
        """Parse a complete XML item and return updated metadata if complete"""
        try:
            root = ET.fromstring(item_xml)

            # Get the code (metadata type)
            code_elem = root.find("code")
            if code_elem is None:
                return None

            code_hex = code_elem.text
            code = bytes.fromhex(code_hex).decode('ascii', errors='ignore')

            # Get the data
            data_elem = root.find("data")
            if data_elem is None:
                return None

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

            # Process based on code
            updated = False
            if code == "asar":  # Artist
                self.current_metadata["artist"] = decoded
                updated = True
                print(f"[DEBUG] Artist: {decoded}", file=sys.stderr, flush=True)
            elif code == "minm":  # Title/Track name
                self.current_metadata["title"] = decoded
                updated = True
                print(f"[DEBUG] Title: {decoded}", file=sys.stderr, flush=True)
            elif code == "asal":  # Album
                self.current_metadata["album"] = decoded
                updated = True
                print(f"[DEBUG] Album: {decoded}", file=sys.stderr, flush=True)
            elif code == "PICT":  # Cover art
                # Cover art is sent in chunks, collect them
                if encoding == "base64" and data_text:
                    self.pending_cover_data.append(data_text)
            elif code == "ssnc":
                # End of cover art or other control message
                if decoded == "PICT" and self.pending_cover_data:
                    self._save_cover_art()
                    updated = True
                    self.pending_cover_data = []

            if updated and self._is_complete():
                return self.current_metadata.copy()

        except ET.ParseError as e:
            print(f"XML Parse error: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"Error parsing metadata: {e}", file=sys.stderr, flush=True)

        return None

    def _save_cover_art(self):
        """Store cover art data as base64"""
        if not self.pending_cover_data:
            return

        try:
            # Combine all chunks into single base64 string
            cover_data_b64 = "".join(self.pending_cover_data)
            self.current_metadata["artData"] = cover_data_b64
            print(f"[DEBUG] Cover art collected ({len(cover_data_b64)} chars)", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"Error processing cover art: {e}", file=sys.stderr, flush=True)

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
            "artData": None
        }
        self.pending_cover_data = []


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self):
        self.metadata_parser = MetadataParser()
        self.last_metadata = {}

    def send_notification(self, method: str, params: Dict):
        """Send JSON-RPC notification to Snapcast via stdout"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        # Write to stdout for Snapcast to read
        print(json.dumps(notification), file=sys.stdout, flush=True)
        print(f"[DEBUG] Sent notification: {method}", file=sys.stderr, flush=True)

    def send_metadata_update(self, metadata: Dict):
        """Send Stream.OnProperties notification with metadata"""
        # Build properties dict
        properties = {}

        if metadata.get("title"):
            properties["title"] = metadata["title"]

        if metadata.get("artist"):
            properties["artist"] = metadata["artist"]

        if metadata.get("album"):
            properties["album"] = metadata["album"]

        if metadata.get("artData"):
            properties["artData"] = metadata["artData"]

        if properties:
            self.send_notification("Stream.OnProperties", {"properties": properties})
            print(f"[DEBUG] Metadata update: {list(properties.keys())}", file=sys.stderr, flush=True)

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")

            print(f"[DEBUG] Received command: {method}", file=sys.stderr, flush=True)

            # Respond to getProperties with current metadata
            if method == "Plugin.Stream.Player.GetProperties":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "properties": self.last_metadata if self.last_metadata else {}
                    }
                }
                print(json.dumps(response), file=sys.stdout, flush=True)

        except json.JSONDecodeError:
            print(f"[DEBUG] Invalid JSON: {line}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[DEBUG] Error handling command: {e}", file=sys.stderr, flush=True)

    def monitor_metadata_pipe(self):
        """Monitor shairport-sync metadata pipe in background thread"""
        print("[DEBUG] Starting metadata pipe monitor", file=sys.stderr, flush=True)

        # Wait for pipe to exist
        while not Path(METADATA_PIPE).exists():
            print(f"[DEBUG] Waiting for metadata pipe: {METADATA_PIPE}", file=sys.stderr, flush=True)
            time.sleep(1)

        print(f"[DEBUG] Metadata pipe found: {METADATA_PIPE}", file=sys.stderr, flush=True)

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
                                self.last_metadata = metadata
                                self.send_metadata_update(metadata)
                                self.metadata_parser.reset()

                        # Keep buffer from growing too large
                        if len(buffer) > 100000:
                            print("[DEBUG] Buffer overflow, keeping last 10KB", file=sys.stderr, flush=True)
                            buffer = buffer[-10000:]

                    except Exception as e:
                        print(f"[DEBUG] Error processing chunk: {e}", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[DEBUG] Fatal error in metadata monitor: {e}", file=sys.stderr, flush=True)

    def run(self):
        """Main event loop"""
        print("[DEBUG] AirPlay Control Script starting...", file=sys.stderr, flush=True)

        # Start metadata pipe monitor in background thread
        metadata_thread = threading.Thread(target=self.monitor_metadata_pipe, daemon=True)
        metadata_thread.start()

        # Process commands from stdin (from Snapcast)
        print("[DEBUG] Listening for commands on stdin...", file=sys.stderr, flush=True)
        try:
            for line in sys.stdin:
                line = line.strip()
                if line:
                    self.handle_command(line)
        except KeyboardInterrupt:
            print("[DEBUG] Shutting down...", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[DEBUG] Fatal error: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    script = SnapcastControlScript()
    script.run()
