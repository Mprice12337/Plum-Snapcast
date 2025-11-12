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
import os
import threading
import time
import xml.etree.ElementTree as ET
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Optional
import sys

# Configuration
METADATA_PIPE = "/tmp/shairport-sync-metadata"
COVER_ART_CACHE_DIR = "/tmp/shairport-sync/.cache/coverart"
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
        self.last_loaded_cache_file = None  # Track which cache file we last loaded
        self.metadata_received_for_current_track = {
            "artist": False,
            "album": False
        }
        self.metadata_arrival_time = {
            "artist": None,
            "album": None
        }

    def parse_item(self, item_xml: str):
        """Parse a complete XML item and update store"""
        try:
            root = ET.fromstring(item_xml)

            # Get the type (core or ssnc)
            type_elem = root.find("type")
            if type_elem is None:
                return

            type_hex = type_elem.text
            item_type = bytes.fromhex(type_hex).decode('ascii', errors='ignore')

            # Get the code (metadata type)
            code_elem = root.find("code")
            if code_elem is None:
                return

            code_hex = code_elem.text
            code = bytes.fromhex(code_hex).decode('ascii', errors='ignore')

            # Get the data
            data_elem = root.find("data")
            if data_elem is None:
                # Some control messages have no data
                data_text = ""
                encoding = ""
                decoded = ""
            else:
                encoding = data_elem.get("encoding", "")
                data_text = (data_elem.text or "").strip()

                # Decode based on encoding (but NOT for PICT - that's binary image data)
                if encoding == "base64" and data_text and code != "PICT":
                    try:
                        decoded = base64.b64decode(data_text).decode('utf-8', errors='ignore')
                    except:
                        decoded = data_text
                else:
                    decoded = data_text

            # Debug: Log all ssnc messages to help diagnose issues
            if item_type == "ssnc":
                data_preview = f"{len(data_text)} chars" if code == "PICT" else (decoded[:50] if decoded else "no data")
                print(f"[Debug] ssnc message: code='{code}' data={data_preview}", flush=True)

            # Process based on type and code
            # Core metadata (from iTunes/Music app)
            if item_type == "core":
                if code == "asar":  # Artist
                    # Only update if non-empty
                    if decoded and decoded.strip():
                        self.current["artist"] = decoded
                        self.store.update(artist=decoded)
                        self.metadata_received_for_current_track["artist"] = True
                        self.metadata_arrival_time["artist"] = time.time()
                        print(f"[Metadata] Artist: {decoded} (flag set to True, time={self.metadata_arrival_time['artist']:.2f})", flush=True)
                    else:
                        print(f"[Metadata] Ignoring empty artist metadata", flush=True)

                elif code == "minm":  # Title/Track name
                    # If title changed, this is a new track
                    # BUT: Don't treat empty titles as real track changes
                    is_empty_title = not decoded or not decoded.strip()

                    if is_empty_title:
                        print(f"[Metadata] Received empty title metadata (ignoring completely)", flush=True)
                        # Don't process empty titles at all - they don't represent real data
                        return

                    # Only trigger new track detection for non-empty, changed titles
                    if self.current["title"] != decoded:
                        print(f"[Metadata] ========================================", flush=True)
                        print(f"[Metadata] NEW TRACK DETECTED", flush=True)
                        print(f"[Metadata] Previous title: '{self.current['title']}'", flush=True)
                        print(f"[Metadata] New title: '{decoded}'", flush=True)
                        print(f"[Metadata] Current artist flag: {self.metadata_received_for_current_track.get('artist')}", flush=True)
                        print(f"[Metadata] Current album flag: {self.metadata_received_for_current_track.get('album')}", flush=True)
                        print(f"[Metadata] Current artist value: '{self.current.get('artist')}'", flush=True)
                        print(f"[Metadata] Current album value: '{self.current.get('album')}'", flush=True)

                        # Check if we have fresh metadata (arrived within last 2 seconds from NOW)
                        # This handles metadata arriving BEFORE the title
                        current_time = time.time()
                        keep_artist = False
                        keep_album = False

                        # Check if artist arrived in the last 2 seconds
                        if self.metadata_received_for_current_track.get('artist'):
                            artist_arrival = self.metadata_arrival_time.get('artist')
                            if artist_arrival:
                                time_since_arrival = current_time - artist_arrival
                                if time_since_arrival < 2.0:
                                    keep_artist = True
                                    print(f"[Metadata] Keeping artist (arrived {time_since_arrival:.2f}s ago, fresh for new track)", flush=True)
                                else:
                                    print(f"[Metadata] Clearing artist (arrived {time_since_arrival:.2f}s ago, too old)", flush=True)

                        # Check if album arrived in the last 2 seconds
                        if self.metadata_received_for_current_track.get('album'):
                            album_arrival = self.metadata_arrival_time.get('album')
                            if album_arrival:
                                time_since_arrival = current_time - album_arrival
                                if time_since_arrival < 2.0:
                                    keep_album = True
                                    print(f"[Metadata] Keeping album (arrived {time_since_arrival:.2f}s ago, fresh for new track)", flush=True)
                                else:
                                    print(f"[Metadata] Clearing album (arrived {time_since_arrival:.2f}s ago, too old)", flush=True)

                        print(f"[Metadata] ========================================", flush=True)

                        # Reset flags for metadata we're NOT keeping
                        self.metadata_received_for_current_track = {
                            "artist": keep_artist,
                            "album": keep_album
                        }

                        # Clear old metadata only if we're not keeping it
                        if not keep_artist:
                            self.store.update(artist="")
                            self.metadata_arrival_time["artist"] = None
                        if not keep_album:
                            self.store.update(album="")
                            self.metadata_arrival_time["album"] = None

                        # Schedule a check to set "Unknown" if metadata doesn't arrive
                        self._schedule_metadata_fallback()

                    self.current["title"] = decoded
                    self.store.update(title=decoded)
                    print(f"[Metadata] Title: {decoded}", flush=True)
                    # When title changes, check for new artwork after a short delay
                    # This handles cases where artwork comes before metadata
                    self._schedule_artwork_check()

                elif code == "asal":  # Album
                    # Only update if non-empty
                    if decoded and decoded.strip():
                        self.current["album"] = decoded
                        self.store.update(album=decoded)
                        self.metadata_received_for_current_track["album"] = True
                        self.metadata_arrival_time["album"] = time.time()
                        print(f"[Metadata] Album: {decoded} (flag set to True, time={self.metadata_arrival_time['album']:.2f})", flush=True)
                    else:
                        print(f"[Metadata] Ignoring empty album metadata", flush=True)

            # Shairport-sync control messages
            elif item_type == "ssnc":
                if code == "PICT":  # Cover art data
                    if encoding == "base64" and data_text:
                        # Store the base64 data directly (don't decode yet)
                        self.pending_cover_data.append(data_text)
                        print(f"[Metadata] Received cover art data ({len(data_text)} chars, total chunks: {len(self.pending_cover_data)})", flush=True)

                elif code == "pcen":  # Picture end marker
                    print(f"[Metadata] Picture end marker received", flush=True)
                    if self.pending_cover_data:
                        self._process_cover_art()
                    else:
                        print(f"[Info] Picture end received but no data in pipe (checking cache instead)", flush=True)
                        # When cover art caching is enabled, shairport-sync doesn't send
                        # the full image through the pipe - we need to read from cache
                        self._load_cover_art_from_cache()

                elif code == "pcst":  # Picture start marker
                    print(f"[Metadata] Picture start marker received", flush=True)
                    # Clear any pending data from previous transmission
                    self.pending_cover_data = []

                elif code == "pbeg":  # Playback begin
                    print("[Metadata] Playback started", flush=True)
                    # Reset metadata at playback start - new session
                    self.store.update(
                        title="Waiting for metadata...",
                        artist="Connecting...",
                        album="N/A"
                    )

                elif code == "pend":  # Playback end
                    print("[Metadata] Playback ended", flush=True)
                    self._reset()

        except ET.ParseError as e:
            print(f"[Error] XML Parse error: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[Error] Error parsing metadata: {e}", file=sys.stderr, flush=True)

    def _process_cover_art(self):
        """Process collected cover art chunks"""
        try:
            print(f"[Metadata] Processing {len(self.pending_cover_data)} cover art chunk(s)", flush=True)

            # Combine all chunks
            cover_data_b64 = "".join(self.pending_cover_data)
            print(f"[Metadata] Total base64 length: {len(cover_data_b64)} chars", flush=True)

            # Decode to check format
            image_data = base64.b64decode(cover_data_b64)
            print(f"[Metadata] Decoded image size: {len(image_data)} bytes", flush=True)

            # Detect image format from magic bytes
            image_format = "jpeg"  # Default
            magic_bytes = image_data[:4] if len(image_data) >= 4 else b''
            print(f"[Metadata] Magic bytes: {magic_bytes.hex()}", flush=True)

            if image_data[:4] == b'\x89PNG':
                image_format = "png"
                print(f"[Metadata] Detected PNG format", flush=True)
            elif image_data[:3] == b'\xff\xd8\xff':
                image_format = "jpeg"
                print(f"[Metadata] Detected JPEG format", flush=True)
            else:
                print(f"[Warning] Unknown image format, magic bytes: {magic_bytes.hex()}", flush=True)

            # Store the artwork
            self.store.update(
                cover_art_data=cover_data_b64,
                cover_art_format=image_format
            )

            print(f"[Metadata] ✓ Successfully saved cover art ({len(image_data)} bytes, format: {image_format})", flush=True)

        except base64.binascii.Error as e:
            print(f"[Error] Base64 decode error: {e}", file=sys.stderr, flush=True)
            print(f"[Error] First 100 chars of data: {self.pending_cover_data[0][:100] if self.pending_cover_data else 'empty'}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[Error] Error processing cover art: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()
        finally:
            self.pending_cover_data = []

    def _load_cover_art_from_cache(self, force=False):
        """Load cover art from shairport-sync cache directory"""
        try:
            cache_dir = Path(COVER_ART_CACHE_DIR)
            if not cache_dir.exists():
                print(f"[Warning] Cache directory doesn't exist: {COVER_ART_CACHE_DIR}", flush=True)
                return

            # Find the most recent cover art file
            cover_files = list(cache_dir.glob("cover-*.jpg")) + list(cache_dir.glob("cover-*.png"))
            if not cover_files:
                print(f"[Warning] No cover art files found in cache", flush=True)
                return

            # Get the newest file
            newest_file = max(cover_files, key=lambda p: p.stat().st_mtime)

            # Skip if we already loaded this file (unless forced)
            if not force and self.last_loaded_cache_file == newest_file.name:
                print(f"[Metadata] Artwork already loaded from {newest_file.name}, skipping", flush=True)
                return

            print(f"[Metadata] Loading cover art from cache: {newest_file.name}", flush=True)

            # Read the image file
            with open(newest_file, 'rb') as f:
                image_data = f.read()

            # Encode to base64 for storage
            cover_data_b64 = base64.b64encode(image_data).decode('ascii')

            # Detect format from extension or magic bytes
            image_format = "jpeg"
            if newest_file.suffix.lower() == ".png" or image_data[:4] == b'\x89PNG':
                image_format = "png"
            elif image_data[:3] == b'\xff\xd8\xff':
                image_format = "jpeg"

            # Store the artwork
            self.store.update(
                cover_art_data=cover_data_b64,
                cover_art_format=image_format
            )

            # Remember which file we loaded
            self.last_loaded_cache_file = newest_file.name

            print(f"[Metadata] ✓ Successfully loaded cover art from cache ({len(image_data)} bytes, format: {image_format})", flush=True)

        except Exception as e:
            print(f"[Error] Error loading cover art from cache: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()

    def _schedule_artwork_check(self):
        """Schedule a delayed check for new artwork in cache"""
        def delayed_check():
            # Wait a bit for shairport-sync to cache the new artwork
            time.sleep(0.5)
            print(f"[Metadata] Checking for new artwork after title change...", flush=True)
            self._load_cover_art_from_cache()

        # Run in a background thread to not block metadata processing
        thread = threading.Thread(target=delayed_check, daemon=True)
        thread.start()

    def _schedule_metadata_fallback(self):
        """Schedule fallback to 'Unknown' for metadata that doesn't arrive"""
        def delayed_check():
            # Wait for metadata to arrive
            time.sleep(2.0)

            # Check if we received artist/album for the current track
            if not self.metadata_received_for_current_track.get("artist"):
                print(f"[Metadata] >>> FALLBACK: No artist received for current track '{self.current.get('title')}', using fallback", flush=True)
                self.store.update(artist="Unknown Artist")
            else:
                print(f"[Metadata] >>> CHECK: Artist flag is True, keeping: '{self.current.get('artist')}'", flush=True)

            if not self.metadata_received_for_current_track.get("album"):
                print(f"[Metadata] >>> FALLBACK: No album received for current track '{self.current.get('title')}', using fallback", flush=True)
                self.store.update(album="Unknown Album")
            else:
                print(f"[Metadata] >>> CHECK: Album flag is True, keeping: '{self.current.get('album')}'", flush=True)

        # Run in a background thread to not block metadata processing
        thread = threading.Thread(target=delayed_check, daemon=True)
        thread.start()

    def _reset(self):
        """Reset current metadata on playback end"""
        self.current = {
            "title": None,
            "artist": None,
            "album": None
        }
        self.pending_cover_data = []
        # Don't reset last_loaded_cache_file - we want to avoid reloading the same artwork

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
