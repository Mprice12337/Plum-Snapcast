#!/usr/bin/env python3
"""
AirPlay Metadata Debug Server
Provides HTTP endpoints to view current AirPlay metadata and album artwork
Endpoints:
  - http://localhost:8080/metadata - Plain text metadata display
  - http://localhost:8080/artwork - Current album artwork image
"""

import base64
import json
import threading
import time
import xml.etree.ElementTree as ET
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Optional
import sys

# Configuration
METADATA_PIPE = "/tmp/shairport-sync-metadata"
HTTP_PORT = 8080
HTTP_HOST = "0.0.0.0"  # Listen on all interfaces

class MetadataStore:
    """Thread-safe storage for current metadata"""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "title": "No metadata yet",
            "artist": "Waiting for AirPlay connection...",
            "album": "N/A",
            "cover_art_data": None,  # Base64 encoded image data
            "cover_art_format": None,  # "jpeg" or "png"
            "last_updated": None
        }

    def update(self, **kwargs):
        """Update metadata fields"""
        with self.lock:
            self.data.update(kwargs)
            self.data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def get_all(self) -> Dict:
        """Get all metadata (returns a copy)"""
        with self.lock:
            return self.data.copy()

    def get_artwork(self) -> Optional[tuple]:
        """Get artwork data and format"""
        with self.lock:
            if self.data["cover_art_data"]:
                return (self.data["cover_art_data"], self.data["cover_art_format"])
            return None

class MetadataParser:
    """Parse shairport-sync metadata format"""

    def __init__(self, store: MetadataStore):
        self.store = store
        self.current = {
            "title": None,
            "artist": None,
            "album": None
        }
        self.pending_cover_data = []

    def parse_item(self, item_xml: str):
        """Parse a complete XML item and update store"""
        try:
            root = ET.fromstring(item_xml)

            # Get the code (metadata type)
            code_elem = root.find("code")
            if code_elem is None:
                return

            code_hex = code_elem.text
            code = bytes.fromhex(code_hex).decode('ascii', errors='ignore')

            # Get the data
            data_elem = root.find("data")
            if data_elem is None:
                return

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
            if code == "asar":  # Artist
                self.current["artist"] = decoded
                self.store.update(artist=decoded)
                print(f"[Metadata] Artist: {decoded}", flush=True)

            elif code == "minm":  # Title/Track name
                self.current["title"] = decoded
                self.store.update(title=decoded)
                print(f"[Metadata] Title: {decoded}", flush=True)

            elif code == "asal":  # Album
                self.current["album"] = decoded
                self.store.update(album=decoded)
                print(f"[Metadata] Album: {decoded}", flush=True)

            elif code == "PICT":  # Cover art chunk
                if encoding == "base64" and data_text:
                    self.pending_cover_data.append(data_text)
                    print(f"[Metadata] Collected cover art chunk ({len(data_text)} chars, total chunks: {len(self.pending_cover_data)})", flush=True)

            elif code == "ssnc":
                # Control messages - check for end of cover art
                if decoded == "PICT" and self.pending_cover_data:
                    self._process_cover_art()
                elif decoded == "pbeg":
                    print("[Metadata] Playback started", flush=True)
                elif decoded == "pend":
                    print("[Metadata] Playback ended", flush=True)
                    self._reset()

        except ET.ParseError as e:
            print(f"[Error] XML Parse error: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[Error] Error parsing metadata: {e}", file=sys.stderr, flush=True)

    def _process_cover_art(self):
        """Process collected cover art chunks"""
        try:
            # Combine all chunks
            cover_data_b64 = "".join(self.pending_cover_data)

            # Decode to check format
            image_data = base64.b64decode(cover_data_b64)

            # Detect image format from magic bytes
            image_format = "jpeg"  # Default
            if image_data[:4] == b'\x89PNG':
                image_format = "png"
            elif image_data[:3] == b'\xff\xd8\xff':
                image_format = "jpeg"

            # Store the artwork
            self.store.update(
                cover_art_data=cover_data_b64,
                cover_art_format=image_format
            )

            print(f"[Metadata] Saved cover art ({len(image_data)} bytes, format: {image_format})", flush=True)

        except Exception as e:
            print(f"[Error] Error processing cover art: {e}", file=sys.stderr, flush=True)
        finally:
            self.pending_cover_data = []

    def _reset(self):
        """Reset current metadata on playback end"""
        self.current = {
            "title": None,
            "artist": None,
            "album": None
        }
        self.pending_cover_data = []

class MetadataHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for metadata endpoints"""

    # Class variable to hold the metadata store
    metadata_store: MetadataStore = None

    def log_message(self, format, *args):
        """Custom logging"""
        print(f"[HTTP] {self.address_string()} - {format % args}", flush=True)

    def do_GET(self):
        """Handle GET requests"""

        if self.path == "/metadata":
            self._serve_metadata()
        elif self.path == "/artwork":
            self._serve_artwork()
        elif self.path == "/" or self.path == "/status":
            self._serve_status()
        else:
            self.send_error(404, "Not Found")

    def _serve_metadata(self):
        """Serve metadata as plain text"""
        metadata = self.metadata_store.get_all()

        text = f"""AirPlay Metadata Debug
{'=' * 50}

Title:   {metadata['title']}
Artist:  {metadata['artist']}
Album:   {metadata['album']}

Artwork: {'Available' if metadata['cover_art_data'] else 'Not available'}
Format:  {metadata['cover_art_format'] or 'N/A'}

Last Updated: {metadata['last_updated'] or 'Never'}

{'=' * 50}
Endpoints:
  /metadata - This page
  /artwork  - Album artwork image
  /status   - JSON status
"""

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(text.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(text.encode('utf-8'))

    def _serve_artwork(self):
        """Serve album artwork as image"""
        artwork = self.metadata_store.get_artwork()

        if not artwork:
            # Send placeholder response
            message = "No artwork available. Play something via AirPlay first."
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message.encode('utf-8'))
            return

        cover_data_b64, image_format = artwork

        try:
            # Decode base64 to binary image data
            image_data = base64.b64decode(cover_data_b64)

            # Determine MIME type
            mime_type = f"image/{image_format}"

            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(image_data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(image_data)

        except Exception as e:
            print(f"[Error] Error serving artwork: {e}", file=sys.stderr, flush=True)
            self.send_error(500, "Error decoding artwork")

    def _serve_status(self):
        """Serve status as JSON"""
        metadata = self.metadata_store.get_all()

        # Don't include full artwork data in JSON (it's huge)
        status = {
            "title": metadata["title"],
            "artist": metadata["artist"],
            "album": metadata["album"],
            "has_artwork": metadata["cover_art_data"] is not None,
            "artwork_format": metadata["cover_art_format"],
            "last_updated": metadata["last_updated"],
            "endpoints": {
                "/metadata": "Plain text metadata display",
                "/artwork": "Album artwork image",
                "/status": "This JSON status"
            }
        }

        json_data = json.dumps(status, indent=2)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(json_data)))
        self.end_headers()
        self.wfile.write(json_data.encode('utf-8'))

def metadata_reader_thread(store: MetadataStore):
    """Background thread to read metadata from pipe"""
    print(f"[Reader] Starting metadata reader thread...", flush=True)

    # Wait for pipe to exist
    while not Path(METADATA_PIPE).exists():
        print(f"[Reader] Waiting for metadata pipe: {METADATA_PIPE}", flush=True)
        time.sleep(2)

    print(f"[Reader] Metadata pipe found: {METADATA_PIPE}", flush=True)

    parser = MetadataParser(store)
    buffer = ""

    try:
        with open(METADATA_PIPE, 'rb') as pipe:
            print("[Reader] Metadata pipe opened, reading...", flush=True)
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
                        parser.parse_item(item_xml)

                    # Keep buffer from growing too large
                    if len(buffer) > 100000:
                        buffer = buffer[-10000:]

                except Exception as e:
                    print(f"[Error] Error processing chunk: {e}", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"[Error] Fatal error in reader thread: {e}", file=sys.stderr, flush=True)

def main():
    """Main entry point"""
    print("=" * 60, flush=True)
    print("AirPlay Metadata Debug Server", flush=True)
    print("=" * 60, flush=True)
    print(f"Starting HTTP server on {HTTP_HOST}:{HTTP_PORT}", flush=True)
    print(f"Endpoints:", flush=True)
    print(f"  http://localhost:{HTTP_PORT}/metadata - Text metadata", flush=True)
    print(f"  http://localhost:{HTTP_PORT}/artwork  - Album artwork", flush=True)
    print(f"  http://localhost:{HTTP_PORT}/status   - JSON status", flush=True)
    print("=" * 60, flush=True)

    # Create metadata store
    store = MetadataStore()

    # Set the store in the handler class
    MetadataHTTPHandler.metadata_store = store

    # Start metadata reader thread
    reader = threading.Thread(target=metadata_reader_thread, args=(store,), daemon=True)
    reader.start()

    # Start HTTP server
    try:
        server = HTTPServer((HTTP_HOST, HTTP_PORT), MetadataHTTPHandler)
        print(f"[HTTP] Server started successfully", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[HTTP] Shutting down...", flush=True)
    except Exception as e:
        print(f"[Error] Server error: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
