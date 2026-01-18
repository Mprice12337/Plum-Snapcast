#!/usr/bin/env python3
"""
Snapcast Control Script for Bluetooth Metadata
Monitors BlueZ D-Bus for MPRIS/AVRCP metadata and provides it to Snapcast via JSON-RPC

Based on proven pattern from airplay-control-script.py:
- Thread-safe metadata storage with atomic updates
- Playback state tracking (Playing/Paused/Stopped)
- Control command handling via BlueZ D-Bus
- Complete properties response for Snapcast
- Album art retrieval via AVRCP BIP/OBEX (BlueZ 5.81+)
"""

import argparse
import base64
import json
import os
import sys
import threading
import time
import urllib.request
from typing import Dict, Optional

# Configuration
LOG_FILE = "/tmp/bluetooth-control-script.log"

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
    import dbus.mainloop.glib
    from gi.repository import GLib
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    log("[Warning] D-Bus not available - Bluetooth features disabled")


class BluetoothCoverArtFetcher:
    """
    Fetches album art via AVRCP BIP (Basic Imaging Profile) over OBEX.

    Requires:
    - BlueZ 5.81+ with experimental features enabled (-E flag)
    - obexd daemon running
    - Device that supports AVRCP cover art (iOS 13+, Android, etc.)

    Flow:
    1. Detect ObexPort on MediaPlayer1 (indicates device supports cover art)
    2. Create OBEX session to that port via org.bluez.obex.Client1
    3. When Track.ImgHandle changes, use org.bluez.obex.Image1.GetThumbnail
    4. Convert image data to base64 data URL
    """

    def __init__(self, bus, on_artwork_callback):
        self.bus = bus
        self.on_artwork = on_artwork_callback
        self.obex_session = None
        self.obex_image_interface = None
        self.current_obex_port = None
        self.current_device_address = None
        self.last_img_handle = None
        self.fetching = False

    def setup_obex_session(self, device_address: str, obex_port: int) -> bool:
        """
        Create OBEX BIP session to the device's cover art port.

        Args:
            device_address: Bluetooth device address (XX:XX:XX:XX:XX:XX)
            obex_port: L2CAP PSM port from MediaPlayer1.ObexPort property
        """
        try:
            # Already have a session to this device/port
            if (self.obex_session and
                self.current_device_address == device_address and
                self.current_obex_port == obex_port):
                return True

            # Close existing session if different device/port
            if self.obex_session:
                self.close_session()

            log(f"[CoverArt] Setting up OBEX BIP session to {device_address} port {obex_port}")

            # Get OBEX Client interface
            obex_client_obj = self.bus.get_object(
                'org.bluez.obex',
                '/org/bluez/obex'
            )
            obex_client = dbus.Interface(
                obex_client_obj,
                'org.bluez.obex.Client1'
            )

            # Create BIP session
            # Target is the AVRCP Cover Art UUID
            session_path = obex_client.CreateSession(
                device_address,
                {
                    'Target': 'avrcp',
                    'Channel': dbus.UInt16(obex_port)
                }
            )

            log(f"[CoverArt] OBEX session created: {session_path}")

            # Get the Image1 interface for fetching cover art
            session_obj = self.bus.get_object('org.bluez.obex', session_path)
            self.obex_image_interface = dbus.Interface(
                session_obj,
                'org.bluez.obex.Image1'
            )
            self.obex_session = session_path
            self.current_device_address = device_address
            self.current_obex_port = obex_port

            log(f"[CoverArt] OBEX BIP session ready for cover art retrieval")
            return True

        except dbus.exceptions.DBusException as e:
            # org.bluez.obex.Error.Failed means obexd isn't running or device doesn't support BIP
            if "Failed" in str(e) or "NotSupported" in str(e):
                log(f"[CoverArt] Device may not support AVRCP cover art: {e}")
            else:
                log(f"[CoverArt] Failed to create OBEX session: {e}")
            return False
        except Exception as e:
            log(f"[CoverArt] Error setting up OBEX session: {e}")
            return False

    def fetch_cover_art(self, img_handle: str) -> Optional[str]:
        """
        Fetch cover art thumbnail for the given image handle.

        Args:
            img_handle: Image handle from MediaPlayer1.Track.ImgHandle

        Returns:
            Base64 data URL (data:image/jpeg;base64,...) or None if failed
        """
        if not self.obex_image_interface:
            log(f"[CoverArt] No OBEX session available")
            return None

        if not img_handle:
            log(f"[CoverArt] No image handle provided")
            return None

        # Skip if same handle as last fetch (avoid re-fetching same art)
        if img_handle == self.last_img_handle:
            log(f"[CoverArt] Same image handle, skipping fetch")
            return None

        if self.fetching:
            log(f"[CoverArt] Already fetching, skipping")
            return None

        try:
            self.fetching = True
            log(f"[CoverArt] Fetching thumbnail for handle: {img_handle}")

            # GetThumbnail returns the image file path
            # The thumbnail is typically 200x200 JPEG
            result = self.obex_image_interface.GetThumbnail(img_handle)

            # Result is the path to the downloaded image file
            if result:
                image_path = str(result)
                log(f"[CoverArt] Thumbnail downloaded to: {image_path}")

                # Read the image file and convert to base64
                try:
                    with open(image_path, 'rb') as f:
                        image_data = f.read()

                    if len(image_data) < 100:
                        log(f"[CoverArt] Image too small ({len(image_data)} bytes), likely invalid")
                        return None

                    # Convert to base64 data URL
                    base64_data = base64.b64encode(image_data).decode('utf-8')

                    # Detect image type (JPEG or PNG)
                    if image_data[:2] == b'\xff\xd8':
                        mime_type = 'image/jpeg'
                    elif image_data[:8] == b'\x89PNG\r\n\x1a\n':
                        mime_type = 'image/png'
                    else:
                        mime_type = 'image/jpeg'  # Default to JPEG

                    data_url = f"data:{mime_type};base64,{base64_data}"
                    log(f"[CoverArt] Successfully converted to data URL ({len(image_data)} bytes, {len(base64_data)} chars)")

                    self.last_img_handle = img_handle
                    return data_url

                except IOError as e:
                    log(f"[CoverArt] Failed to read image file: {e}")
                    return None
            else:
                log(f"[CoverArt] GetThumbnail returned empty result")
                return None

        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
            if "NotSupported" in str(e):
                log(f"[CoverArt] Device doesn't support thumbnail retrieval")
            elif "InvalidArguments" in str(e):
                log(f"[CoverArt] Invalid image handle: {img_handle}")
            else:
                log(f"[CoverArt] D-Bus error fetching thumbnail: {error_name}")
            return None
        except Exception as e:
            log(f"[CoverArt] Error fetching cover art: {e}")
            import traceback
            log(f"[CoverArt] Traceback: {traceback.format_exc()}")
            return None
        finally:
            self.fetching = False

    def close_session(self):
        """Close the OBEX session"""
        if self.obex_session:
            try:
                obex_client_obj = self.bus.get_object(
                    'org.bluez.obex',
                    '/org/bluez/obex'
                )
                obex_client = dbus.Interface(
                    obex_client_obj,
                    'org.bluez.obex.Client1'
                )
                obex_client.RemoveSession(self.obex_session)
                log(f"[CoverArt] Closed OBEX session")
            except Exception as e:
                log(f"[CoverArt] Error closing OBEX session: {e}")

            self.obex_session = None
            self.obex_image_interface = None
            self.current_device_address = None
            self.current_obex_port = None
            self.last_img_handle = None

    def handle_track_update(self, device_address: str, obex_port: Optional[int],
                           img_handle: Optional[str]):
        """
        Handle a track metadata update - fetch cover art if available.

        Args:
            device_address: Bluetooth device address
            obex_port: L2CAP PSM from MediaPlayer1.ObexPort (None if not supported)
            img_handle: Image handle from Track.ImgHandle (None if not available)
        """
        if not obex_port:
            # Device doesn't advertise AVRCP cover art support
            return

        if not img_handle:
            # No image handle in track metadata (might arrive later)
            log(f"[CoverArt] Track has no image handle yet")
            return

        # Setup session if needed
        if not self.setup_obex_session(device_address, obex_port):
            return

        # Fetch cover art in background thread to avoid blocking D-Bus loop
        def fetch_thread():
            data_url = self.fetch_cover_art(img_handle)
            if data_url and self.on_artwork:
                self.on_artwork(data_url)

        thread = threading.Thread(target=fetch_thread, daemon=True)
        thread.start()


class MetadataStore:
    """
    Thread-safe storage for current metadata and playback state.
    This ensures atomic reads/writes and consistency.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "title": None,
            "artist": None,
            "album": None,
            "artUrl": None,
            "duration": None,  # Track duration in milliseconds
            "position": 0,  # Current position in milliseconds
            "position_timestamp": None,  # When position was last updated (for interpolation)
            "last_updated": None,
            "playback_status": "Stopped",  # "Playing", "Paused", or "Stopped"
            "volume": None,  # Source volume 0-100 (from AVRCP Absolute Volume)
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

    def get_current_position(self) -> int:
        """
        Get current playback position with client-side interpolation.
        If playing, calculates position based on elapsed time since last update.
        Returns position in milliseconds.
        """
        with self.lock:
            stored_position = self.data.get("position", 0)
            playback_status = self.data.get("playback_status", "Stopped")
            position_timestamp = self.data.get("position_timestamp")
            duration = self.data.get("duration")

            # If not playing or no timestamp, return stored position
            if playback_status != "Playing" or position_timestamp is None:
                return stored_position

            # Calculate elapsed time and interpolate
            elapsed_ms = int((time.time() - position_timestamp) * 1000)
            interpolated_position = stored_position + elapsed_ms

            # Clamp to duration if available
            if duration and interpolated_position > duration:
                return duration

            return interpolated_position

    def get_all(self) -> Dict:
        """Get all metadata (returns a copy)"""
        with self.lock:
            return self.data.copy()

    def get_metadata_for_snapcast(self) -> Optional[Dict]:
        """
        Get metadata formatted for Snapcast.

        Snapcast expects simple field names:
        - title (string)
        - artist (array of strings)
        - album (string)
        - artUrl (string)
        """
        with self.lock:
            # Only return if we have at least a title
            if self.data.get("title"):
                meta = {}

                # Snapcast metadata fields (simple names)
                if self.data.get("title"):
                    meta["title"] = self.data["title"]

                if self.data.get("artist"):
                    # Snapcast expects artist as an array
                    artist = self.data["artist"]
                    meta["artist"] = [artist] if isinstance(artist, str) else artist

                if self.data.get("album"):
                    meta["album"] = self.data["album"]

                if self.data.get("artUrl"):
                    meta["artUrl"] = self.data["artUrl"]

                # Duration in SECONDS per Snapcast API (convert from BlueZ milliseconds)
                if self.data.get("duration"):
                    meta["duration"] = self.data["duration"] / 1000.0

                return meta
            return None


class BluetoothMetadataMonitor:
    """Monitor BlueZ D-Bus for Bluetooth audio metadata, playback state, volume, and cover art"""

    def __init__(self, store: MetadataStore, on_update_callback, stream_id: str):
        self.store = store
        self.on_update = on_update_callback
        self.stream_id = stream_id  # Needed for playback API posts on seek detection
        self.last_position_post_time = 0  # Rate limit immediate seek posts
        self.current_player_path = None
        self.player_interface = None
        self.player_properties = None
        # MediaTransport1 for volume control (AVRCP Absolute Volume)
        self.current_transport_path = None
        self.transport_properties = None
        self.bus = None
        # Cover art support (AVRCP BIP/OBEX)
        self.cover_art_fetcher = None
        self.current_obex_port = None
        self.current_device_address = None

        if not DBUS_AVAILABLE:
            log("[Bluetooth] D-Bus not available - monitoring disabled")
            return

        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

        # Initialize cover art fetcher
        self.cover_art_fetcher = BluetoothCoverArtFetcher(
            self.bus,
            self._on_cover_art_received
        )

        log("[Bluetooth] D-Bus monitor initialized (with cover art support)")

    def _on_cover_art_received(self, data_url: str):
        """Callback when cover art is successfully fetched"""
        log(f"[CoverArt] Received cover art ({len(data_url)} chars)")
        self.store.update(artUrl=data_url)
        if self.on_update:
            self.on_update()

    def _extract_device_address_from_path(self, player_path: str) -> Optional[str]:
        """Extract Bluetooth device address from D-Bus object path.

        Path format: /org/bluez/hci0/dev_XX_XX_XX_XX_XX_XX/player0
        Returns: XX:XX:XX:XX:XX:XX or None
        """
        try:
            # Find dev_ in path
            if '/dev_' in player_path:
                # Extract the address part
                parts = player_path.split('/')
                for part in parts:
                    if part.startswith('dev_'):
                        # dev_XX_XX_XX_XX_XX_XX -> XX:XX:XX:XX:XX:XX
                        addr = part[4:].replace('_', ':')
                        return addr
        except Exception as e:
            log(f"[CoverArt] Failed to extract device address from path: {e}")
        return None

    def _get_obex_port(self) -> Optional[int]:
        """Get the OBEX BIP port from MediaPlayer1.ObexPort property.

        This property is only available when:
        - BlueZ was started with -E (experimental features)
        - The connected device supports AVRCP cover art

        Returns: L2CAP PSM port number, or None if not supported
        """
        if not self.player_properties:
            return None

        try:
            obex_port = self.player_properties.Get('org.bluez.MediaPlayer1', 'ObexPort')
            port = int(obex_port)
            if port > 0:
                log(f"[CoverArt] Device supports cover art (ObexPort={port})")
                return port
        except dbus.exceptions.DBusException as e:
            # Property not available - device doesn't support cover art or bluetoothd -E not used
            if "UnknownProperty" in str(e) or "not found" in str(e).lower():
                log(f"[CoverArt] ObexPort not available (device may not support cover art or bluetoothd -E not enabled)")
            else:
                log(f"[CoverArt] Error getting ObexPort: {e}")
        except Exception as e:
            log(f"[CoverArt] Error getting ObexPort: {e}")

        return None

    def _extract_metadata_from_dict(self, metadata_dict: Dict) -> Dict:
        """Extract metadata from BlueZ MediaPlayer1 Track properties"""
        result = {}

        try:
            # MPRIS/AVRCP metadata fields
            if 'Title' in metadata_dict:
                result['title'] = str(metadata_dict['Title'])
                log(f"[Metadata] Title: {result['title']}")

            if 'Artist' in metadata_dict:
                # Artist can be a string or array
                artist = metadata_dict['Artist']
                if isinstance(artist, str):
                    result['artist'] = artist
                elif hasattr(artist, '__iter__'):
                    result['artist'] = ', '.join(str(a) for a in artist)
                else:
                    result['artist'] = str(artist)
                log(f"[Metadata] Artist: {result['artist']}")

            if 'Album' in metadata_dict:
                result['album'] = str(metadata_dict['Album'])
                log(f"[Metadata] Album: {result['album']}")

            # Image handle for AVRCP cover art (BlueZ 5.81+ with -E flag)
            # This is used to fetch cover art via OBEX BIP
            if 'ImgHandle' in metadata_dict:
                img_handle = str(metadata_dict['ImgHandle'])
                if img_handle:
                    result['img_handle'] = img_handle
                    log(f"[Metadata] Image Handle: {img_handle}")

            # Legacy: Direct album art URL (rarely used)
            if 'AlbumArt' in metadata_dict:
                result['artUrl'] = str(metadata_dict['AlbumArt'])
                log(f"[Metadata] Album Art URL: {result['artUrl']}")

        except Exception as e:
            log(f"[Error] Metadata extraction failed: {e}")

        return result

    def _extract_playback_status(self, status_str: str) -> str:
        """Convert MPRIS playback status to our format"""
        # MPRIS statuses: "playing", "paused", "stopped"
        status_map = {
            "playing": "Playing",
            "paused": "Paused",
            "stopped": "Stopped",
        }
        return status_map.get(status_str.lower(), "Stopped")

    def _properties_changed_handler(self, interface, changed, invalidated, path):
        """Handle D-Bus PropertiesChanged signals from BlueZ"""
        try:
            log(f"[DBus] ⚡ Signal received: interface={interface}, path={path}")
            # Handle MediaTransport1 for volume changes (AVRCP Absolute Volume)
            if interface == 'org.bluez.MediaTransport1':
                if 'Volume' in changed:
                    # Volume is 0-127, convert to 0-100 percentage
                    old_volume = self.store.get_all().get("volume")
                    raw_volume = int(changed['Volume'])
                    volume_percent = int(round(raw_volume / 1.27))

                    # Only notify Snapcast if volume actually changed
                    # This prevents notification spam from Bluetooth devices that send redundant volume signals
                    if volume_percent != old_volume:
                        log(f"[Volume] Transport volume changed: {old_volume}% → {volume_percent}%")
                        self.store.update(volume=volume_percent)
                        if self.on_update:
                            self.on_update()
                    else:
                        log(f"[Volume] Received duplicate volume signal: {volume_percent}% (no change)")
                return

            # We're interested in MediaPlayer1 interface for metadata/playback
            if interface != 'org.bluez.MediaPlayer1':
                return

            log(f"[DBus] Properties changed on {path}: {list(changed.keys())}")

            # If we don't have a player interface yet, set it up now
            # This handles the case where bluetoothd wasn't ready during startup scan
            if self.player_interface is None and path:
                try:
                    log(f"[DBus] Setting up player interface for {path}")
                    player_obj = self.bus.get_object('org.bluez', path)
                    self.player_interface = dbus.Interface(player_obj, 'org.bluez.MediaPlayer1')
                    self.player_properties = dbus.Interface(player_obj, 'org.freedesktop.DBus.Properties')
                    self.current_player_path = path
                    log(f"[DBus] ✓ Player interface ready - controls enabled")

                    # Notify that control became available
                    if self.on_update:
                        self.on_update()
                except Exception as e:
                    log(f"[Error] Failed to setup player interface: {e}")

            updated = False
            # Track if we should send Snapcast notification (for meaningful changes only)
            should_notify_snapcast = False

            # Check if Track metadata changed
            if 'Track' in changed:
                track_dict = changed['Track']
                log(f"[DBus] Track metadata changed: {list(track_dict.keys())}")

                metadata = self._extract_metadata_from_dict(track_dict)

                if metadata:
                    # Don't store img_handle in the main store - it's only used for fetching
                    img_handle = metadata.pop('img_handle', None)

                    # Update store with new metadata
                    self.store.update(**metadata)
                    updated = True
                    should_notify_snapcast = True  # Track change is meaningful

                    # Try to fetch cover art if we have an image handle and cover art fetcher
                    if img_handle and self.cover_art_fetcher and self.current_player_path:
                        # Extract device address from player path
                        device_address = self._extract_device_address_from_path(self.current_player_path)
                        if device_address:
                            # Check if player has ObexPort (indicates cover art support)
                            obex_port = self._get_obex_port()
                            if obex_port:
                                log(f"[CoverArt] Triggering cover art fetch (device={device_address}, port={obex_port}, handle={img_handle})")
                                self.cover_art_fetcher.handle_track_update(
                                    device_address, obex_port, img_handle
                                )

            # Check if playback status changed
            if 'Status' in changed:
                old_status = self.store.get_all().get("playback_status", "Unknown")
                status = self._extract_playback_status(str(changed['Status']))
                log(f"[DBus] ⚡ Status changed: {old_status} → {status}")
                self.store.update(playback_status=status)
                updated = True
                should_notify_snapcast = True  # Status change is meaningful

            # Check if position changed (AVRCP 1.3+)
            if 'Position' in changed:
                # Position is in milliseconds
                state_data = self.store.get_all()
                old_position = state_data.get("position", 0)
                position_ms = int(changed['Position'])
                delta_ms = position_ms - old_position
                log(f"[DBus] ⚡ Position changed: {old_position}ms → {position_ms}ms (Δ {delta_ms}ms)")
                self.store.update(position=position_ms)
                updated = True

                # DON'T notify Snapcast for position-only changes - position goes to playback API only
                # This prevents flooding Snapcast with constant Stream.OnUpdate notifications

                # CRITICAL: Detect seeks and post immediately to playback API
                # A seek is a position jump >2 seconds (same threshold as send_update)
                # This ensures the frontend updates immediately when user scrubs on source device
                is_seek = abs(delta_ms) > 2000
                if is_seek:
                    # Rate limit: don't post if send_update just posted (<500ms ago)
                    # This prevents duplicate posts during track changes when both D-Bus and send_update detect seeks
                    time_since_last_post = time.time() - self.last_position_post_time
                    if time_since_last_post > 0.5:
                        log(f"[Position] Seek detected! Posting immediately to playback API (delta: {delta_ms}ms)")
                        duration_ms = state_data.get("duration", 0)
                        playback_status = state_data.get("playback_status", "Stopped")
                        post_playback_position(
                            stream_id=self.stream_id,
                            position_ms=position_ms,
                            duration_ms=duration_ms or 0,
                            playback_status=playback_status.lower()
                        )
                        self.last_position_post_time = time.time()  # Update for rate limiting
                    else:
                        log(f"[Position] Seek detected but rate limited (last post {time_since_last_post:.2f}s ago)")

            # Check if duration is available in Track metadata
            if 'Track' in changed:
                track_dict = changed['Track']
                if 'Duration' in track_dict:
                    # Duration is in milliseconds
                    duration_ms = int(track_dict['Duration'])
                    log(f"[DBus] Duration: {duration_ms}ms")
                    self.store.update(duration=duration_ms)
                    updated = True
                    # Duration is part of track metadata, already marked for notification above

            # Only notify Snapcast for meaningful changes (track, status)
            # Position updates go to playback API only (via periodic thread)
            if should_notify_snapcast and self.on_update:
                log(f"[DBus] Calling send_update() due to meaningful property changes")
                self.on_update()
            elif updated:
                log(f"[DBus] Position updated (not sending to Snapcast, playback API will handle)")

        except Exception as e:
            log(f"[Error] Properties changed handler failed: {e}")

    def start(self):
        """Start monitoring D-Bus for Bluetooth metadata"""
        if not DBUS_AVAILABLE:
            log("[Bluetooth] D-Bus not available - metadata monitoring disabled")
            return

        log("[Bluetooth] Starting metadata monitoring...")

        try:
            # Subscribe to PropertiesChanged signals from BlueZ
            self.bus.add_signal_receiver(
                self._properties_changed_handler,
                dbus_interface='org.freedesktop.DBus.Properties',
                signal_name='PropertiesChanged',
                path_keyword='path'
            )

            log("[Bluetooth] ✓ Subscribed to BlueZ D-Bus PropertiesChanged signals")

            # Try to find existing media players
            self._scan_for_players()

            # Start GLib main loop in a thread for D-Bus signal reception
            self.loop = GLib.MainLoop()
            self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
            self.loop_thread.start()

            log("[Bluetooth] ✓ GLib main loop thread started (D-Bus signal reception should be active)")

        except Exception as e:
            log(f"[Error] Failed to start Bluetooth monitor: {e}")
            import traceback
            log(f"[Error] Traceback: {traceback.format_exc()}")

    def _scan_for_players(self):
        """Scan for existing Bluetooth media players and transports"""
        if not DBUS_AVAILABLE:
            return

        try:
            # Get BlueZ object manager
            obj_manager = dbus.Interface(
                self.bus.get_object('org.bluez', '/'),
                'org.freedesktop.DBus.ObjectManager'
            )

            objects = obj_manager.GetManagedObjects()

            for path, interfaces in objects.items():
                # Look for MediaPlayer1 interfaces (for playback control & metadata)
                if 'org.bluez.MediaPlayer1' in interfaces:
                    log(f"[Bluetooth] Found media player: {path}")
                    self.current_player_path = path

                    # Get interfaces for control
                    player_obj = self.bus.get_object('org.bluez', path)
                    self.player_interface = dbus.Interface(player_obj, 'org.bluez.MediaPlayer1')
                    self.player_properties = dbus.Interface(player_obj, 'org.freedesktop.DBus.Properties')

                    # Get current track if available
                    props = interfaces['org.bluez.MediaPlayer1']
                    img_handle = None
                    if 'Track' in props:
                        metadata = self._extract_metadata_from_dict(props['Track'])
                        if metadata:
                            # Extract img_handle before storing (it's not for the store)
                            img_handle = metadata.pop('img_handle', None)
                            self.store.update(**metadata)
                            log(f"[Bluetooth] Initial metadata loaded")

                    # Get current position if available (AVRCP 1.3+)
                    # BlueZ Position is in milliseconds (per org.bluez.MediaPlayer1 spec)
                    if 'Position' in props:
                        position_ms = int(props['Position'])
                        self.store.update(position=position_ms)
                        log(f"[Bluetooth] Initial position: {position_ms}ms")

                    # Get current playback status
                    if 'Status' in props:
                        status = self._extract_playback_status(str(props['Status']))
                        self.store.update(playback_status=status)
                        log(f"[Bluetooth] Initial status: {status}")

                    # Check for cover art support (AVRCP BIP/OBEX)
                    # ObexPort indicates the device supports AVRCP cover art
                    if self.cover_art_fetcher and img_handle:
                        obex_port = self._get_obex_port()
                        if obex_port:
                            device_address = self._extract_device_address_from_path(path)
                            if device_address:
                                log(f"[CoverArt] Triggering initial cover art fetch")
                                self.cover_art_fetcher.handle_track_update(
                                    device_address, obex_port, img_handle
                                )

                # Look for MediaTransport1 interfaces (for volume control via AVRCP)
                if 'org.bluez.MediaTransport1' in interfaces:
                    log(f"[Bluetooth] Found media transport: {path}")
                    self.current_transport_path = path

                    # Get transport properties interface for volume control
                    transport_obj = self.bus.get_object('org.bluez', path)
                    self.transport_properties = dbus.Interface(transport_obj, 'org.freedesktop.DBus.Properties')

                    # Get current volume if available
                    props = interfaces['org.bluez.MediaTransport1']
                    if 'Volume' in props:
                        raw_volume = int(props['Volume'])
                        volume_percent = int(round(raw_volume / 1.27))
                        self.store.update(volume=volume_percent)
                        log(f"[Bluetooth] Initial volume: {raw_volume}/127 = {volume_percent}%")
                    else:
                        log(f"[Bluetooth] Transport found but Volume property not available (device may not support AVRCP Absolute Volume)")

        except Exception as e:
            log(f"[Error] Player scan failed: {e}")

    def play(self):
        """Send play command via BlueZ"""
        if self.player_interface:
            try:
                self.player_interface.Play()
                log("[Control] Sent Play command")
                self.store.update(playback_status="Playing")
            except Exception as e:
                log(f"[Error] Play failed: {e}")

    def pause(self):
        """Send pause command via BlueZ"""
        if self.player_interface:
            try:
                self.player_interface.Pause()
                log("[Control] Sent Pause command")
                self.store.update(playback_status="Paused")
            except Exception as e:
                log(f"[Error] Pause failed: {e}")

    def next_track(self):
        """Skip to next track"""
        if self.player_interface:
            try:
                self.player_interface.Next()
                log("[Control] Sent Next command")
            except Exception as e:
                log(f"[Error] Next failed: {e}")

    def previous_track(self):
        """Skip to previous track"""
        if self.player_interface:
            try:
                self.player_interface.Previous()
                log("[Control] Sent Previous command")
            except Exception as e:
                log(f"[Error] Previous failed: {e}")

    def is_available(self):
        """Check if playback control is available"""
        return self.player_interface is not None

    def is_volume_available(self):
        """Check if volume control is available (AVRCP Absolute Volume)"""
        return self.transport_properties is not None

    def get_position(self) -> Optional[int]:
        """
        Get current position (milliseconds) from MediaPlayer1.
        Actively queries BlueZ since AVRCP position updates are infrequent.
        Returns position in milliseconds, or None if unavailable.
        """
        if not self.player_properties:
            return None

        try:
            # BlueZ Position is in milliseconds (per org.bluez.MediaPlayer1 spec)
            position_ms = self.player_properties.Get('org.bluez.MediaPlayer1', 'Position')
            return int(position_ms)
        except dbus.exceptions.DBusException as e:
            # Position property may not be available for all devices/states
            log(f"[Position] Could not get position: {e}")
            return None
        except Exception as e:
            log(f"[Error] Get position failed: {e}")
            return None

    def refresh_position(self):
        """Query current position from BlueZ and update store"""
        position_ms = self.get_position()
        if position_ms is not None:
            self.store.update(position=position_ms)
            log(f"[Bluetooth] Refreshed position: {position_ms}ms")
            return True
        return False

    def get_volume(self) -> Optional[int]:
        """Get current volume (0-100) from MediaTransport1"""
        if not self.transport_properties:
            return None

        try:
            raw_volume = self.transport_properties.Get('org.bluez.MediaTransport1', 'Volume')
            volume_percent = int(round(int(raw_volume) / 1.27))
            return volume_percent
        except dbus.exceptions.DBusException as e:
            # Volume property may not be available if device doesn't support AVRCP Absolute Volume
            log(f"[Volume] Could not get volume: {e}")
            return None
        except Exception as e:
            log(f"[Error] Get volume failed: {e}")
            return None

    def _refresh_transport(self) -> bool:
        """Refresh transport interface reference (in case it became stale)"""
        try:
            obj_manager = dbus.Interface(
                self.bus.get_object('org.bluez', '/'),
                'org.freedesktop.DBus.ObjectManager'
            )
            objects = obj_manager.GetManagedObjects()

            for path, interfaces in objects.items():
                if 'org.bluez.MediaTransport1' in interfaces:
                    log(f"[Volume] Refreshed media transport: {path}")
                    self.current_transport_path = path
                    transport_obj = self.bus.get_object('org.bluez', path)
                    self.transport_properties = dbus.Interface(transport_obj, 'org.freedesktop.DBus.Properties')
                    return True

            log("[Volume] No transport found during refresh")
            return False

        except Exception as e:
            log(f"[Error] Transport refresh failed: {e}")
            return False

    def set_volume(self, volume_percent: int) -> bool:
        """Set volume (0-100) via MediaTransport1 AVRCP Absolute Volume"""
        if not self.transport_properties:
            log("[Volume] Cannot set volume - no transport available")
            return False

        try:
            # Convert 0-100 to 0-127
            raw_volume = int(round(volume_percent * 1.27))
            raw_volume = max(0, min(127, raw_volume))  # Clamp to valid range

            self.transport_properties.Set(
                'org.bluez.MediaTransport1',
                'Volume',
                dbus.UInt16(raw_volume)
            )

            log(f"[Volume] Set volume to {volume_percent}% (raw: {raw_volume}/127)")
            self.store.update(volume=volume_percent)
            return True

        except dbus.exceptions.DBusException as e:
            # If we get "No such file or directory", the transport reference is stale
            # Try refreshing and retrying once
            if "No such file or directory" in str(e) or "UnknownObject" in str(e):
                log(f"[Volume] Transport reference stale, refreshing and retrying...")
                if self._refresh_transport():
                    try:
                        raw_volume = int(round(volume_percent * 1.27))
                        raw_volume = max(0, min(127, raw_volume))
                        self.transport_properties.Set(
                            'org.bluez.MediaTransport1',
                            'Volume',
                            dbus.UInt16(raw_volume)
                        )
                        log(f"[Volume] Set volume to {volume_percent}% after refresh (raw: {raw_volume}/127)")
                        self.store.update(volume=volume_percent)
                        return True
                    except Exception as retry_error:
                        log(f"[Volume] Retry after refresh failed: {retry_error}")
                        return False

            log(f"[Volume] Could not set volume (device may not support AVRCP Absolute Volume): {e}")
            return False
        except Exception as e:
            log(f"[Error] Set volume failed: {e}")
            return False

    def stop(self):
        """Stop monitoring and clean up"""
        # Close cover art OBEX session
        if self.cover_art_fetcher:
            self.cover_art_fetcher.close_session()

        # Stop GLib main loop
        if hasattr(self, 'loop'):
            self.loop.quit()


class SnapcastControlScript:
    """Snapcast control script that communicates via stdin/stdout"""

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.store = MetadataStore()
        self.bt_monitor = BluetoothMetadataMonitor(self.store, self.send_update, stream_id)
        self.last_position_post_time = 0  # Rate limit position posts to playback API
        self.last_playback_status = None  # Track state changes for immediate posting
        self.last_posted_position = None  # Track last posted position to detect seeks
        self.position_update_thread = None
        self.running = False
        log(f"[Init] Initialized for stream: {stream_id}")

    def _position_update_loop(self):
        """
        Periodic position update loop.
        Since AVRCP position updates are infrequent, we periodically:
        1. Query position from BlueZ
        2. Post to playback API for server-side interpolation
        This ensures accurate timeline tracking even without AVRCP events.
        """
        log("[Position] Starting periodic position update loop")
        while self.running:
            try:
                state_data = self.store.get_all()
                playback_status = state_data.get("playback_status", "Stopped")

                # Only update position when playing
                if playback_status == "Playing":
                    # Refresh position from BlueZ
                    self.bt_monitor.refresh_position()

                    # Get interpolated position and duration
                    position_ms = self.store.get_current_position()
                    duration_ms = state_data.get("duration", 0)

                    # Post to playback API
                    post_playback_position(
                        stream_id=self.stream_id,
                        position_ms=position_ms,
                        duration_ms=duration_ms or 0,
                        playback_status="playing"
                    )

                # Update every 5 seconds
                time.sleep(5)

            except Exception as e:
                log(f"[Position] Error in position update loop: {e}")
                time.sleep(5)

    def send_notification(self, method: str, params: Dict):
        """Send JSON-RPC notification to Snapcast via stdout"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        print(json.dumps(notification), file=sys.stdout, flush=True)
        log(f"[Snapcast] → {method}")

    def send_update(self):
        """Send Plugin.Stream.Player.Properties with current state and metadata"""
        meta_obj = self.store.get_metadata_for_snapcast() or {}
        state_data = self.store.get_all()
        playback_status = state_data.get("playback_status", "Stopped")
        duration_ms = state_data.get("duration", 0)
        volume = state_data.get("volume")  # May be None if AVRCP Absolute Volume not supported
        can_control = self.bt_monitor.is_available()
        can_volume = self.bt_monitor.is_volume_available()

        # Use interpolated position for accurate tracking
        position_ms = self.store.get_current_position()

        # CRITICAL: Convert playback status to lowercase for Snapcast compatibility
        # Snapcast expects "playing", "paused", "stopped" (lowercase)
        # Our internal store uses "Playing", "Paused", "Stopped" (capitalized)
        snapcast_playback_status = playback_status.lower() if playback_status else "stopped"

        # Notification params: include stream ID and all properties
        params = {
            "id": self.stream_id,  # Include stream ID so frontend knows which stream to update

            # Playback state
            "playbackStatus": snapcast_playback_status,
            "loopStatus": "none",
            "shuffle": False,
            "mute": False,
            "rate": 1.0,
            "position": position_ms / 1000.0 if position_ms else 0,  # Convert ms to seconds

            # Control capabilities (enable if D-Bus is available)
            "canGoNext": can_control,
            "canGoPrevious": can_control,
            "canPlay": can_control,
            "canPause": can_control,
            "canSeek": False,
            "canControl": can_control,

            # Metadata (simple field names)
            "metadata": meta_obj
        }

        # Include volume only if AVRCP Absolute Volume is available
        # This controls whether the frontend shows the volume slider
        if volume is not None and can_volume:
            params["volume"] = volume

        self.send_notification("Plugin.Stream.Player.Properties", params)

        # Post position to playback API for these conditions:
        # 1. State changed (play/pause/stop)
        # 2. Position jumped (seek detected - >2 second difference)
        # 3. Periodic update (every 5 seconds)
        # 4. Paused/stopped (ensure accurate frozen position)
        current_time = time.time()
        time_since_last_post = current_time - self.last_position_post_time
        last_status = getattr(self, 'last_playback_status', None)
        state_changed = last_status != playback_status

        # Detect seeks: position jumped more than 2 seconds from last posted position
        position_jumped = False
        if self.last_posted_position is not None and position_ms is not None:
            # Account for normal playback progress since last post
            expected_position = self.last_posted_position + (time_since_last_post * 1000)
            position_delta = abs(position_ms - expected_position)
            # Seek detected if delta > 2 seconds (2000ms)
            if position_delta > 2000:
                position_jumped = True
                log(f"[Seek] Detected position jump: {position_delta/1000:.1f}s delta")

        should_post = (state_changed or position_jumped or
                      time_since_last_post >= 5.0 or
                      playback_status in ("Paused", "Stopped"))

        if should_post:
            if state_changed:
                log(f"[PlaybackAPI] Posting due to state change: {last_status} → {playback_status}")
            self.last_position_post_time = current_time
            self.last_playback_status = playback_status
            self.last_posted_position = position_ms
            # Convert playback status to lowercase for playback API
            api_status = playback_status.lower() if playback_status else "stopped"
            post_playback_position(
                stream_id=self.stream_id,
                position_ms=position_ms,
                duration_ms=duration_ms or 0,
                playback_status=api_status
            )

        # Log what we sent
        if meta_obj:
            title = meta_obj.get('title', 'N/A')
            artist = meta_obj.get('artist', ['N/A'])
            artist_str = artist[0] if isinstance(artist, list) and artist else 'N/A'
            log(f"[Snapcast] Metadata → {title} - {artist_str} [{playback_status}] (stream={self.stream_id})")
            if "artUrl" in meta_obj:
                log(f"[Snapcast]   Artwork: {len(meta_obj['artUrl'])} chars")
        else:
            log(f"[Snapcast] State → [{playback_status}] (stream={self.stream_id})")

    def handle_command(self, line: str):
        """Handle JSON-RPC command from Snapcast"""
        try:
            request = json.loads(line)
            method = request.get("method", "")
            request_id = request.get("id")
            params = request.get("params", {})

            log(f"[Command] Received: {method} (id={request_id})")

            if method == "Plugin.Stream.Player.GetProperties":
                # Return COMPLETE properties object
                # First, refresh position from BlueZ (AVRCP updates are infrequent)
                self.bt_monitor.refresh_position()

                meta_obj = self.store.get_metadata_for_snapcast() or {}
                state_data = self.store.get_all()
                playback_status = state_data.get("playback_status", "Stopped")
                # Use interpolated position for accurate tracking
                position_ms = self.store.get_current_position()
                volume = state_data.get("volume")  # May be None
                can_control = self.bt_monitor.is_available()
                can_volume = self.bt_monitor.is_volume_available()

                # CRITICAL: Convert playback status to lowercase for Snapcast compatibility
                # Snapcast expects "playing", "paused", "stopped" (lowercase)
                snapcast_playback_status = playback_status.lower() if playback_status else "stopped"

                # Build complete properties response per Snapcast Stream Plugin API
                # Position in SECONDS per Snapcast API (convert from BlueZ milliseconds)
                properties = {
                    # Playback state
                    "playbackStatus": snapcast_playback_status,
                    "loopStatus": "none",
                    "shuffle": False,
                    "mute": False,
                    "rate": 1.0,
                    "position": position_ms / 1000.0 if position_ms else 0,

                    # Control capabilities
                    "canGoNext": can_control,
                    "canGoPrevious": can_control,
                    "canPlay": can_control,
                    "canPause": can_control,
                    "canSeek": False,
                    "canControl": can_control,

                    # Metadata
                    "metadata": meta_obj
                }

                # Include volume only if AVRCP Absolute Volume is available
                if volume is not None and can_volume:
                    properties["volume"] = volume

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": properties
                }
                print(json.dumps(response), file=sys.stdout, flush=True)
                log(f"[Snapcast] GetProperties → status={playback_status}, volume={volume}, metadata keys: {list(meta_obj.keys())}")

                # Post current position to playback API so frontend's next poll has fresh data
                # This ensures smooth stream switching and page refreshes
                duration_ms = state_data.get("duration", 0)
                api_status = playback_status.lower() if playback_status else "stopped"
                post_playback_position(
                    stream_id=self.stream_id,
                    position_ms=position_ms,
                    duration_ms=duration_ms or 0,
                    playback_status=api_status
                )

            elif method == "Plugin.Stream.Player.Control" or method == "Plugin.Stream.Control":
                # Handle playback control commands
                command = params.get("command", "")
                log(f"[Control] Received control command: {command} (params={params})")

                if not self.bt_monitor.is_available():
                    # Return error if D-Bus not available
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Control not available (no Bluetooth player connected)"
                        }
                    }
                    print(json.dumps(error_response), file=sys.stdout, flush=True)
                    return

                # Execute command via D-Bus and update state
                if command == "play":
                    self.bt_monitor.play()
                    self.send_update()
                elif command == "pause":
                    self.bt_monitor.pause()
                    self.send_update()
                elif command == "playPause":
                    # Toggle state
                    current_state = self.store.get_all().get("playback_status", "Paused")
                    if current_state == "Playing":
                        self.bt_monitor.pause()
                    else:
                        self.bt_monitor.play()
                    self.send_update()
                elif command == "next":
                    self.bt_monitor.next_track()
                    self.send_update()
                elif command == "previous" or command == "prev":
                    self.bt_monitor.previous_track()
                    self.send_update()
                elif command == "setVolume" or command == "volume":
                    # Handle volume control via AVRCP Absolute Volume
                    volume_param = params.get("volume") or params.get("params", {}).get("volume")
                    if volume_param is not None:
                        volume = int(volume_param)
                        if self.bt_monitor.is_volume_available():
                            success = self.bt_monitor.set_volume(volume)
                            if success:
                                self.send_update()
                                log(f"[Control] Volume set to {volume}%")
                            else:
                                log(f"[Control] Failed to set volume to {volume}%")
                        else:
                            log(f"[Control] Volume control not available (device may not support AVRCP Absolute Volume)")
                    else:
                        log(f"[Control] setVolume command missing volume parameter")
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
                log(f"[Command] WARNING: Unknown method '{method}'")
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
            log(f"[Error] Invalid JSON received: {e}")
        except Exception as e:
            log(f"[Error] Command handler exception: {e}")
            import traceback
            log(f"[Error] {traceback.format_exc()}")
            if 'request_id' in locals() and request_id:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }
                print(json.dumps(error_response), file=sys.stdout, flush=True)

    def run(self):
        """Main event loop"""
        log("[Init] Bluetooth Control Script starting...")

        # Start Bluetooth metadata monitoring
        self.bt_monitor.start()

        # Give D-Bus monitor a moment to initialize and scan for devices
        time.sleep(0.5)

        # Start periodic position update thread
        self.running = True
        self.position_update_thread = threading.Thread(target=self._position_update_loop, daemon=True)
        self.position_update_thread.start()

        # Send ready notification
        self.send_notification("Plugin.Stream.Ready", {})
        log("[Init] Sent Plugin.Stream.Ready")

        # CRITICAL: Send initial state to frontend immediately after startup
        # This ensures frontend has playback status even if D-Bus signals aren't received
        # Without this, frontend shows status=unknown indefinitely
        log("[Init] Sending initial state to frontend...")
        self.send_update()

        # Post initial position to playback API immediately (don't wait 5 seconds)
        # This ensures frontend has data available on initial load or stream switch
        state_data = self.store.get_all()
        if state_data.get("playback_status") == "Playing":
            position_ms = self.store.get_current_position()
            duration_ms = state_data.get("duration", 0)
            post_playback_position(
                stream_id=self.stream_id,
                position_ms=position_ms,
                duration_ms=duration_ms or 0,
                playback_status="playing"
            )
            log("[Init] Posted initial position to playback API")

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
        finally:
            self.running = False
            self.bt_monitor.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Bluetooth metadata control script for Snapcast')
    parser.add_argument('--stream', required=False, default=None, help='Stream ID (auto-detected from settings if not provided)')
    parser.add_argument('--snapcast-host', required=False, default='localhost', help='Snapcast host')
    parser.add_argument('--snapcast-port', required=False, default='1780', help='Snapcast port')

    args = parser.parse_args()

    # Determine stream ID - read from settings if not provided
    # Must match the stream ID created by bluetooth-stream-lifecycle-manager.py
    stream_id = args.stream
    if not stream_id:
        # Read Bluetooth device name from settings (same logic as lifecycle manager)
        device_name = "Plum Audio"  # Default fallback
        try:
            import os
            settings_file = "/app/data/settings.json"
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
                    device_name = settings.get('integrations', {}).get('bluetooth', {}).get('deviceName', 'Plum Audio')
            log(f"[Init] Read Bluetooth device name from settings: {device_name}")
        except Exception as e:
            log(f"[Init] Could not read settings, using default device name: {e}")

        # Construct stream ID to match lifecycle manager: "{deviceName} Bluetooth"
        stream_id = f"{device_name} Bluetooth"

    log(f"[Init] Starting with stream ID: {stream_id}")

    script = SnapcastControlScript(stream_id=stream_id)
    script.run()
