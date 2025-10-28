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
        response = self._send_request("Stream.SetProperty", params)
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
            "cover_art_path": None
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
                print(f"  Artist: {decoded}", flush=True)
            elif code == "minm":  # Title/Track name
                self.current_metadata["title"] = decoded
                updated = True
                print(f"  Title: {decoded}", flush=True)
            elif code == "asal":  # Album
                self.current_metadata["album"] = decoded
                updated = True
                print(f"  Album: {decoded}", flush=True)
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
        """Save collected cover art data to a file"""
        if not self.pending_cover_data:
            return

        try:
            # Combine all chunks
            cover_data_b64 = "".join(self.pending_cover_data)
            cover_data = base64.b64decode(cover_data_b64)

            # Save to file
            cover_dir = Path(COVER_ART_DIR)
            cover_dir.mkdir(parents=True, exist_ok=True)

            cover_path = cover_dir / "current.jpg"
            with open(cover_path, "wb") as f:
                f.write(cover_data)

            self.current_metadata["cover_art_path"] = str(cover_path)
            print(f"  Cover art saved: {cover_path}", flush=True)

        except Exception as e:
            print(f"Error saving cover art: {e}", file=sys.stderr, flush=True)

    def _is_complete(self) -> bool:
        """Check if we have enough metadata to update"""
        return (self.current_metadata["title"] is not None or
                self.current_metadata["artist"] is not None)

    def reset(self):
        """Reset current metadata"""
        self.current_metadata = {
            "title": None,
            "artist": None,
            "album": None,
            "cover_art_path": None
        }
        self.pending_cover_data = []

def update_snapcast_metadata(client: SnapcastClient, stream_id: str, metadata: Dict[str, str]):
    """Update Snapcast stream properties with metadata"""
    properties_to_set = {}

    if metadata.get("title"):
        properties_to_set["title"] = metadata["title"]

    if metadata.get("artist"):
        properties_to_set["artist"] = metadata["artist"]

    if metadata.get("album"):
        properties_to_set["album"] = metadata["album"]

    if metadata.get("cover_art_path"):
        properties_to_set["artUrl"] = f"file://{metadata['cover_art_path']}"

    # Set all properties
    for key, value in properties_to_set.items():
        success = client.set_stream_property(stream_id, key, value)
        if success:
            print(f"✓ Updated {key}: {value}", flush=True)
        else:
            print(f"✗ Failed to update {key}", file=sys.stderr, flush=True)

def read_complete_item(pipe) -> Optional[str]:
    """Read from pipe until we get a complete <item>...</item>"""
    buffer = ""
    while True:
        chunk = pipe.read(1024)
        if not chunk:
            time.sleep(0.1)
            continue

        buffer += chunk

        # Look for complete items
        while "<item>" in buffer and "</item>" in buffer:
            start = buffer.find("<item>")
            end = buffer.find("</item>") + len("</item>")

            if start != -1 and end > start:
                item = buffer[start:end]
                buffer = buffer[end:]
                return item

        # Keep buffer from growing too large
        if len(buffer) > 100000:
            print("Warning: Buffer overflow, clearing", file=sys.stderr, flush=True)
            buffer = buffer[-10000:]

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
            break
        print(f"Waiting for AirPlay stream... (attempt {attempt + 1}/10)", flush=True)
        time.sleep(2)

    if not stream_id:
        print(f"Warning: Could not find stream named '{STREAM_NAME}'. Metadata updates may fail.", file=sys.stderr, flush=True)
        stream_id = "Airplay"  # Try with default stream ID

    # Process metadata from pipe
    print("Reading metadata from pipe...", flush=True)
    try:
        with open(METADATA_PIPE, 'r') as pipe:
            while True:
                try:
                    # Read a complete XML item
                    item_xml = read_complete_item(pipe)

                    if item_xml:
                        # Parse the item
                        metadata = parser.parse_item(item_xml)

                        # If we got complete metadata, update Snapcast
                        if metadata:
                            print(f"\n🎵 New metadata received:", flush=True)
                            update_snapcast_metadata(snapcast, stream_id, metadata)
                            parser.reset()

                except Exception as e:
                    print(f"Error processing item: {e}", file=sys.stderr, flush=True)

    except KeyboardInterrupt:
        print("\nShutting down...", flush=True)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()