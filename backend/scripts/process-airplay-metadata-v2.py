#!/usr/bin/env python3
"""
AirPlay Metadata Processor for Snapcast
Reads metadata from shairport-sync pipe and updates Snapcast stream properties
"""

import base64
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

# Configuration
METADATA_PIPE = "/tmp/shairport-sync-metadata"
SNAPCAST_HOST = "localhost"
SNAPCAST_PORT = 1780  # HTTP API port
STREAM_NAME = "Airplay"  # Should match AIRPLAY_SOURCE_NAME from environment
COVER_ART_DIR = "/tmp/shairport-sync/.cache/coverart"

class SnapcastClient:
    """Simple Snapcast JSON-RPC client"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.request_id = 0

    def _send_request(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Send JSON-RPC request to Snapcast via HTTP API"""
        import urllib.request
        import urllib.error

        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self.request_id
        }
        if params:
            request["params"] = params

        try:
            url = f"http://{self.host}:{self.port}/jsonrpc"
            data = json.dumps(request).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

            with urllib.request.urlopen(req, timeout=5) as response:
                response_data = response.read().decode('utf-8')
                if response_data:
                    return json.loads(response_data)
        except urllib.error.URLError as e:
            print(f"Error communicating with Snapcast HTTP API: {e}", file=sys.stderr, flush=True)
            return None
        except Exception as e:
            print(f"Error communicating with Snapcast: {e}", file=sys.stderr, flush=True)
            return None

    def get_status(self) -> Optional[Dict]:
        """Get server status"""
        response = self._send_request("Server.GetStatus")
        return response.get("result") if response else None

    def set_stream_property(self, stream_id: str, property_name: str, value: str) -> bool:
        """Set a stream property"""
        params = {
            "id": stream_id,
            "property": property_name,
            "value": value
        }
        print(f"  [API] Calling Stream.SetProperty with: {params}", flush=True)
        response = self._send_request("Stream.SetProperty", params)
        print(f"  [API] Response: {response}", flush=True)
        return response is not None and "result" in response

    def find_stream_by_name(self, name: str) -> Optional[str]:
        """Find stream ID by name"""
        status = self.get_status()
        if not status or "server" not in status:
            return None

        for stream in status["server"].get("streams", []):
            stream_name = stream.get("uri", {}).get("query", {}).get("name", "")
            if stream_name == name:
                return stream["id"]
        return None

class MetadataParser:
    """Parse shairport-sync metadata format"""

    def __init__(self):
        self.current_metadata = {
            "title": None,
            "artist": None,
            "album": None,
            "cover_art_data": None
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
                print(f"  [DEBUG] Set artist: '{decoded}'", flush=True)
            elif code == "minm":  # Title/Track name
                self.current_metadata["title"] = decoded
                updated = True
                print(f"  [DEBUG] Set title: '{decoded}'", flush=True)
            elif code == "asal":  # Album
                self.current_metadata["album"] = decoded
                updated = True
                print(f"  [DEBUG] Set album: '{decoded}'", flush=True)
            elif code == "PICT":  # Cover art
                # Cover art is sent in chunks, collect them
                if encoding == "base64" and data_text:
                    self.pending_cover_data.append(data_text)
                    print(f"  [DEBUG] Collected cover art chunk ({len(data_text)} chars)", flush=True)
            elif code == "ssnc":
                # End of cover art or other control message
                if decoded == "PICT" and self.pending_cover_data:
                    self._save_cover_art()
                    updated = True
                    self.pending_cover_data = []
                    print(f"  [DEBUG] Saved cover art", flush=True)

            if updated and self._is_complete():
                print(f"  [DEBUG] Metadata complete! Returning: {self.current_metadata}", flush=True)
                return self.current_metadata.copy()

        except ET.ParseError as e:
            print(f"XML Parse error: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"Error parsing metadata: {e}", file=sys.stderr, flush=True)

        return None

    def _save_cover_art(self):
        """Store cover art data as base64 for Snapcast"""
        if not self.pending_cover_data:
            return

        try:
            # Combine all chunks into single base64 string
            cover_data_b64 = "".join(self.pending_cover_data)

            # Store as base64 - Snapcast will decode, cache, and serve it
            self.current_metadata["cover_art_data"] = cover_data_b64

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
            "cover_art_data": None
        }
        self.pending_cover_data = []

def update_snapcast_metadata(client: SnapcastClient, stream_id: str, metadata: Dict[str, str]):
    """Update Snapcast stream properties with metadata"""
    # Debug: show what we received (but truncate cover art for readability)
    debug_metadata = metadata.copy()
    if "cover_art_data" in debug_metadata and debug_metadata["cover_art_data"]:
        debug_metadata["cover_art_data"] = f"<base64 data: {len(debug_metadata['cover_art_data'])} chars>"
    print(f"\n📡 Received metadata: {debug_metadata}", flush=True)

    properties_to_set = {}

    if metadata.get("title"):
        properties_to_set["title"] = metadata["title"]

    if metadata.get("artist"):
        properties_to_set["artist"] = metadata["artist"]

    if metadata.get("album"):
        properties_to_set["album"] = metadata["album"]

    # Use artData with base64 encoding - Snapcast will cache and serve via HTTP
    if metadata.get("cover_art_data"):
        properties_to_set["artData"] = metadata["cover_art_data"]

    print(f"📡 Updating Snapcast with {len(properties_to_set)} properties:", flush=True)

    if not properties_to_set:
        print("  ⚠️  No properties to set (all values were empty/None)", flush=True)
        return

    # Set all properties
    for key, value in properties_to_set.items():
        # Truncate artData in log output for readability
        display_value = f"<base64 image: {len(value)} chars>" if key == "artData" else value
        success = client.set_stream_property(stream_id, key, value)
        if success:
            print(f"  ✓ {key}: {display_value}", flush=True)
        else:
            print(f"  ✗ Failed to update {key}", file=sys.stderr, flush=True)

def main():
    """Main processing loop"""
    print("Starting AirPlay metadata processor...", flush=True)

    # Wait for pipe to exist
    while not Path(METADATA_PIPE).exists():
        print(f"Waiting for metadata pipe: {METADATA_PIPE}", flush=True)
        time.sleep(1)

    print(f"Metadata pipe found: {METADATA_PIPE}", flush=True)

    # Initialize clients
    snapcast = SnapcastClient(SNAPCAST_HOST, SNAPCAST_PORT)
    parser = MetadataParser()

    # Find the AirPlay stream
    stream_id = None
    for attempt in range(10):
        stream_id = snapcast.find_stream_by_name(STREAM_NAME)
        if stream_id:
            print(f"Found AirPlay stream with ID: {stream_id}", flush=True)

            # Debug: show current stream state
            status = snapcast.get_status()
            if status:
                for stream in status.get("server", {}).get("streams", []):
                    if stream["id"] == stream_id:
                        print(f"[DEBUG] Current stream properties: {stream.get('properties', {})}", flush=True)
                        print(f"[DEBUG] Stream URI: {stream.get('uri', {})}", flush=True)
            break
        print(f"Waiting for AirPlay stream... (attempt {attempt + 1}/10)", flush=True)
        time.sleep(2)

    if not stream_id:
        print(f"Warning: Could not find stream named '{STREAM_NAME}'. Metadata updates may fail.", file=sys.stderr, flush=True)
        stream_id = "Airplay"  # Try with default stream ID

    # Process metadata from pipe
    print("Reading metadata from pipe...", flush=True)

    buffer = ""
    try:
        # Open in binary mode to avoid encoding issues
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
                        metadata = parser.parse_item(item_xml)

                        # If we got complete metadata, update Snapcast
                        if metadata:
                            update_snapcast_metadata(snapcast, stream_id, metadata)
                            parser.reset()

                    # Keep buffer from growing too large
                    if len(buffer) > 100000:
                        print("Warning: Buffer overflow, keeping last 10KB", file=sys.stderr, flush=True)
                        buffer = buffer[-10000:]

                except Exception as e:
                    print(f"Error processing chunk: {e}", file=sys.stderr, flush=True)

    except KeyboardInterrupt:
        print("\nShutting down...", flush=True)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()