#!/usr/bin/env python3
"""
Snapcast Control Script for AirPlay Metadata
Reads metadata from shairport-sync pipe and provides it to Snapcast via JSON-RPC

Based on proven pattern from metadata-debug-server.py:
- Thread-safe metadata storage with atomic updates
- mdst/mden bundle pattern with pending state
- Independent artwork handling
- Only send complete, consistent updates to Snapcast
- D-Bus integration for playback state and remote control
"""

import argparse
import base64
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

# Configuration
METADATA_PIPE = "/tmp/shairport-sync-metadata"
COVER_ART_CACHE_DIR = "/tmp/shairport-sync/.cache/coverart"
LOG_FILE = "/tmp/airplay-control-script.log"
STREAM_END_SIGNAL_FILE = "/tmp/airplay-stream-end.signal"

# D-Bus service name for shairport-sync (instance-specific in multi-instance mode)
DBUS_SERVICE_NAME = "org.gnome.ShairportSync"
DBUS_INTERFACE_NAME = "org.gnome.ShairportSync.RemoteControl"

# Playback API configuration (for real-time position tracking independent of Snapcast)
# This API runs on the federation service port (default 5000)
PLAYBACK_API_PORT = int(os.getenv("FEDERATION_API_PORT", "5000"))
PLAYBACK_API_URL = f"http://localhost:{PLAYBACK_API_PORT}/api/playback"

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

def signal_stream_end():
    """Signal to lifecycle manager that stream should be removed"""
    try:
        # Write current timestamp to signal file
        # Lifecycle manager watches this file and removes stream when it updates
        with open(STREAM_END_SIGNAL_FILE, 'w') as f:
            f.write(str(time.time()))
        log("[Signal] Notified lifecycle manager to remove stream")
    except Exception as e:
        log(f"[Signal] Failed to write signal file: {e}")


def post_playback_position(stream_id: str, position_ms: int, duration_ms: int,
                           playback_status: str = "playing", **extra):
    """
    POST position update to playback API (non-blocking).

    Sends position data to our API instead of Snapcast notifications to avoid audio stuttering.
    """
    def _post():
        try:
            # URL-encode the stream_id for the path
            encoded_stream_id = urllib.request.quote(stream_id, safe='')
            url = f"{PLAYBACK_API_URL}/{encoded_stream_id}"

            data = {
                "position": position_ms,
                "duration": duration_ms,
                "playback_status": playback_status,
                **extra
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    log(f"[PlaybackAPI] Posted position: {position_ms}ms / {duration_ms}ms ({playback_status})")
                else:
                    log(f"[PlaybackAPI] Unexpected status: {response.status}")

        except urllib.error.URLError as e:
            # API might not be ready yet - this is expected during startup
            log(f"[PlaybackAPI] Failed to post (API may not be ready): {e.reason}")
        except Exception as e:
            log(f"[PlaybackAPI] Error posting position: {e}")

    # Run in background thread to avoid blocking metadata processing
    thread = threading.Thread(target=_post, daemon=True)
    thread.start()


# Try to import D-Bus - graceful fallback if not available
try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    log("[Warning] D-Bus not available - playback controls disabled")


class MetadataStore:
    """
    Thread-safe storage for current metadata and playback state.

    Position Interpolation:
    - Stores position and timestamp when D-Bus ProgressString updates
    - get_current_position() calculates current position by adding elapsed time
    - Provides smooth progress tracking between D-Bus updates (which only occur
      on track change/seek, not continuously during playback)
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "title": None,
            "artist": None,
            "album": None,
            "track_id": None,
            "artwork_url": None,
            "last_updated": None,
            "playback_status": "stopped",  # "playing", "paused", or "stopped"
            "duration": 0,  # Track duration in milliseconds
            "position": 0,  # Last known position from D-Bus (milliseconds)
            "position_timestamp": None,  # When position was last updated (for interpolation)
        }

    def update(self, **kwargs):
        """Update metadata fields atomically"""
        with self.lock:
            self.data.update(kwargs)
            self.data["last_updated"] = time.time()
            # Record timestamp when position is updated for interpolation
            if "position" in kwargs:
                self.data["position_timestamp"] = time.time()
            log(f"[Store] Updated: {list(kwargs.keys())}")

    def get_all(self) -> Dict:
        """Get all metadata (returns a copy)"""
        with self.lock:
            return self.data.copy()

    def get_current_position(self) -> int:
        """
        Get current playback position with client-side interpolation.
        If playing, calculates position based on elapsed time since last update.
        Returns position in milliseconds.
        """
        with self.lock:
            stored_position = self.data.get("position", 0)
            playback_status = self.data.get("playback_status", "stopped")
            position_timestamp = self.data.get("position_timestamp")
            duration = self.data.get("duration")

            # If not playing or no timestamp, return stored position
            if playback_status != "playing" or position_timestamp is None:
                return stored_position

            # Calculate elapsed time and interpolate
            elapsed_ms = int((time.time() - position_timestamp) * 1000)
            interpolated_position = stored_position + elapsed_ms

            # Clamp to duration if available
            if duration and interpolated_position > duration:
                return duration

            return interpolated_position

    def get_metadata_for_snapcast(self) -> Optional[Dict]:
        """
        Get metadata formatted for Snapcast.

        Snapcast expects simple field names (NOT MPRIS format):
        - title (string)
        - artist (array of strings)
        - album (string)
        - artUrl (string)
        - duration (float, seconds)

        Returns partial metadata if available - duration from prgr events
        can arrive before title/artist metadata.
        """
        with self.lock:
            meta = {}

            # Snapcast metadata fields (simple names, not MPRIS)
            if self.data.get("title"):
                meta["title"] = self.data["title"]

            if self.data.get("artist"):
                # Snapcast expects artist as an array
                meta["artist"] = [self.data["artist"]]

            if self.data.get("album"):
                meta["album"] = self.data["album"]

            if self.data.get("artwork_url"):
                meta["artUrl"] = self.data["artwork_url"]

            # Duration in SECONDS per Snapcast API (convert from internal milliseconds)
            # Internal storage is in ms, but Snapcast expects seconds (like position)
            # CRITICAL: Include duration even without title! prgr events provide duration
            # before metadata events arrive, allowing frontend to display progress immediately.
            if self.data.get("duration"):
                meta["duration"] = self.data["duration"] / 1000.0

            # Return metadata if we have ANY fields (duration, title, etc.)
            # Don't wait for complete metadata - partial updates are valuable
            return meta if meta else None


class MetadataParser:
    """
    Parse shairport-sync metadata using the proven pattern from debug server.

    Pattern:
    - Accumulate in pending_metadata during mdst...mden bundle
    - Apply atomically to store at mden
    - Handle artwork independently
    """

    def __init__(self, store: MetadataStore, on_position_update=None, dbus_monitor=None, on_state_change=None):
        self.store = store
        self.on_position_update = on_position_update  # Callback for position updates
        self.dbus_monitor = dbus_monitor  # D-Bus monitor for accurate position
        self.on_state_change = on_state_change  # Callback for playback state changes (sends Snapcast notification)

        # Current state (what's been applied)
        self.current = {
            "title": None,
            "artist": None,
            "album": None,
            "track_id": None
        }

        # Pending state (accumulating during bundle)
        self.pending_metadata = {
            "title": None,
            "artist": None,
            "album": None
        }

        # Artwork handling
        self.pending_cover_data = []

        # Track when artwork was loaded to prevent race condition clearing
        self.last_artwork_load_time = 0
        self.last_loaded_cache_file = None

        # Bundle state flags
        self.in_metadata_bundle = False
        self.in_artwork_bundle = False

        # Track change flag - prevents stale prgr events from overwriting position reset
        self.waiting_for_fresh_prgr = False
        self.expected_new_duration = None  # Duration from metadata bundle

    def parse_item(self, item_xml: str) -> bool:
        """
        Parse one XML item and update store.
        Returns True if store was updated (signals Snapcast notification needed).
        """
        try:
            root = ET.fromstring(item_xml)

            # Extract type and code
            type_elem = root.find("type")
            code_elem = root.find("code")
            if code_elem is None:
                return False

            item_type = bytes.fromhex(type_elem.text).decode('ascii', errors='ignore') if type_elem is not None else ""
            code = bytes.fromhex(code_elem.text).decode('ascii', errors='ignore')

            # Extract data
            data_elem = root.find("data")
            encoding = data_elem.get("encoding", "") if data_elem is not None else ""
            data_text = (data_elem.text or "").strip() if data_elem is not None else ""

            decoded = ""
            if encoding == "base64" and data_text and code != "PICT":
                try:
                    decoded = base64.b64decode(data_text).decode('utf-8', errors='ignore')
                except:
                    decoded = ""

            # ===== METADATA BUNDLE MARKERS (ssnc) =====
            if item_type == "ssnc":
                if code == "mdst":
                    # Metadata bundle START
                    log(f"[Bundle] Metadata START")
                    self.in_metadata_bundle = True
                    # Clear pending metadata for new bundle
                    self.pending_metadata = {
                        "title": None,
                        "artist": None,
                        "album": None
                    }
                    return False

                elif code == "mden":
                    # Metadata bundle END - ATOMIC APPLICATION
                    log(f"[Bundle] Metadata END")
                    self.in_metadata_bundle = False

                    updated = False

                    # Detect track change by checking if title changed
                    track_changed = False
                    if self.pending_metadata["title"]:
                        old_title = self.current.get("title")
                        new_title = self.pending_metadata["title"]
                        # Track changed if title changed AND old title wasn't placeholder/empty
                        # (Don't treat initial connection as track change - preserves mid-track position)
                        if old_title != new_title and old_title and old_title not in ["Unknown Track", "N/A"]:
                            track_changed = True
                            log(f"[Bundle] Track changed: '{old_title}' → '{new_title}'")

                    # Apply all pending metadata at once to both current and store
                    if self.pending_metadata["title"]:
                        self.current["title"] = self.pending_metadata["title"]
                        self.store.update(title=self.pending_metadata["title"])
                        log(f"[Bundle] Applied title: {self.pending_metadata['title']}")
                        updated = True

                    if self.pending_metadata["artist"]:
                        self.current["artist"] = self.pending_metadata["artist"]
                        self.store.update(artist=self.pending_metadata["artist"])
                        log(f"[Bundle] Applied artist: {self.pending_metadata['artist']}")
                        updated = True

                    if self.pending_metadata["album"]:
                        self.current["album"] = self.pending_metadata["album"]
                        self.store.update(album=self.pending_metadata["album"])
                        log(f"[Bundle] Applied album: {self.pending_metadata['album']}")
                        updated = True

                    # CRITICAL: Do NOT set playback status based on metadata!
                    # Metadata arrives even when paused (AirPlay sends metadata updates).
                    # Only pbeg, pfls, paus, prsm, prgr events and control commands should update status.

                    # CRITICAL: Reset position when track changes to prevent interpolation from previous track
                    if track_changed:
                        log(f"[Bundle] Resetting position for new track")
                        self.store.update(position=0, duration=0, position_timestamp=None)
                        # Flag to reject stale prgr events until we get fresh data from new track
                        self.waiting_for_fresh_prgr = True
                        self.expected_new_duration = None
                        log(f"[Bundle] Waiting for fresh prgr data from new track")
                        updated = True

                    # Check for cached artwork (in case track changed but artwork is from same album)
                    # This ensures artwork displays even when shairport-sync doesn't send new artwork events
                    artwork_url = self._load_artwork_from_cache()
                    if artwork_url:
                        self.last_artwork_load_time = time.time()
                        self.store.update(artwork_url=artwork_url)
                        log(f"[Artwork] Loaded from cache at metadata bundle end")
                        updated = True

                    # Signal update if we changed anything
                    return updated

                # ===== PLAYBACK STATE EVENTS (ssnc) =====
                elif code == "pbeg":
                    # Play stream begin
                    log(f"[Session] Play stream BEGIN")
                    current_state = self.store.get_all().get("playback_status", "stopped")
                    if current_state != "playing":
                        # Get actual starting position from D-Bus (handles mid-track connections)
                        position_ms = 0
                        duration_ms = 0
                        if self.dbus_monitor and self.dbus_monitor.is_available():
                            progress = self.dbus_monitor.get_progress()
                            if progress:
                                position_ms, duration_ms = progress
                                log(f"[State] Play begin at position {position_ms}ms from D-Bus (mid-track connection)")

                        # Start interpolation immediately if we have a valid position
                        self.store.update(playback_status="playing", position=position_ms, duration=duration_ms, position_timestamp=time.time())

                        # Send immediate Snapcast notification
                        if self.on_state_change:
                            self.on_state_change()

                        # Update playback API immediately with starting position
                        if self.on_position_update:
                            self.on_position_update(position_ms, duration_ms, "playing")

                        log(f"[State] Playback state → playing (stream begin, position={position_ms}ms) - notified")
                        return False  # Don't trigger duplicate notification
                    return False

                elif code == "pend":
                    # Play stream end - Can indicate pause from source device or track end
                    # NOTE: Also happens during track changes, but in that case pbeg will follow
                    log(f"[Session] Play stream END (pend)")
                    current_state = self.store.get_all().get("playback_status", "stopped")

                    # Treat pend as pause - stream goes idle
                    # Always update playback API and notify (frontend needs this for source device pause)
                    self.store.update(playback_status="paused")
                    state_data = self.store.get_all()
                    if self.on_position_update:
                        self.on_position_update(
                            state_data.get("position", 0),
                            state_data.get("duration", 0),
                            "paused"
                        )

                    # Always send immediate Snapcast notification for pause from source
                    if self.on_state_change:
                        self.on_state_change()
                    log(f"[State] Playback state → paused (stream ended) - Snapcast notified")
                    return False  # Don't trigger duplicate notification from pipe monitor

                elif code == "prgr":
                    # Progress information: "start_rtp/current_rtp/end_rtp" (RTP timestamps at 44.1kHz)
                    # Position updates POST to playback API (not Snapcast) to avoid audio stuttering
                    if data_text:
                        try:
                            decoded = base64.b64decode(data_text).decode('utf-8')
                            parts = decoded.split("/")
                            if len(parts) == 3:
                                start_rtp = int(parts[0])
                                current_rtp = int(parts[1])
                                end_rtp = int(parts[2])

                                # Convert RTP frames to milliseconds (44.1kHz = 44100 samples/sec)
                                duration_ms = int(((end_rtp - start_rtp) / 44100.0) * 1000)
                                position_ms = int(((current_rtp - start_rtp) / 44100.0) * 1000)

                                # Get current state for comparison
                                state_data = self.store.get_all()
                                old_position = state_data.get("position", 0)
                                old_duration = state_data.get("duration", 0)

                                # CRITICAL: If waiting for fresh prgr after track change, validate this data
                                fresh_prgr_accepted = False
                                if self.waiting_for_fresh_prgr:
                                    # Accept prgr if position is near start (< 10s) - this is the new track
                                    if position_ms < 10000:
                                        log(f"[Progress] Accepting fresh prgr (position={position_ms}ms < 10s) after track change")
                                        self.waiting_for_fresh_prgr = False
                                        self.expected_new_duration = duration_ms
                                        fresh_prgr_accepted = True
                                    # Also accept if duration changed significantly AND position is reasonable
                                    elif old_duration > 0 and abs(duration_ms - old_duration) > 10000 and position_ms < duration_ms * 0.2:
                                        log(f"[Progress] Accepting fresh prgr (duration changed: {old_duration}ms → {duration_ms}ms, position={position_ms}ms) after track change")
                                        self.waiting_for_fresh_prgr = False
                                        self.expected_new_duration = duration_ms
                                        fresh_prgr_accepted = True
                                    else:
                                        # Reject stale prgr data - position too high or same duration
                                        log(f"[Progress] REJECTING stale prgr (position={position_ms}ms, duration={duration_ms}ms) - waiting for fresh data from new track")
                                        return False

                                # Detect track changes by position jumping backwards significantly
                                # This can happen when prgr arrives before metadata bundle completes
                                # BUT: Don't re-flag if we just accepted a fresh prgr above (prevents infinite rejection)
                                track_likely_changed = (
                                    not fresh_prgr_accepted and
                                    (
                                        (old_position > 5000 and position_ms < old_position - 5000) or
                                        (old_duration > 0 and abs(duration_ms - old_duration) > 10000)
                                    )
                                )

                                if track_likely_changed:
                                    log(f"[Progress] Track change detected (position: {old_position}ms → {position_ms}ms, duration: {old_duration}ms → {duration_ms}ms)")
                                    # Reset position and flag to wait for confirmation
                                    self.waiting_for_fresh_prgr = True
                                    self.expected_new_duration = duration_ms

                                current_state = state_data.get("playback_status", "stopped")
                                if current_state != "playing":
                                    # State change to playing - notify Snapcast
                                    self.store.update(playback_status="playing", duration=duration_ms, position=position_ms, position_timestamp=time.time())
                                    if self.on_position_update:
                                        self.on_position_update(position_ms, duration_ms, "playing")
                                    return True  # Notify on state change
                                else:
                                    # Position update only - no Snapcast notification (avoid stuttering)
                                    self.store.update(duration=duration_ms, position=position_ms, position_timestamp=time.time())
                                    if self.on_position_update:
                                        self.on_position_update(position_ms, duration_ms, "playing")
                                    return False  # No notification for position-only updates
                        except (ValueError, ZeroDivisionError, UnicodeDecodeError) as e:
                            log(f"[Progress] Failed to parse prgr: {data_text} - {e}")
                    return False

                elif code == "paus":
                    # Pause (older shairport-sync versions)
                    log(f"[Session] PAUSE")
                    current_state = self.store.get_all().get("playback_status", "paused")

                    # Always update playback API and send notification
                    # (Frontend needs notification even if state unchanged to sync UI)
                    self.store.update(playback_status="paused")
                    state_data = self.store.get_all()
                    if self.on_position_update:
                        self.on_position_update(
                            state_data.get("position", 0),
                            state_data.get("duration", 0),
                            "paused"
                        )

                    # Send immediate Snapcast notification
                    if self.on_state_change:
                        self.on_state_change()
                    log(f"[State] Playback state → paused - Snapcast notified")
                    return False  # Don't trigger duplicate notification

                elif code == "pfls":
                    # Play stream flush (pause/stop)
                    log(f"[Session] Play stream FLUSH (pause)")
                    current_state = self.store.get_all().get("playback_status", "paused")

                    # Always update playback API and send notification
                    # (Frontend needs notification even if state unchanged to sync UI)
                    self.store.update(playback_status="paused")
                    state_data = self.store.get_all()
                    if self.on_position_update:
                        self.on_position_update(
                            state_data.get("position", 0),
                            state_data.get("duration", 0),
                            "paused"
                        )

                    # Send immediate Snapcast notification
                    if self.on_state_change:
                        self.on_state_change()
                    log(f"[State] Playback state → paused (stream flushed) - Snapcast notified")
                    return False  # Don't trigger duplicate notification

                elif code == "prsm":
                    # Play stream resume
                    log(f"[Session] Play stream RESUME")
                    current_state = self.store.get_all().get("playback_status", "playing")

                    # Get actual position from D-Bus before resuming (for accuracy)
                    if self.dbus_monitor and self.dbus_monitor.is_available():
                        progress = self.dbus_monitor.get_progress()
                        if progress:
                            position_ms, duration_ms = progress
                            # Start interpolation from D-Bus position
                            self.store.update(playback_status="playing", position=position_ms, duration=duration_ms, position_timestamp=time.time())
                            log(f"[State] Playback state → playing (stream resumed), position from D-Bus: {position_ms}ms")
                        else:
                            # No D-Bus position, start from last known position
                            self.store.update(playback_status="playing", position_timestamp=time.time())
                            log(f"[State] Playback state → playing (stream resumed, no D-Bus position)")
                    else:
                        # No D-Bus, start from last known position
                        self.store.update(playback_status="playing", position_timestamp=time.time())
                        log(f"[State] Playback state → playing (stream resumed)")

                    # Always notify playback API and frontend (even if already playing)
                    state_data = self.store.get_all()
                    if self.on_position_update:
                        self.on_position_update(
                            state_data.get("position", 0),
                            state_data.get("duration", 0),
                            "playing"
                        )

                    # Send immediate Snapcast notification
                    if self.on_state_change:
                        self.on_state_change()
                    log(f"[State] Playback state → playing (resumed) - Snapcast notified")
                    return False  # Don't trigger duplicate notification

                elif code == "pvol":
                    # Volume change (informational, we don't track volume from source)
                    log(f"[Session] Volume change from source")
                    return False

                elif code == "pcst":
                    # Artwork bundle START
                    log(f"[Artwork] START")
                    self.in_artwork_bundle = True
                    self.pending_cover_data = []
                    return False

                elif code == "pcen":
                    # Artwork bundle END
                    log(f"[Artwork] END")
                    self.in_artwork_bundle = False

                    # Load from cache (shairport-sync writes to disk)
                    artwork_url = self._load_artwork_from_cache()
                    if artwork_url:
                        self.last_artwork_load_time = time.time()
                        self.store.update(artwork_url=artwork_url)
                        log(f"[Artwork] Applied to store ({len(artwork_url)} chars)")
                        return True  # Signal update

                    return False

                elif code == "PICT":
                    # Artwork data (not used when caching is enabled)
                    if encoding == "base64" and data_text:
                        self.pending_cover_data.append(data_text)
                        log(f"[Artwork] Received PICT chunk ({len(data_text)} chars)")
                    return False

            # ===== METADATA FIELDS (core) =====
            if item_type == "core":
                if code == "mper" and decoded:  # Track ID (persistent ID)
                    track_id = decoded.strip()
                    if track_id:
                        # Detect track change
                        if self.current["track_id"] and self.current["track_id"] != track_id:
                            log(f"[Track] CHANGE: {self.current['track_id'][:8]}... → {track_id[:8]}...")
                            # Clear everything for new track
                            self.current = {
                                "title": None,
                                "artist": None,
                                "album": None,
                                "track_id": track_id
                            }
                            # CRITICAL: Also clear artwork cache tracker so same artwork can reload
                            self.last_loaded_cache_file = None

                            # Check if artwork was just loaded (within last 2 seconds)
                            # If yes, it's likely for the NEW track, so keep it
                            time_since_artwork = time.time() - self.last_artwork_load_time
                            should_clear_artwork = time_since_artwork > 2.0

                            if should_clear_artwork:
                                self.store.update(
                                    title=None,
                                    artist=None,
                                    album=None,
                                    track_id=track_id,
                                    artwork_url=None
                                )
                                log(f"[Track] Cleared all metadata including artwork (last loaded {time_since_artwork:.1f}s ago)")
                            else:
                                # Keep artwork - it was just loaded and is likely for this new track
                                self.store.update(
                                    title=None,
                                    artist=None,
                                    album=None,
                                    track_id=track_id
                                    # Note: artwork_url NOT set to None
                                )
                                log(f"[Track] Cleared metadata but KEPT artwork (loaded {time_since_artwork:.1f}s ago - likely for new track)")

                            return True  # Signal update to clear Snapcast
                        else:
                            self.current["track_id"] = track_id
                            self.store.update(track_id=track_id)
                            log(f"[Track] ID: {track_id[:8]}...")

                elif code == "minm" and decoded.strip():  # Title
                    if self.in_metadata_bundle:
                        self.pending_metadata["title"] = decoded.strip()
                        log(f"[Field] Title (pending): {decoded.strip()}")
                    else:
                        # Immediate update (outside bundle)
                        self.current["title"] = decoded.strip()
                        self.store.update(title=decoded.strip())
                        log(f"[Field] Title (immediate): {decoded.strip()}")
                        return True

                elif code == "asar" and decoded.strip():  # Artist
                    if self.in_metadata_bundle:
                        self.pending_metadata["artist"] = decoded.strip()
                        log(f"[Field] Artist (pending): {decoded.strip()}")
                    else:
                        # Immediate update (outside bundle)
                        self.current["artist"] = decoded.strip()
                        self.store.update(artist=decoded.strip())
                        log(f"[Field] Artist (immediate): {decoded.strip()}")
                        return True

                elif code == "asal" and decoded.strip():  # Album
                    if self.in_metadata_bundle:
                        self.pending_metadata["album"] = decoded.strip()
                        log(f"[Field] Album (pending): {decoded.strip()}")
                    else:
                        # Immediate update (outside bundle)
                        self.current["album"] = decoded.strip()
                        self.store.update(album=decoded.strip())
                        log(f"[Field] Album (immediate): {decoded.strip()}")
                        return True

        except ET.ParseError:
            # Expected when buffer cuts mid-XML
            pass
        except Exception as e:
            log(f"[Error] Parse exception: {e}")

        return False

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
            if self.last_loaded_cache_file == newest_file.name:
                return None  # No change

            # Read and encode
            with open(newest_file, 'rb') as f:
                image_data = f.read()

            import mimetypes
            mime_type = mimetypes.guess_type(str(newest_file))[0] or 'image/jpeg'
            data_url = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('ascii')}"

            self.last_loaded_cache_file = newest_file.name
            log(f"[Artwork] Loaded from cache: {newest_file.name} ({len(image_data)} bytes)")

            return data_url

        except Exception as e:
            log(f"[Error] Artwork load failed: {e}")
            return None


class DBusMonitor:
    """
    Monitor ShairportSync D-Bus interface for playback state changes.
    Provides remote control capabilities (play, pause, next, previous).
    """

    def __init__(self, store: MetadataStore, on_state_change_callback, on_metadata_update_callback=None):
        self.store = store
        self.on_state_change = on_state_change_callback
        self.on_metadata_update = on_metadata_update_callback
        self.dbus_interface = None
        self.dbus_properties = None
        self.mpris_interface = None  # MPRIS interface for seeking
        self.bus = None
        self._connection_complete = threading.Event()  # Signal when connection attempt finishes

        if not DBUS_AVAILABLE:
            log("[DBus] D-Bus Python bindings not available - control disabled")
            log("[DBus] Install py3-dbus and py3-gobject3 to enable controls")
            self._connection_complete.set()  # Mark as complete (failed)
            return

        # Start connection in background thread to avoid blocking
        connect_thread = threading.Thread(target=self._connect_with_retry, daemon=True)
        connect_thread.start()

    def _connect_with_retry(self):
        """Try to connect to ShairportSync D-Bus with retries"""
        max_retries = 10
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Initialize D-Bus main loop on first attempt
                if attempt == 0:
                    DBusGMainLoop(set_as_default=True)
                    log(f"[DBus] Attempting to connect to service: {DBUS_SERVICE_NAME}")

                # Connect to system bus
                self.bus = dbus.SystemBus()

                # Get ShairportSync RemoteControl interface (using instance-specific service name)
                shairport = self.bus.get_object(DBUS_SERVICE_NAME, '/org/gnome/ShairportSync')
                self.dbus_interface = dbus.Interface(shairport, DBUS_INTERFACE_NAME)
                self.dbus_properties = dbus.Interface(shairport, 'org.freedesktop.DBus.Properties')

                # Try to get MPRIS interface for seeking (may not be available)
                try:
                    mpris_obj = self.bus.get_object('org.mpris.MediaPlayer2.ShairportSync', '/org/mpris/MediaPlayer2')
                    self.mpris_interface = dbus.Interface(mpris_obj, 'org.mpris.MediaPlayer2.Player')
                    log("[DBus] ✓ MPRIS interface available - seeking enabled")
                except dbus.exceptions.DBusException:
                    log("[DBus] ℹ MPRIS interface not available - seeking disabled")
                    log("[DBus] (To enable: rebuild shairport-sync with --with-mpris-interface)")
                    self.mpris_interface = None

                # Note: ShairportSync doesn't expose playback state via D-Bus
                # We'll track state based on metadata events instead
                log("[DBus] ✓ Connected to ShairportSync D-Bus interface")
                log("[DBus] ✓ Control methods available (Play, Pause, Next, Previous)")
                log("[DBus] Note: Playback state tracked via metadata events")

                # Set initial state to paused (will update when metadata arrives)
                self.store.update(playback_status="paused")

                # Notify parent that we're ready
                if self.on_state_change:
                    self.on_state_change()

                self._connection_complete.set()  # Signal that connection succeeded
                return  # Success!

            except dbus.exceptions.DBusException as e:
                if attempt < max_retries - 1:
                    log(f"[DBus] Connection attempt {attempt + 1}/{max_retries} failed: {e}")
                    log(f"[DBus] Retrying in {retry_delay}s (ShairportSync may not be ready yet)...")
                    time.sleep(retry_delay)
                else:
                    log(f"[DBus] ✗ Failed to connect after {max_retries} attempts: {e}")
                    log("[DBus] Control features disabled - check that ShairportSync is running")
                    self.dbus_interface = None
                    self._connection_complete.set()  # Signal that connection failed
            except Exception as e:
                log(f"[DBus] ✗ Unexpected error during connection: {e}")
                self.dbus_interface = None
                self._connection_complete.set()  # Signal that connection failed
                break

    def on_properties_changed(self, interface_name, changed_properties, invalidated_properties):
        """
        Handle D-Bus property changes.
        Note: ShairportSync doesn't emit playback state changes via D-Bus.
        We track state based on metadata events instead.
        """
        # This handler is kept for future compatibility if ShairportSync adds state properties
        pass

    def play(self):
        """Send play command to ShairportSync"""
        if self.dbus_interface:
            try:
                self.dbus_interface.Play()
                log("[DBus] Sent Play command")
            except Exception as e:
                log(f"[DBus] Play failed: {e}")

    def pause(self):
        """Send pause command to ShairportSync"""
        if self.dbus_interface:
            try:
                self.dbus_interface.Pause()
                log("[DBus] Sent Pause command")
            except Exception as e:
                log(f"[DBus] Pause failed: {e}")

    def play_pause(self):
        """Toggle play/pause"""
        if self.dbus_interface:
            try:
                self.dbus_interface.PlayPause()
                log("[DBus] Sent PlayPause command")
            except Exception as e:
                log(f"[DBus] PlayPause failed: {e}")

    def next_track(self):
        """Skip to next track"""
        if self.dbus_interface:
            try:
                self.dbus_interface.Next()
                log("[DBus] Sent Next command")
            except Exception as e:
                log(f"[DBus] Next failed: {e}")

    def previous_track(self):
        """Skip to previous track"""
        if self.dbus_interface:
            try:
                self.dbus_interface.Previous()
                log("[DBus] Sent Previous command")
            except Exception as e:
                log(f"[DBus] Previous failed: {e}")

    def seek(self, position_ms: int):
        """Seek to specific position via MPRIS interface (if available)"""
        if self.mpris_interface:
            try:
                # MPRIS SetPosition takes track ID and position in microseconds
                # We'll use Seek with relative offset instead
                # First get current position from store
                current_position = self.store.get_all().get("position", 0)
                offset_ms = position_ms - current_position
                offset_us = offset_ms * 1000

                self.mpris_interface.Seek(dbus.Int64(offset_us))
                log(f"[DBus] Seek to {position_ms}ms (offset: {offset_ms}ms)")

                # Update store with new position
                self.store.update(position=position_ms)
            except Exception as e:
                log(f"[DBus] Seek failed: {e}")
        else:
            log("[DBus] Seek not available - MPRIS interface not enabled")

    def get_progress(self):
        """
        Get progress from D-Bus ProgressString property.
        Returns (position_ms, duration_ms) tuple or None if not available.

        If progress data is available, that means stream is playing,
        so we also update playback status to "playing".
        """
        if not self.dbus_properties:
            return None

        try:
            # Get ProgressString property from RemoteControl interface
            # Format: "start_rtp/current_rtp/end_rtp"
            progress_str = self.dbus_properties.Get(
                DBUS_INTERFACE_NAME,
                'ProgressString'
            )

            if progress_str:
                # Parse RTP timestamps
                parts = str(progress_str).split("/")
                if len(parts) == 3:
                    start_rtp = int(parts[0])
                    current_rtp = int(parts[1])
                    end_rtp = int(parts[2])

                    # Convert RTP frames to milliseconds (44.1kHz = 44100 samples/sec)
                    duration_ms = int(((end_rtp - start_rtp) / 44100.0) * 1000)
                    position_ms = int(((current_rtp - start_rtp) / 44100.0) * 1000)

                    # CRITICAL: Do NOT set playback status here!
                    # D-Bus ProgressString returns data even when paused, so having progress
                    # data doesn't mean the stream is playing. Only metadata events (pfls, paus,
                    # prsm, pbeg) and prgr events should control playback state.

                    return (position_ms, duration_ms)
        except Exception as e:
            # Property may not be available when stream is not playing
            # This is normal - don't log spam
            pass

        return None

    def get_playback_state(self):
        """
        Get current playback state from D-Bus PlayerState property.
        Returns "Playing", "Stopped", "Paused", or None if not available.

        This is critical for iOS AirPlay which doesn't send pause metadata events.
        """
        if not self.dbus_properties:
            return None

        try:
            # Get PlayerState property from RemoteControl interface
            player_state = self.dbus_properties.Get(
                DBUS_INTERFACE_NAME,
                'PlayerState'
            )
            return str(player_state) if player_state else None
        except Exception:
            # Property may not be available when stream is not playing
            # This is normal - don't log spam
            pass

        return None

    def wait_for_connection(self, timeout=5.0):
        """
        Wait for D-Bus connection attempt to complete.

        Args:
            timeout: Maximum time to wait in seconds (default: 5s)

        Returns:
            bool: True if connection succeeded, False if failed or timed out
        """
        completed = self._connection_complete.wait(timeout)
        if not completed:
            log(f"[DBus] Connection timeout after {timeout}s - continuing without D-Bus")
            return False
        return self.dbus_interface is not None

    def is_available(self):
        """Check if D-Bus control is available"""
        return self.dbus_interface is not None

    def can_seek(self):
        """Check if seek is available via MPRIS"""
        return self.mpris_interface is not None


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.store = MetadataStore()
        self.dbus_monitor = DBusMonitor(self.store, self.send_playback_state_update, self.send_metadata_update)
        self.metadata_parser = MetadataParser(
            self.store,
            on_position_update=self._on_position_update,
            dbus_monitor=self.dbus_monitor,
            on_state_change=self.send_playback_state_update
        )
        self.last_metadata_update_time = 0  # For debouncing metadata updates
        log(f"[Init] Initialized for stream: {stream_id}")

    def _on_position_update(self, position_ms: int, duration_ms: int, playback_status: str):
        """Callback for position updates - posts to our playback API"""
        post_playback_position(
            stream_id=self.stream_id,
            position_ms=position_ms,
            duration_ms=duration_ms,
            playback_status=playback_status
        )

    def send_notification(self, method: str, params: Dict):
        """Send JSON-RPC notification to Snapcast via stdout"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        print(json.dumps(notification), file=sys.stdout, flush=True)
        log(f"[Snapcast] → {method}")

    def send_playback_state_update(self):
        """Send playback state update to Snapcast (called when D-Bus state changes)"""
        playback_status = self.store.get_all().get("playback_status", "stopped")
        can_control = self.dbus_monitor.is_available()

        params = {
            "playbackStatus": playback_status,
            "canGoNext": can_control,
            "canGoPrevious": can_control,
            "canPlay": can_control,
            "canPause": can_control,
            "canControl": can_control,
        }
        self.send_notification("Plugin.Stream.Player.Properties", params)
        log(f"[Snapcast] Playback state → {playback_status} (stream={self.stream_id})")

    def send_metadata_update(self):
        """
        Send Plugin.Stream.Player.Properties notification to Snapcast.

        Only call on metadata/state changes (NOT position updates to avoid stuttering).
        Position is excluded from notifications and only provided via GetProperties.
        """
        meta_obj = self.store.get_metadata_for_snapcast() or {}
        state_data = self.store.get_all()
        playback_status = state_data.get("playback_status", "stopped")
        can_control = self.dbus_monitor.is_available()

        # Build notification params (position excluded - only in GetProperties)
        params = {
            # Playback state (same fields as GetProperties)
            "playbackStatus": playback_status,
            "loopStatus": "none",
            "shuffle": False,
            "volume": 100,
            "mute": False,
            "rate": 1.0,

            # Control capabilities
            "canGoNext": can_control,
            "canGoPrevious": can_control,
            "canPlay": can_control,
            "canPause": can_control,
            "canSeek": self.dbus_monitor.can_seek() if can_control else False,
            "canControl": can_control,

            # Metadata (simple field names)
            "metadata": meta_obj
        }
        self.send_notification("Plugin.Stream.Player.Properties", params)

        # Log notification
        title = meta_obj.get('title', 'N/A')
        artist = meta_obj.get('artist', ['N/A'])
        artist_str = artist[0] if isinstance(artist, list) and artist else 'N/A'
        log(f"[Snapcast] Metadata → {title} - {artist_str} [{playback_status}]")

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")
            params = request.get("params", {})

            log(f"[Command] Received: {method} (id={request_id})")

            if method == "Plugin.Stream.Player.GetProperties":
                # Return complete properties: playback state, control capabilities, metadata, position
                state_data = self.store.get_all()
                playback_status = state_data.get("playback_status", "stopped")
                meta_obj = self.store.get_metadata_for_snapcast() or {}
                can_control = self.dbus_monitor.is_available()

                # Get current position with interpolation
                position = self.store.get_current_position()
                position_seconds = position / 1000.0 if position is not None else 0.0

                # Build properties response
                properties = {
                    # Playback state (from D-Bus if available)
                    "playbackStatus": playback_status,
                    "loopStatus": "none",
                    "shuffle": False,
                    "volume": 100,
                    "mute": False,
                    "rate": 1.0,
                    "position": position_seconds,  # Convert milliseconds to seconds (float) per Snapcast API

                    # Control capabilities (enable if D-Bus available)
                    "canGoNext": can_control,
                    "canGoPrevious": can_control,
                    "canPlay": can_control,
                    "canPause": can_control,
                    "canSeek": self.dbus_monitor.can_seek() if can_control else False,
                    "canControl": can_control,

                    # Metadata (MPRIS format)
                    "metadata": meta_obj
                }

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": properties
                }

                print(json.dumps(response), file=sys.stdout, flush=True)
                log(f"[Snapcast] GetProperties → status={playback_status}, position={position_seconds:.1f}s")

            elif method == "Plugin.Stream.Player.Control" or method == "Plugin.Stream.Control":
                # Handle playback control commands
                command = params.get("command", "")
                log(f"[Control] Received control command: {command} (params={params})")

                if not self.dbus_monitor.is_available():
                    # Return error if D-Bus not available
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Control not available (D-Bus not connected)"
                        }
                    }
                    print(json.dumps(error_response), file=sys.stdout, flush=True)
                    return

                # Execute command via D-Bus - let metadata events update state
                if command == "play":
                    self.dbus_monitor.play()
                    log("[Command] Play command sent - waiting for metadata confirmation")

                elif command == "pause":
                    self.dbus_monitor.pause()
                    log("[Command] Pause command sent - waiting for metadata confirmation")

                elif command == "playPause":
                    self.dbus_monitor.play_pause()
                    log("[Command] PlayPause command sent - waiting for metadata confirmation")
                elif command == "next":
                    self.dbus_monitor.next_track()
                    log("[Command] Next track command sent - waiting for metadata confirmation")

                elif command == "previous" or command == "prev":
                    self.dbus_monitor.previous_track()
                    log("[Command] Previous track command sent - waiting for metadata confirmation")
                elif command == "seek":
                    # Seek to specific position (in milliseconds)
                    position = params.get("position", 0)
                    log(f"[Control] Seeking to position: {position}ms")
                    self.dbus_monitor.seek(position)
                    self.send_metadata_update()
                else:
                    log(f"[Snapcast] Unknown control command: {command}")

                # Send success response
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                }
                print(json.dumps(response), file=sys.stdout, flush=True)
                log(f"[Control] Sent success response for: {command}")

            else:
                # Unknown method
                log(f"[Command] WARNING: Unknown method '{method}' - request: {request}")
                if request_id:
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}"
                        }
                    }
                    print(json.dumps(error_response), file=sys.stdout, flush=True)

        except json.JSONDecodeError as e:
            log(f"[Error] Invalid JSON received: {e} - line: {line[:100]}")
        except Exception as e:
            log(f"[Error] Command handler exception: {e}")
            import traceback
            log(f"[Error] {traceback.format_exc()}")
            if request_id:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }
                print(json.dumps(error_response), file=sys.stdout, flush=True)

    def monitor_position_updates(self):
        """
        Background thread for heartbeat updates to prevent playback API staleness.

        Sends periodic heartbeats (10s) that keep data fresh without breaking interpolation.
        Actual position changes come from prgr events.
        """
        log("[Init] Starting position monitor (heartbeat mode)")

        # On startup, check D-Bus ONCE to detect if stream is already playing
        if self.dbus_monitor.is_available():
            progress = self.dbus_monitor.get_progress()
            if progress:
                position_ms, duration_ms = progress
                self.store.update(
                    position=position_ms,
                    duration=duration_ms,
                    position_timestamp=time.time(),
                    playback_status="playing"
                )
                log(f"[Init] Detected active stream via D-Bus (position={position_ms}ms, duration={duration_ms}ms)")
                # Send initial state notification to Snapcast
                self.send_playback_state_update()
                # Send initial position to playback API
                self._on_position_update(position_ms, duration_ms, "playing")

        # Periodic heartbeat loop - prevent API staleness
        # API will only reset timestamp if position changed significantly
        while True:
            try:
                time.sleep(10.0)  # Heartbeat every 10 seconds

                state_data = self.store.get_all()
                playback_status = state_data.get("playback_status", "unknown")

                # Only send heartbeat if playing (avoid spam when idle)
                if playback_status == "playing":
                    position_ms = state_data.get("position", 0)
                    duration_ms = state_data.get("duration", 0)

                    # Send heartbeat (API won't reset timestamp if position unchanged)
                    self._on_position_update(position_ms, duration_ms, playback_status)

            except Exception as e:
                log(f"[Error] Position monitor error: {e}")
                time.sleep(30.0)

    def monitor_metadata_pipe(self):
        """Monitor shairport-sync metadata pipe"""
        log("[Init] Starting metadata pipe monitor")

        # Wait for pipe
        while not Path(METADATA_PIPE).exists():
            log(f"[Init] Waiting for pipe: {METADATA_PIPE}")
            time.sleep(1)

        log(f"[Init] Pipe found: {METADATA_PIPE}")

        # LINE-BY-LINE reading
        tmp = ""
        line_count = 0
        try:
            while True:
                with open(METADATA_PIPE, 'r') as pipe:
                    for line in pipe:
                        line_count += 1
                        strip_line = line.strip()

                        # Log every 100 lines to show pipe is active
                        if line_count % 100 == 0:
                            log(f"[Pipe] Processed {line_count} lines from metadata pipe")

                        if strip_line.endswith("</item>"):
                            # Complete item
                            item_xml = tmp + strip_line
                            updated = self.metadata_parser.parse_item(item_xml)

                            # Send update to Snapcast if store was modified
                            if updated:
                                log("[Pipe] Metadata changed, triggering Snapcast update")
                                self.send_metadata_update()

                            tmp = ""

                        elif strip_line.startswith("<item>"):
                            # New item starting
                            if tmp:
                                # Previous item incomplete - try to close it
                                item_xml = tmp + "</item>"
                                updated = self.metadata_parser.parse_item(item_xml)
                                if updated:
                                    log("[Pipe] Metadata changed (incomplete item), triggering Snapcast update")
                                    self.send_metadata_update()

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

        # Wait for D-Bus connection attempt to complete (with timeout)
        # This ensures capabilities are correctly reported from the start
        log("[Init] Waiting for D-Bus connection...")
        self.dbus_monitor.wait_for_connection(timeout=5.0)

        # Start metadata monitor in background
        monitor_thread = threading.Thread(target=self.monitor_metadata_pipe, daemon=True)
        monitor_thread.start()

        # Start position update monitor in background
        position_thread = threading.Thread(target=self.monitor_position_updates, daemon=True)
        position_thread.start()

        # Start D-Bus main loop in background (if available)
        if DBUS_AVAILABLE and self.dbus_monitor.is_available():
            dbus_loop = GLib.MainLoop()
            dbus_thread = threading.Thread(target=dbus_loop.run, daemon=True)
            dbus_thread.start()
            log("[Init] D-Bus event loop started")

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
    parser.add_argument('--stream', required=False, help='Stream ID (auto-generated from instance-id if not provided)')
    parser.add_argument('--instance-id', required=False, help='Instance ID for multi-instance mode (1, 2, or 3)')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    # Multi-instance support: override paths based on instance-id
    if args.instance_id:
        instance_id = args.instance_id

        # Get endpoint name from settings.json for stream display name (must match lifecycle manager)
        endpoint_name = None
        try:
            import json
            with open('/app/data/settings.json', 'r') as f:
                settings = json.load(f)
                endpoints = settings.get('integrations', {}).get('airplay', {}).get('endpoints', [])
                for endpoint in endpoints:
                    if endpoint.get('id') == instance_id:
                        endpoint_name = endpoint.get('deviceName', f'Endpoint {instance_id}')
                        break
        except Exception as e:
            print(f"[Init] WARNING: Could not read endpoint name from settings: {e}", file=sys.stderr)
            endpoint_name = f'Endpoint {instance_id}'

        # Override module-level constants GLOBALLY for this instance
        # These assignments modify the global variables defined at module level
        globals()['METADATA_PIPE'] = f"/tmp/airplay-{instance_id}-metadata"
        globals()['COVER_ART_CACHE_DIR'] = f"/tmp/shairport-sync-{instance_id}/.cache/coverart"
        globals()['LOG_FILE'] = f"/tmp/airplay-{instance_id}-control-script.log"
        globals()['STREAM_END_SIGNAL_FILE'] = f"/tmp/airplay-{instance_id}-stream-end.signal"

        # NOTE: D-Bus service name is NOT instance-specific
        # Only instance 1 has D-Bus enabled (all instances connect to org.gnome.ShairportSync)
        # D-Bus controls (play/pause/skip) only work on instance 1

        # Generate stream ID to match lifecycle manager format: "AirPlay - [device name]"
        # This MUST match what the lifecycle manager uses when creating the stream
        stream_id = args.stream if args.stream else (f"AirPlay - {endpoint_name}" if endpoint_name else f"AirPlay-{instance_id}")

        # Log confirmation (using the new global values)
        print(f"[Init] Multi-instance mode: instance={instance_id}, stream={stream_id}", file=sys.stderr)
        print(f"[Init] Endpoint name: {endpoint_name}", file=sys.stderr)
        print(f"[Init] Metadata pipe: {globals()['METADATA_PIPE']}", file=sys.stderr)
        print(f"[Init] Artwork cache: {globals()['COVER_ART_CACHE_DIR']}", file=sys.stderr)
    else:
        # Single-instance mode (original behavior)
        stream_id = args.stream if args.stream else 'Airplay'
        print(f"[Init] Single-instance mode: stream={stream_id}", file=sys.stderr)

    script = SnapcastControlScript(stream_id=stream_id)
    script.run()
