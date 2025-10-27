#!/usr/bin/env python3
"""
AirPlay Metadata Processor for Snapcast
Reads metadata from shairport-sync pipe and updates Snapcast stream properties
"""

import base64
import json
import socket
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

# Configuration
METADATA_PIPE = "/tmp/shairport-sync-metadata"
SNAPCAST_HOST = "localhost"
SNAPCAST_PORT = 1705
STREAM_NAME = "AirPlay"  # Should match AIRPLAY_SOURCE_NAME from environment
COVER_ART_DIR = "/tmp/shairport-sync/.cache/coverart"

class SnapcastClient:
    """Simple Snapcast JSON-RPC client"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.request_id = 0

    def _send_request(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Send JSON-RPC request to Snapcast"""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self.request_id
        }
        if params:
            request["params"] = params

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.host, self.port))
            sock.sendall((json.dumps(request) + "\r\n").encode())

            response_data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\r\n" in response_data:
                    break

            sock.close()

            response_str = response_data.decode().strip()
            if response_str:
                return json.loads(response_str)
        except Exception as e:
            print(f"Error communicating with Snapcast: {e}", file=sys.stderr)
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

    def parse_line(self, line: str) -> Optional[Dict[str, str]]:
        """Parse a metadata line and return updated metadata if complete"""
        line = line.strip()
        if not line:
            return None

        try:
            # Shairport-sync metadata format: <item><type>73736e63</type><code>70696374</code><length>12345</length><data encoding="base64">...</data></item>
            root = ET.fromstring(line)

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
            data_text = data_elem.text or ""

            # Decode based on encoding
            if encoding == "base64":
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
            elif code == "minm":  # Title/Track name
                self.current_metadata["title"] = decoded
                updated = True
            elif code == "asal":  # Album
                self.current_metadata["album"] = decoded
                updated = True
            elif code == "PICT":  # Cover art
                # Cover art is sent in chunks, collect them
                if encoding == "base64":
                    self.pending_cover_data.append(data_text)
            elif code == "ssnc" and decoded == "PICT":
                # End of cover art, save it
                if self.pending_cover_data:
                    self._save_cover_art()
                    updated = True
                self.pending_cover_data = []

            if updated and self._is_complete():
                return self.current_metadata.copy()

        except ET.ParseError:
            # Not valid XML, might be a plain text line
            pass
        except Exception as e:
            print(f"Error parsing metadata: {e}", file=sys.stderr)

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
            print(f"Saved cover art to {cover_path}")

        except Exception as e:
            print(f"Error saving cover art: {e}", file=sys.stderr)

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
        # For cover art, we'll store the path - the frontend can fetch it
        properties_to_set["artUrl"] = f"file://{metadata['cover_art_path']}"

    # Set all properties
    for key, value in properties_to_set.items():
        success = client.set_stream_property(stream_id, key, value)
        if success:
            print(f"Updated {key}: {value}")
        else:
            print(f"Failed to update {key}", file=sys.stderr)

def main():
    """Main processing loop"""
    print("Starting AirPlay metadata processor...")

    # Wait for pipe to exist
    while not Path(METADATA_PIPE).exists():
        print(f"Waiting for metadata pipe: {METADATA_PIPE}")
        time.sleep(1)

    print(f"Metadata pipe found: {METADATA_PIPE}")

    # Initialize clients
    snapcast = SnapcastClient(SNAPCAST_HOST, SNAPCAST_PORT)
    parser = MetadataParser()

    # Find the AirPlay stream
    stream_id = None
    for attempt in range(10):
        stream_id = snapcast.find_stream_by_name(STREAM_NAME)
        if stream_id:
            print(f"Found AirPlay stream with ID: {stream_id}")
            break
        print(f"Waiting for AirPlay stream... (attempt {attempt + 1}/10)")
        time.sleep(2)

    if not stream_id:
        print(f"Warning: Could not find stream named '{STREAM_NAME}'. Metadata updates may fail.", file=sys.stderr)
        stream_id = "0"  # Try with default stream ID

    # Process metadata from pipe
    print("Reading metadata from pipe...")
    try:
        with open(METADATA_PIPE, 'r') as pipe:
            while True:
                try:
                    line = pipe.readline()
                    if not line:
                        time.sleep(0.1)
                        continue

                    # Parse the line
                    metadata = parser.parse_line(line)

                    # If we got complete metadata, update Snapcast
                    if metadata:
                        print(f"\nNew metadata received:")
                        print(f"  Title: {metadata.get('title', 'N/A')}")
                        print(f"  Artist: {metadata.get('artist', 'N/A')}")
                        print(f"  Album: {metadata.get('album', 'N/A')}")
                        print(f"  Cover: {metadata.get('cover_art_path', 'N/A')}")

                        update_snapcast_metadata(snapcast, stream_id, metadata)

                        # Reset for next track
                        parser.reset()

                except Exception as e:
                    print(f"Error processing line: {e}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()