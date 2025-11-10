#!/usr/bin/env python3
"""
Snapcast Control Script for AirPlay Metadata
Reads metadata from shairport-sync pipe and provides it to Snapcast via JSON-RPC
Supports initial metadata fetch, position tracking, and media controls via D-Bus
"""

import argparse
import base64
import json
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional, Any

# Configuration
METADATA_PIPE = "/tmp/shairport-sync-metadata"
COVER_ART_DIR = "/tmp/shairport-sync/.cache/coverart"
SNAPCAST_WEB_ROOT = "/usr/share/snapserver/snapweb"
LOG_FILE = "/tmp/airplay-control-script.log"
DBUS_SERVICE = "org.gnome.ShairportSync"
DBUS_OBJECT_PATH = "/org/gnome/ShairportSync"
DBUS_REMOTE_CONTROL_INTERFACE = "org.gnome.ShairportSync.RemoteControl"
DBUS_ADVANCED_REMOTE_CONTROL_INTERFACE = "org.gnome.ShairportSync.AdvancedRemoteControl"

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


class DBusInterface:
    """Interface to shairport-sync via D-Bus"""

    def __init__(self):
        self.bus = None
        self.remote_control = None
        self.advanced_remote_control = None
        self.is_playing = False
        self._initialize_dbus()

    def _initialize_dbus(self, max_retries=10, retry_delay=1):
        """Initialize D-Bus connection to shairport-sync with retry logic"""
        try:
            import dbus

            # Retry D-Bus connection - it might not be ready at startup
            for attempt in range(max_retries):
                try:
                    self.bus = dbus.SystemBus()
                    log(f"[DBUS] Connected to D-Bus system bus (attempt {attempt + 1})")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        log(f"[DBUS] D-Bus not ready yet (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                    else:
                        log(f"[DBUS] Failed to connect to D-Bus after {max_retries} attempts: {e}")
                        return

            # Get remote control interface with retry
            for attempt in range(max_retries):
                try:
                    proxy = self.bus.get_object(DBUS_SERVICE, DBUS_OBJECT_PATH)
                    self.remote_control = dbus.Interface(proxy, DBUS_REMOTE_CONTROL_INTERFACE)
                    log("[DBUS] Connected to RemoteControl interface")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        log(f"[DBUS] Waiting for shairport-sync RemoteControl (attempt {attempt + 1}/{max_retries})...")
                        time.sleep(retry_delay)
                    else:
                        log(f"[DBUS] RemoteControl interface not available after {max_retries} attempts: {e}")

            # Get advanced remote control interface for position tracking
            try:
                proxy = self.bus.get_object(DBUS_SERVICE, DBUS_OBJECT_PATH)
                self.advanced_remote_control = dbus.Interface(proxy, DBUS_ADVANCED_REMOTE_CONTROL_INTERFACE)
                log("[DBUS] Connected to AdvancedRemoteControl interface")
            except Exception as e:
                log(f"[DBUS] AdvancedRemoteControl interface not available: {e}")

        except ImportError:
            log("[DBUS] python-dbus not available, D-Bus features disabled")
        except Exception as e:
            log(f"[DBUS] Failed to initialize D-Bus: {e}")

    def get_current_metadata(self) -> Optional[Dict[str, Any]]:
        """Get current metadata from shairport-sync D-Bus interface"""
        if not self.remote_control:
            return None

        try:
            # Try to get metadata via D-Bus properties
            import dbus
            props_iface = dbus.Interface(
                self.bus.get_object(DBUS_SERVICE, DBUS_OBJECT_PATH),
                'org.freedesktop.DBus.Properties'
            )

            metadata = {}

            # Get standard MPRIS metadata fields
            try:
                title = props_iface.Get(DBUS_REMOTE_CONTROL_INTERFACE, 'Title')
                if title:
                    metadata['title'] = str(title)
            except:
                pass

            try:
                artist = props_iface.Get(DBUS_REMOTE_CONTROL_INTERFACE, 'Artist')
                if artist:
                    metadata['artist'] = str(artist)
            except:
                pass

            try:
                album = props_iface.Get(DBUS_REMOTE_CONTROL_INTERFACE, 'Album')
                if album:
                    metadata['album'] = str(album)
            except:
                pass

            if metadata:
                log(f"[DBUS] Fetched initial metadata: {metadata}")
                return metadata

        except Exception as e:
            log(f"[DBUS] Failed to get metadata: {e}")

        return None

    def get_position(self) -> Optional[int]:
        """Get current playback position in microseconds"""
        if not self.advanced_remote_control:
            return None

        try:
            # GetPlayerPosition returns position in microseconds
            position = self.advanced_remote_control.GetPlayerPosition()
            return int(position)
        except Exception as e:
            # Not all versions of shairport-sync support this
            return None

    def play(self):
        """Send play command"""
        if self.remote_control:
            try:
                self.remote_control.Play()
                log("[DBUS] Sent Play command")
                self.is_playing = True
                return True
            except Exception as e:
                log(f"[DBUS] Play failed: {e}")
        return False

    def pause(self):
        """Send pause command"""
        if self.remote_control:
            try:
                self.remote_control.Pause()
                log("[DBUS] Sent Pause command")
                self.is_playing = False
                return True
            except Exception as e:
                log(f"[DBUS] Pause failed: {e}")
        return False

    def play_pause(self):
        """Toggle play/pause"""
        if self.remote_control:
            try:
                self.remote_control.PlayPause()
                self.is_playing = not self.is_playing
                log(f"[DBUS] Sent PlayPause command (now {'playing' if self.is_playing else 'paused'})")
                return True
            except Exception as e:
                log(f"[DBUS] PlayPause failed: {e}")
        return False

    def next_track(self):
        """Skip to next track"""
        if self.remote_control:
            try:
                self.remote_control.Next()
                log("[DBUS] Sent Next command")
                return True
            except Exception as e:
                log(f"[DBUS] Next failed: {e}")
        return False

    def previous_track(self):
        """Skip to previous track"""
        if self.remote_control:
            try:
                self.remote_control.Previous()
                log("[DBUS] Sent Previous command")
                return True
            except Exception as e:
                log(f"[DBUS] Previous failed: {e}")
        return False

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
        # Track which track the pending artwork belongs to
        self.artwork_track_title = None
        self.artwork_track_artist = None
        self.artwork_track_album = None
        # Store complete metadata snapshot when artwork is validated
        # This prevents writing JSON with current_metadata that may have changed
        self.validated_artwork_metadata = None
        # RTP timestamps for correlation (official shairport-sync method)
        self.metadata_rtptime = None  # From mdst/mden
        self.picture_rtptime = None   # From pcst/pcen

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
                # Check if this is a new track (artist changed)
                if self.current_metadata.get("artist") and self.current_metadata["artist"] != decoded:
                    log(f"[DEBUG] Artist changed from '{self.current_metadata['artist']}' to '{decoded}' - clearing artwork")
                    self.current_metadata["artUrl"] = None  # Clear artwork for new track
                self.current_metadata["artist"] = decoded
                updated = True
                log(f"[DEBUG] Artist: {decoded}")
            elif item_type == "core" and code == "minm":  # Title/Track name
                # Check if this is a new track (title changed)
                if self.current_metadata.get("title") and self.current_metadata["title"] != decoded:
                    log(f"[DEBUG] Title changed from '{self.current_metadata['title']}' to '{decoded}' - clearing artwork")
                    self.current_metadata["artUrl"] = None  # Clear artwork for new track
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

                # Parse rtptime for metadata correlation (official shairport-sync method)
                if code == "mdst":  # Metadata Start - contains rtptime for metadata
                    if encoding == "base64" and data_text:
                        try:
                            rtptime_bytes = base64.b64decode(data_text)
                            # rtptime is 4 bytes, big-endian unsigned integer
                            prev_rtptime = self.metadata_rtptime
                            self.metadata_rtptime = int.from_bytes(rtptime_bytes[:4], 'big', signed=False)
                            log(f"[RTPTIME] Metadata rtptime: {prev_rtptime} → {self.metadata_rtptime}")
                        except:
                            pass
                elif code == "pcst":  # Picture Start - contains rtptime for picture
                    if encoding == "base64" and data_text:
                        try:
                            rtptime_bytes = base64.b64decode(data_text)
                            self.picture_rtptime = int.from_bytes(rtptime_bytes[:4], 'big', signed=False)
                            log(f"[RTPTIME] Picture rtptime: {self.picture_rtptime}")
                            log(f"[RTPTIME]   Current metadata rtptime: {self.metadata_rtptime}")
                            log(f"[RTPTIME]   Match: {self.picture_rtptime == self.metadata_rtptime}")
                        except:
                            self.picture_rtptime = None
                    else:
                        self.picture_rtptime = None

                    # Only record title/artist if we don't have rtptime
                    # If we have rtptime, we'll use ONLY that for validation
                    if self.picture_rtptime is None:
                        self.artwork_track_title = self.current_metadata.get("title")
                        self.artwork_track_artist = self.current_metadata.get("artist")
                        log(f"[PCST] Picture start (NO rtptime) for: '{self.artwork_track_title}' - '{self.artwork_track_artist}'")
                    else:
                        # We have rtptime - don't rely on title/artist (could be wrong if track changed)
                        self.artwork_track_title = None
                        self.artwork_track_artist = None
                        current_title = self.current_metadata.get("title")
                        current_artist = self.current_metadata.get("artist")
                        log(f"[PCST] Picture start WITH rtptime: {self.picture_rtptime}")
                        log(f"[PCST]   Current track: '{current_title}' - '{current_artist}'")
                elif code == "PICT":
                    if encoding == "base64" and data_text:
                        # This is a PICT data chunk - just collect it
                        self.pending_cover_data.append(data_text)
                        log(f"[DEBUG] Collected PICT chunk ({len(data_text)} chars), total chunks: {len(self.pending_cover_data)}")
                    else:
                        # This is the PICT end signal (no data)
                        if self.pending_cover_data:
                            log(f"[DEBUG] PICT end signal with {len(self.pending_cover_data)} chunks")

                            # Check if track has changed since we started collecting artwork
                            current_title = self.current_metadata.get("title")
                            current_artist = self.current_metadata.get("artist")

                            log(f"[VALIDATION] ========== ARTWORK VALIDATION CHECK ==========")
                            log(f"[VALIDATION] Recorded when PICT started: title='{self.artwork_track_title}', artist='{self.artwork_track_artist}'")
                            log(f"[VALIDATION] Current metadata now: title='{current_title}', artist='{current_artist}'")
                            log(f"[VALIDATION] Metadata rtptime: {self.metadata_rtptime}, Picture rtptime: {self.picture_rtptime}")

                            # Use rtptime correlation (official method) if available
                            rtptime_matches = (
                                self.metadata_rtptime is not None and
                                self.picture_rtptime is not None and
                                self.metadata_rtptime == self.picture_rtptime
                            )

                            # Fallback to title/artist matching if rtptime not available
                            title_artist_matches = (
                                (self.artwork_track_title is None or self.artwork_track_title == current_title) and
                                (self.artwork_track_artist is None or self.artwork_track_artist == current_artist)
                            )

                            if rtptime_matches:
                                # Primary validation: rtptime matches (most reliable)
                                log(f"[VALIDATION] ✓✓✓ PASS: rtptime matches ({self.metadata_rtptime}) - SAVING ARTWORK")
                                # CRITICAL: Capture metadata snapshot BEFORE saving artwork
                                # This ensures JSON file has correct metadata even if current_metadata changes
                                self.validated_artwork_metadata = {
                                    "title": current_title,
                                    "artist": current_artist,
                                    "album": current_album
                                }
                                log(f"[VALIDATION] Captured metadata snapshot: {self.validated_artwork_metadata}")
                                self._save_cover_art()
                                self.pending_cover_data = []
                                if self.current_metadata.get("artUrl"):
                                    log(f"[VALIDATION] Cover art complete, sending metadata update")
                                    return self.current_metadata.copy()
                            elif self.metadata_rtptime is None and self.picture_rtptime is None and title_artist_matches:
                                # Fallback validation: No rtptime available, use title/artist
                                log(f"[VALIDATION] ✓✓✓ PASS: No rtptime, title/artist matches - SAVING ARTWORK")
                                # CRITICAL: Capture metadata snapshot BEFORE saving artwork
                                self.validated_artwork_metadata = {
                                    "title": current_title,
                                    "artist": current_artist,
                                    "album": current_album
                                }
                                log(f"[VALIDATION] Captured metadata snapshot: {self.validated_artwork_metadata}")
                                self._save_cover_art()
                                self.pending_cover_data = []
                                if self.current_metadata.get("artUrl"):
                                    log(f"[VALIDATION] Cover art complete, sending metadata update")
                                    return self.current_metadata.copy()
                            else:
                                # Validation failed - discard artwork
                                if self.metadata_rtptime is not None and self.picture_rtptime is not None:
                                    log(f"[VALIDATION] ✗✗✗ FAIL: rtptime mismatch - DISCARDING STALE ARTWORK")
                                    log(f"[VALIDATION]   Metadata rtptime: {self.metadata_rtptime}")
                                    log(f"[VALIDATION]   Picture rtptime: {self.picture_rtptime}")
                                    log(f"[VALIDATION]   Difference: {abs(self.metadata_rtptime - self.picture_rtptime)}")
                                else:
                                    log(f"[VALIDATION] ✗✗✗ FAIL: Track changed - DISCARDING STALE ARTWORK")
                                    log(f"[VALIDATION]   Was: '{self.artwork_track_title}' by '{self.artwork_track_artist}'")
                                    log(f"[VALIDATION]   Now: '{current_title}' by '{current_artist}'")
                                self.pending_cover_data = []
                                self.artwork_track_title = None
                                self.artwork_track_artist = None
                            log(f"[VALIDATION] ==============================================")
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

            # Detect image format from magic bytes
            # JPEG: FF D8 FF, PNG: 89 50 4E 47 0D 0A 1A 0A
            if len(cover_data) >= 3 and cover_data[:3] == b'\xff\xd8\xff':
                extension = ".jpg"
                format_type = "JPEG"
            elif len(cover_data) >= 8 and cover_data[:8] == b'\x89PNG\r\n\x1a\n':
                extension = ".png"
                format_type = "PNG"
            else:
                # Unknown format, default to jpg
                extension = ".jpg"
                format_type = "Unknown (defaulting to JPEG)"

            # Use a hash of the data as filename to avoid duplicates
            import hashlib
            cover_hash = hashlib.md5(cover_data).hexdigest()
            filename = f"{cover_hash}{extension}"
            log(f"[DEBUG] Detected image format: {format_type}")

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
        self.artwork_track_title = None
        self.artwork_track_artist = None
        self.artwork_track_album = None
        self.validated_artwork_metadata = None


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.metadata_parser = MetadataParser()
        self.last_metadata = {}
        self.dbus = DBusInterface()
        self.last_position = 0
        self.position_update_interval = 2  # Update position every 2 seconds
        self.artwork_sequence = 0  # Increments with each artwork write
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
        """Write current artwork URL to JSON file for frontend to fetch

        CRITICAL: Uses validated_artwork_metadata snapshot, NOT current_metadata!
        This prevents race condition where artwork for Track N is written with
        Track N+1's metadata if track changes between validation and JSON write.
        """
        try:
            self.artwork_sequence += 1
            artwork_file = Path(SNAPCAST_WEB_ROOT) / "airplay-artwork.json"

            # Use validated snapshot if available, otherwise fall back to metadata param
            if self.metadata_parser.validated_artwork_metadata:
                validated_meta = self.metadata_parser.validated_artwork_metadata
                artwork_data = {
                    "artUrl": metadata.get("artUrl"),  # artUrl comes from metadata param
                    "title": validated_meta.get("title"),  # But title/artist/album from snapshot!
                    "artist": validated_meta.get("artist"),
                    "album": validated_meta.get("album"),
                    "sequence": self.artwork_sequence,
                    "timestamp": int(time.time() * 1000),
                    "metadata_rtptime": self.metadata_parser.metadata_rtptime,
                    "picture_rtptime": self.metadata_parser.picture_rtptime,
                }
                log(f"[ARTWORK-WRITE] Using validated metadata snapshot (prevents race condition)")
            else:
                # Fallback to metadata param if no snapshot (shouldn't happen)
                artwork_data = {
                    "artUrl": metadata.get("artUrl"),
                    "title": metadata.get("title"),
                    "artist": metadata.get("artist"),
                    "album": metadata.get("album"),
                    "sequence": self.artwork_sequence,
                    "timestamp": int(time.time() * 1000),
                    "metadata_rtptime": self.metadata_parser.metadata_rtptime,
                    "picture_rtptime": self.metadata_parser.picture_rtptime,
                }
                log(f"[ARTWORK-WRITE] WARNING: No validated snapshot, using metadata param")

            with open(artwork_file, 'w') as f:
                json.dump(artwork_data, f, indent=2)
            log(f"[ARTWORK-WRITE] Sequence #{self.artwork_sequence}: '{artwork_data.get('title')}' by '{artwork_data.get('artist')}'")
            log(f"[ARTWORK-WRITE]   artUrl: {artwork_data.get('artUrl')}")
            log(f"[ARTWORK-WRITE]   metadata_rtptime: {self.metadata_parser.metadata_rtptime}, picture_rtptime: {self.metadata_parser.picture_rtptime}")
            log(f"[ARTWORK-WRITE]   Wrote to: {artwork_file}")

            # Clear the validated snapshot after writing
            self.metadata_parser.validated_artwork_metadata = None
        except Exception as e:
            log(f"[ARTWORK-WRITE] ERROR writing artwork JSON: {e}")

    def send_metadata_update(self, metadata: Dict, include_position: bool = False):
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

        if meta_obj or include_position:
            # Build the properties object
            properties = {"metadata": meta_obj} if meta_obj else {}

            # Also add artUrl as a top-level property (not just in metadata)
            # since Snapcast might filter metadata fields but preserve top-level properties
            if metadata.get("artUrl"):
                properties["artUrl"] = metadata["artUrl"]

            # ALWAYS add control capabilities so they don't get lost on metadata updates
            properties["canPlay"] = True
            properties["canPause"] = True
            properties["canGoNext"] = True
            properties["canGoPrevious"] = True
            properties["canSeek"] = False  # AirPlay doesn't typically support seeking

            # ALWAYS add playback status so frontend stays in sync
            properties["playbackStatus"] = "Playing" if self.dbus.is_playing else "Paused"

            # Add playback properties
            if include_position:
                # Get position from D-Bus
                position_us = self.dbus.get_position()
                if position_us is not None:
                    # Convert microseconds to milliseconds for Snapcast
                    position_ms = position_us // 1000
                    properties["position"] = position_ms
                    self.last_position = position_ms

            # Send Plugin.Stream.Player.Properties
            self.send_notification("Plugin.Stream.Player.Properties", properties)

            if meta_obj:
                log(f"[DEBUG] Sent metadata update: {list(meta_obj.keys())}")
            if include_position and "position" in properties:
                log(f"[DEBUG] Sent position update: {properties['position']}ms, status: {properties.get('playbackStatus')}")
            if metadata.get("artUrl"):
                log(f"[DEBUG] Also sent top-level artUrl: {metadata['artUrl']}")

        # Since Snapcast filters out artUrl, write it to a JSON file
        # that the frontend can fetch via HTTP
        # Only write when we have artwork - frontend validation rejects stale artwork
        if metadata.get("artUrl"):
            self._write_artwork_json(metadata)

    def fetch_and_send_initial_metadata(self):
        """Fetch current metadata from D-Bus and send to Snapcast"""
        log("[DEBUG] Fetching initial metadata from D-Bus...")
        initial_metadata = self.dbus.get_current_metadata()

        if initial_metadata:
            self.last_metadata = initial_metadata
            self.send_metadata_update(initial_metadata, include_position=True)
            log("[DEBUG] Sent initial metadata to Snapcast")
        else:
            log("[DEBUG] No initial metadata available from D-Bus")

    def update_position(self):
        """Periodically update playback position"""
        log("[DEBUG] Starting position updater thread")
        while True:
            try:
                time.sleep(self.position_update_interval)

                # Only send position updates if we have metadata
                if self.last_metadata:
                    position_us = self.dbus.get_position()
                    if position_us is not None:
                        position_ms = position_us // 1000

                        # Only send update if position changed significantly (>1 second)
                        if abs(position_ms - self.last_position) > 1000:
                            # Send just the position update
                            properties = {
                                "position": position_ms,
                                "playbackStatus": "Playing" if self.dbus.is_playing else "Paused"
                            }
                            self.send_notification("Plugin.Stream.Player.Properties", properties)
                            self.last_position = position_ms

            except Exception as e:
                log(f"[DEBUG] Error in position updater: {e}")
                time.sleep(5)  # Back off on error

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            params = request.get("params", {})
            request_id = request.get("id")

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
                        # Use MPRIS standard field name for artwork
                        meta_obj["mpris:artUrl"] = self.last_metadata["artUrl"]

                # Build result with metadata, position, and capabilities
                result = {"metadata": meta_obj}
                if self.last_metadata and self.last_metadata.get("artUrl"):
                    result["artUrl"] = self.last_metadata["artUrl"]

                # Add position if available
                position_us = self.dbus.get_position()
                if position_us is not None:
                    result["position"] = position_us // 1000  # Convert to ms

                # Add playback status and capabilities
                result["playbackStatus"] = "Playing" if self.dbus.is_playing else "Paused"
                result["canPlay"] = True
                result["canPause"] = True
                result["canGoNext"] = True
                result["canGoPrevious"] = True
                result["canSeek"] = False

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }
                response_str = json.dumps(response)
                print(response_str, file=sys.stdout, flush=True)
                log(f"[DEBUG] Sent GetProperties response: {response_str[:300]}")

            # Handle control commands
            elif method == "Plugin.Stream.Player.Control":
                command = params.get("command", "")
                log(f"[DEBUG] Received control command: {command}")

                success = False
                if command == "play":
                    success = self.dbus.play()
                elif command == "pause":
                    success = self.dbus.pause()
                elif command == "playPause":
                    success = self.dbus.play_pause()
                elif command == "next":
                    success = self.dbus.next_track()
                elif command == "previous" or command == "prev":
                    success = self.dbus.previous_track()
                else:
                    log(f"[DEBUG] Unknown control command: {command}")

                # Send response
                if request_id is not None:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"success": success}
                    }
                    response_str = json.dumps(response)
                    print(response_str, file=sys.stdout, flush=True)
                    log(f"[DEBUG] Sent control response: success={success}")

                # Send updated properties after control command
                if success and self.last_metadata:
                    self.send_metadata_update(self.last_metadata, include_position=True)

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
                                    # On new track, clear old artwork if new metadata doesn't have it yet
                                    # Better to show no artwork briefly than wrong artwork
                                    if not metadata.get("artUrl"):
                                        log(f"[DEBUG] New track without artwork - will wait for artwork to arrive")

                                # Check if metadata actually changed before sending update
                                should_send = (
                                    not self.last_metadata or
                                    is_new_track or
                                    self.last_metadata.get("album") != metadata.get("album") or
                                    self.last_metadata.get("artUrl") != metadata.get("artUrl")
                                )

                                if should_send:
                                    self.last_metadata = metadata
                                    self.send_metadata_update(metadata)
                                else:
                                    log(f"[DEBUG] Metadata unchanged, skipping update")
                                    self.last_metadata = metadata

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

        # Start position updater in background thread
        position_thread = threading.Thread(target=self.update_position, daemon=True)
        position_thread.start()

        # Send Plugin.Stream.Ready notification to tell Snapcast we're ready
        self.send_notification("Plugin.Stream.Ready", {})
        log("[DEBUG] Sent Plugin.Stream.Ready notification")

        # Wait a moment for shairport-sync to be available on D-Bus
        time.sleep(2)

        # Fetch and send initial metadata if available
        self.fetch_and_send_initial_metadata()

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
