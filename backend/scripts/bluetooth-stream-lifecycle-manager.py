#!/usr/bin/env python3
"""
Bluetooth Stream Lifecycle Manager for Plum-Snapcast

Manages dynamic creation/removal of Snapcast Bluetooth stream based on device connections.
Keeps Bluetooth services always discoverable/available but only creates Snapcast stream
when Bluetooth devices are actively connected.

Features:
- Monitors BlueZ D-Bus for A2DP device connections
- Adds Bluetooth stream to Snapserver when device connects
- Removes stream after idle timeout when device disconnects
- Event-driven timeout management (no polling)
- Communicates with Snapserver via JSON-RPC 2.0 (HTTP + WebSocket)
- Coordinates with FIFO keeper to prevent bluealsa-aplay blocking
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from enum import Enum
from typing import Optional
import http.client
import websocket

# Try to import D-Bus - graceful fallback if not available
try:
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    print("[Warning] D-Bus not available - Bluetooth lifecycle management disabled", file=sys.stderr)

# Configuration
SNAPSERVER_HOST = "localhost"
SNAPSERVER_PORT = 1780
LOG_FILE = "/tmp/bluetooth-stream-lifecycle-manager.log"

# Timeout configuration (in seconds)
IDLE_TIMEOUT = 300  # 5 minutes - time to wait after device disconnects before removing stream

# Stream configuration
BLUETOOTH_STREAM_ID = "Bluetooth"
BLUETOOTH_FIFO_PATH = "/tmp/bluetooth-fifo"
BLUETOOTH_CONTROL_SCRIPT = "/usr/share/snapserver/plug-ins/bluetooth-control-script.py"


class StreamState(Enum):
    """Stream lifecycle states"""
    IDLE = "idle"           # No stream exists, no device connected
    ACTIVE = "active"       # Stream exists, device connected
    TIMEOUT = "timeout"     # Device disconnected, waiting before removal


def log(message: str):
    """Log to both stderr and a file"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"{timestamp} [BT-Lifecycle] {message}"
    print(log_msg, file=sys.stderr, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(log_msg + "\n")
    except:
        pass


class SnapserverClient:
    """JSON-RPC client for Snapserver API"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.request_id = 0

    def _call_rpc(self, method: str, params: dict = None) -> Optional[dict]:
        """Make a JSON-RPC call to Snapserver"""
        self.request_id += 1

        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method
        }
        if params:
            request["params"] = params

        try:
            # Use HTTP connection to Snapserver
            conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
            headers = {"Content-Type": "application/json"}
            body = json.dumps(request)

            conn.request("POST", "/jsonrpc", body, headers)
            response = conn.getresponse()
            response_data = response.read().decode('utf-8')
            conn.close()

            result = json.loads(response_data)

            if "error" in result:
                log(f"RPC error: {result['error']}")
                return None

            return result.get("result")

        except Exception as e:
            log(f"RPC call failed: {e}")
            return None

    def add_stream(self, stream_uri: str) -> bool:
        """Add a stream to Snapserver"""
        log(f"Adding stream: {stream_uri}")
        result = self._call_rpc("Stream.AddStream", {"streamUri": stream_uri})

        if result:
            stream_id = result.get("stream_id")
            log(f"✓ Stream added: {stream_id}")
            return True
        else:
            log(f"✗ Failed to add stream")
            return False

    def remove_stream(self, stream_id: str) -> bool:
        """Remove a stream from Snapserver"""
        log(f"Removing stream: {stream_id}")
        result = self._call_rpc("Stream.RemoveStream", {"id": stream_id})

        if result:
            removed_id = result.get("stream_id")
            log(f"✓ Stream removed: {removed_id}")
            return True
        else:
            log(f"✗ Failed to remove stream")
            return False

    def get_status(self) -> Optional[dict]:
        """Get server status"""
        return self._call_rpc("Server.GetStatus")

    def set_group_stream(self, group_id: str, stream_id: str) -> bool:
        """Set a group's stream"""
        log(f"Setting group {group_id} to stream {stream_id}")
        result = self._call_rpc("Group.SetStream", {"id": group_id, "stream_id": stream_id})

        if result:
            log(f"✓ Group {group_id} moved to stream {stream_id}")
            return True
        else:
            log(f"✗ Failed to set group stream")
            return False

    def move_clients_to_fallback_stream(self, from_stream_id: str) -> bool:
        """Move all clients from a stream to the default 'none' fallback stream

        This is called before removing a stream to ensure clients don't become orphaned.
        """
        try:
            status = self.get_status()
            if not status or 'server' not in status:
                log("ERROR: Could not get server status for client reassignment")
                return False

            # Find the none stream (first one that starts with 'none-')
            none_stream_id = None
            if 'streams' in status['server']:
                for stream in status['server']['streams']:
                    if stream['id'].startswith('none-'):
                        none_stream_id = stream['id']
                        break

            if not none_stream_id:
                log("WARNING: No 'none' stream found - clients will be orphaned")
                return False

            # Find all groups currently on the stream being removed
            moved_count = 0
            if 'groups' in status['server']:
                for group in status['server']['groups']:
                    if group.get('stream_id') == from_stream_id:
                        # Move this group to the none stream
                        if self.set_group_stream(group['id'], none_stream_id):
                            moved_count += 1
                            client_names = [c.get('config', {}).get('name', c['id']) for c in group.get('clients', [])]
                            log(f"✓ Moved group {group['id']} ({len(client_names)} client(s): {', '.join(client_names)}) to fallback stream '{none_stream_id}'")

            if moved_count > 0:
                log(f"✓ Successfully moved {moved_count} group(s) to fallback stream")
                return True
            else:
                log(f"No clients were on stream '{from_stream_id}' - no reassignment needed")
                return True

        except Exception as e:
            log(f"ERROR: Failed to move clients to fallback stream: {e}")
            import traceback
            log(traceback.format_exc())
            return False


class SnapcastWebSocketMonitor:
    """Monitor Snapcast WebSocket for stream status updates"""

    def __init__(self, lifecycle_manager: 'StreamLifecycleManager', host: str, port: int):
        self.manager = lifecycle_manager
        self.host = host
        self.port = port
        self.ws = None
        self.ws_thread = None
        self.running = False

    def start(self):
        """Start WebSocket monitor in background thread"""
        self.running = True
        self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.ws_thread.start()
        log("WebSocket monitor started")

    def stop(self):
        """Stop WebSocket monitor"""
        self.running = False
        if self.ws:
            self.ws.close()

    def _on_message(self, ws, message):
        """Handle WebSocket message from Snapcast"""
        try:
            data = json.loads(message)

            # Check for Stream.OnUpdate notification
            if data.get("method") == "Stream.OnUpdate":
                params = data.get("params", {})
                stream_id = params.get("id")
                stream = params.get("stream", {})
                status = stream.get("status")

                # Only process updates for our Bluetooth stream
                if stream_id == BLUETOOTH_STREAM_ID and status:
                    log(f"WebSocket: Stream status update - {stream_id} = {status}")

                    if status == "idle":
                        # Stream went idle - start timeout if we're in ACTIVE state
                        self.manager.on_status_idle()
                    elif status == "playing":
                        # Stream is playing - cancel timeout if we're in TIMEOUT state
                        self.manager.on_status_playing()

        except json.JSONDecodeError:
            pass
        except Exception as e:
            log(f"WebSocket message error: {e}")

    def _on_error(self, ws, error):
        """Handle WebSocket error"""
        log(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        log("WebSocket connection closed")

        # Auto-reconnect if still running
        if self.running:
            log("Reconnecting WebSocket in 5s...")
            time.sleep(5)
            if self.running:
                self._connect()

    def _on_open(self, ws):
        """Handle WebSocket open"""
        log("WebSocket connected to Snapcast")

    def _connect(self):
        """Connect to Snapcast WebSocket"""
        url = f"ws://{self.host}:{self.port}/jsonrpc"
        self.ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )
        self.ws.run_forever()

    def _run_websocket(self):
        """Run WebSocket client (blocking)"""
        while self.running:
            try:
                self._connect()
            except Exception as e:
                log(f"WebSocket connection failed: {e}")
                if self.running:
                    time.sleep(5)


class StreamLifecycleManager:
    """Manages Bluetooth stream lifecycle based on device connection state"""

    def __init__(self, snapserver_client: SnapserverClient, idle_timeout: int = 300):
        self.client = snapserver_client
        self.idle_timeout = idle_timeout
        self.state = StreamState.IDLE
        self.state_lock = threading.Lock()
        self.timeout_timer = None

        log(f"Initialized - starting in IDLE state (timeout: {idle_timeout}s)")

    def on_device_connected(self):
        """Handle Bluetooth device connection"""
        with self.state_lock:
            if self.state == StreamState.IDLE:
                # No stream exists - create it
                log("Event: Device CONNECTED - State: IDLE → ACTIVE")
                self._add_stream()
                self.state = StreamState.ACTIVE

            elif self.state == StreamState.TIMEOUT:
                # Stream exists but in timeout - cancel removal
                log("Event: Device CONNECTED - State: TIMEOUT → ACTIVE")
                self._cancel_timeout()
                self.state = StreamState.ACTIVE

            elif self.state == StreamState.ACTIVE:
                # Stream already active
                log("Event: Device CONNECTED - State: ACTIVE (no change)")

    def on_device_disconnected(self):
        """Handle Bluetooth device disconnection"""
        with self.state_lock:
            if self.state == StreamState.ACTIVE:
                # Device disconnected - start timeout before removal
                log(f"Event: Device DISCONNECTED - State: ACTIVE → TIMEOUT ({self.idle_timeout}s)")
                self._start_timeout()
                self.state = StreamState.TIMEOUT

            elif self.state == StreamState.IDLE:
                log("Event: Device DISCONNECTED - State: IDLE (no stream to remove)")

            elif self.state == StreamState.TIMEOUT:
                log("Event: Device DISCONNECTED - State: TIMEOUT (already waiting)")

    def on_status_idle(self):
        """Handle Snapcast status change to 'idle'"""
        with self.state_lock:
            if self.state == StreamState.ACTIVE:
                # Stream went idle - start timeout before removal
                log(f"Event: Status IDLE (Snapcast) - State: ACTIVE → TIMEOUT ({self.idle_timeout}s)")
                self._start_timeout()
                self.state = StreamState.TIMEOUT
            elif self.state == StreamState.TIMEOUT:
                # Already in timeout - restart timer
                log(f"Event: Status IDLE (Snapcast) - State: TIMEOUT (restarting timer)")
                self._start_timeout()
            else:
                log(f"Event: Status IDLE (Snapcast) - State: {self.state.value} (no action)")

    def on_status_playing(self):
        """Handle Snapcast status change to 'playing'"""
        with self.state_lock:
            if self.state == StreamState.TIMEOUT:
                # Stream started playing again - cancel removal
                log("Event: Status PLAYING (Snapcast) - State: TIMEOUT → ACTIVE")
                self._cancel_timeout()
                self.state = StreamState.ACTIVE
            elif self.state == StreamState.IDLE:
                # Stream doesn't exist but Snapcast says playing - create it
                log("Event: Status PLAYING (Snapcast) - State: IDLE → ACTIVE")
                self._add_stream()
                self.state = StreamState.ACTIVE
            else:
                log(f"Event: Status PLAYING (Snapcast) - State: {self.state.value} (no action)")

    def _add_stream(self):
        """Add Bluetooth stream to Snapserver"""
        # CRITICAL: Clean up any orphaned control scripts BEFORE adding new stream
        # Snapcast doesn't clean these up automatically, and multiple control scripts
        # competing for FIFO reads causes choppy/sped-up audio
        self._cleanup_control_scripts()

        # CRITICAL: Stop FIFO keeper BEFORE adding stream to prevent multiple readers
        # If both cat and snapserver read simultaneously, audio data gets split between them
        # causing choppy/corrupt audio. Brief gap with no reader is better than two readers.
        self._stop_fifo_keeper()

        # Build stream URI - Note: Dynamic streams require controlscript in /usr/share/snapserver/plug-ins/
        # Static config can use /app/scripts/ but JSON-RPC API enforces the plug-ins directory
        stream_uri = (
            f"pipe://{BLUETOOTH_FIFO_PATH}"
            f"?name={BLUETOOTH_STREAM_ID}"
            f"&sampleformat=44100:16:2"
            f"&codec=pcm"
            f"&controlscript={BLUETOOTH_CONTROL_SCRIPT}"
        )

        # Now add stream - Snapserver will immediately start reading from FIFO
        success = self.client.add_stream(stream_uri)
        if not success:
            log("ERROR: Failed to add stream")
            # Restart fifo keeper if stream creation failed
            self._start_fifo_keeper()
            return

    def _remove_stream(self):
        """Remove Bluetooth stream from Snapserver"""
        # CRITICAL: Move all clients to fallback 'none' stream BEFORE removing this stream
        # This prevents clients from becoming orphaned when the stream disappears
        log(f"Moving clients from '{BLUETOOTH_STREAM_ID}' to fallback stream before removal...")
        self.client.move_clients_to_fallback_stream(BLUETOOTH_STREAM_ID)

        # Now remove the stream
        success = self.client.remove_stream(BLUETOOTH_STREAM_ID)
        if not success:
            log("ERROR: Failed to remove stream")

        # Kill orphaned control scripts (Snapcast doesn't clean them up)
        self._cleanup_control_scripts()

        # Start FIFO keeper to prevent bluealsa-aplay from blocking
        # DO NOT restart Bluetooth services - this causes BlueZ to lose device UUIDs
        # and prevents reconnection (devices show 0 UUIDs and get "Connection Unsuccessful")
        self._start_fifo_keeper()

    def _start_timeout(self):
        """Start timeout timer before removing stream"""
        # Cancel any existing timer
        self._cancel_timeout()

        # Start new timer
        self.timeout_timer = threading.Timer(self.idle_timeout, self._on_timeout_expired)
        self.timeout_timer.daemon = True
        self.timeout_timer.start()
        log(f"Timeout timer started ({self.idle_timeout}s)")

    def _cancel_timeout(self):
        """Cancel pending timeout timer"""
        if self.timeout_timer and self.timeout_timer.is_alive():
            self.timeout_timer.cancel()
            log("Timeout timer cancelled")
            self.timeout_timer = None

    def _on_timeout_expired(self):
        """Handle timeout expiration - remove stream"""
        with self.state_lock:
            if self.state == StreamState.TIMEOUT:
                log("Timeout expired - State: TIMEOUT → IDLE")
                self._remove_stream()
                self.state = StreamState.IDLE
            else:
                log(f"Timeout expired but state is {self.state.value} (unexpected)")

    def _stop_fifo_keeper(self):
        """Stop FIFO keeper via supervisorctl"""
        try:
            result = subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'stop', 'bluetooth-fifo-keeper'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                log("FIFO keeper stopped")
            else:
                log(f"FIFO keeper stop returned code {result.returncode}: {result.stdout} {result.stderr}")
        except Exception as e:
            log(f"Failed to stop FIFO keeper: {e}")

    def _start_fifo_keeper(self):
        """Start FIFO keeper via supervisorctl

        Uses restart instead of start to handle cases where the service
        is in a failed/stopped state and won't start with 'start' command.
        """
        try:
            # First check if it's already running
            status_result = subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'status', 'bluetooth-fifo-keeper'],
                capture_output=True,
                text=True,
                timeout=5
            )

            # Use restart to ensure it starts even if in weird state
            result = subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'restart', 'bluetooth-fifo-keeper'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0 or 'started' in result.stdout.lower():
                log("FIFO keeper started")
            else:
                log(f"FIFO keeper start returned code {result.returncode}")
                log(f"  stdout: {result.stdout.strip()}")
                log(f"  stderr: {result.stderr.strip()}")

        except Exception as e:
            log(f"Failed to start FIFO keeper: {e}")

    def _cleanup_control_scripts(self):
        """Kill orphaned Bluetooth control script processes

        Snapcast spawns control scripts when streams are dynamically added but doesn't
        clean them up when streams are removed.
        """
        try:
            # Find all bluetooth-control-script.py processes
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            killed_count = 0
            for line in result.stdout.splitlines():
                if 'bluetooth-control-script.py' in line and 'grep' not in line:
                    # Extract PID (second column in ps aux output)
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            subprocess.run(['kill', str(pid)], timeout=2)
                            killed_count += 1
                            log(f"Killed orphaned control script: PID {pid}")
                        except (ValueError, subprocess.TimeoutExpired):
                            pass

            if killed_count == 0:
                log("No orphaned control scripts found")
            else:
                log(f"Cleaned up {killed_count} orphaned control script(s)")

        except Exception as e:
            log(f"Failed to cleanup control scripts: {e}")


class BluetoothDeviceMonitor:
    """Monitor BlueZ D-Bus for Bluetooth device connections"""

    def __init__(self, lifecycle_manager: StreamLifecycleManager):
        self.manager = lifecycle_manager
        self.bus = None
        self.connected_devices = set()

        if not DBUS_AVAILABLE:
            log("[Bluetooth] D-Bus not available - monitoring disabled")
            return

        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        log("[Bluetooth] D-Bus monitor initialized")

    def _properties_changed_handler(self, interface, changed, invalidated, path):
        """Handle D-Bus PropertiesChanged signals"""
        try:
            # We're interested in Device1 interface
            if interface != 'org.bluez.Device1':
                return

            # Check if Connected property changed
            if 'Connected' in changed:
                is_connected = bool(changed['Connected'])
                log(f"[DBus] Device {path} connection state: {is_connected}")

                if is_connected:
                    # Device is connecting - check if it's A2DP or a known paired device
                    is_audio = self._is_audio_device(path)
                    is_paired = self._is_paired(path)

                    if is_audio:
                        # Device has UUIDs and is A2DP - trust and pair it to persist connection
                        # This is critical for iOS "Just Works" SSP pairing
                        self._trust_and_pair_device(path)

                        if path not in self.connected_devices:
                            self.connected_devices.add(path)
                            log(f"[DBus] A2DP device connected: {path}")
                            self.manager.on_device_connected()
                    elif is_paired:
                        # Known paired device reconnecting without UUIDs yet
                        # Accept it immediately - UUIDs will populate via UUIDs property change
                        if path not in self.connected_devices:
                            self.connected_devices.add(path)
                            log(f"[DBus] Known paired device reconnecting (UUIDs pending): {path}")
                            self.manager.on_device_connected()
                else:
                    # Device disconnecting
                    if path in self.connected_devices:
                        self.connected_devices.remove(path)
                        log(f"[DBus] Device disconnected: {path}")

                        # Only trigger disconnect if no other devices are connected
                        if not self.connected_devices:
                            self.manager.on_device_disconnected()
                        else:
                            log(f"[DBus] Other devices still connected: {len(self.connected_devices)}")

            # Check if UUIDs property changed (service discovery completed)
            # This handles the case where UUIDs are populated after connection
            if 'UUIDs' in changed:
                log(f"[DBus] Device {path} UUIDs updated")

                # Check if device is currently connected and has A2DP UUID
                if self._is_connected(path) and self._is_audio_device(path):
                    # Device is connected and now we know it's A2DP - trust and pair it
                    self._trust_and_pair_device(path)

                    # Device is connected and now we know it's A2DP
                    if path not in self.connected_devices:
                        self.connected_devices.add(path)
                        log(f"[DBus] A2DP device detected (via UUIDs update): {path}")
                        self.manager.on_device_connected()
                elif self._is_connected(path) and not self._is_audio_device(path):
                    # Device UUIDs populated but it's NOT A2DP - remove if we added it prematurely
                    if path in self.connected_devices:
                        self.connected_devices.remove(path)
                        log(f"[DBus] Device is not A2DP - removing: {path}")
                        if not self.connected_devices:
                            self.manager.on_device_disconnected()

        except Exception as e:
            log(f"[Error] Properties changed handler failed: {e}")

    def _is_connected(self, device_path: str) -> bool:
        """Check if device is currently connected"""
        try:
            device_obj = self.bus.get_object('org.bluez', device_path)
            device_props = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            return bool(device_props.Get('org.bluez.Device1', 'Connected'))
        except Exception as e:
            log(f"[Error] Failed to check device connection status: {e}")
            return False

    def _is_paired(self, device_path: str) -> bool:
        """Check if device is paired (known device)"""
        try:
            device_obj = self.bus.get_object('org.bluez', device_path)
            device_props = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            paired = bool(device_props.Get('org.bluez.Device1', 'Paired'))
            log(f"[DBus] Device {device_path} paired status: {paired}")
            return paired
        except Exception as e:
            log(f"[Error] Failed to check device paired status: {e}")
            return False

    def _is_audio_device(self, device_path: str) -> bool:
        """Check if device is an audio device (has A2DP UUID)"""
        try:
            device_obj = self.bus.get_object('org.bluez', device_path)
            device_props = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            uuids = device_props.Get('org.bluez.Device1', 'UUIDs')

            # A2DP UUID: 0000110d-0000-1000-8000-00805f9b34fb (Audio Sink)
            # A2DP Source UUID: 0000110a-0000-1000-8000-00805f9b34fb (Audio Source)
            a2dp_uuids = [
                '0000110d-0000-1000-8000-00805f9b34fb',  # A2DP Sink
                '0000110a-0000-1000-8000-00805f9b34fb',  # A2DP Source
            ]

            log(f"[DBus] Checking UUIDs for {device_path}")
            log(f"[DBus] Device has {len(uuids)} UUIDs")

            for uuid in uuids:
                uuid_str = str(uuid).lower()
                if uuid_str in a2dp_uuids:
                    log(f"[DBus] MATCH! A2DP UUID found: {uuid_str}")
                    return True

            log(f"[DBus] No A2DP UUIDs found")
            return False

        except Exception as e:
            log(f"[Error] Failed to check if device is audio: {e}")
            import traceback
            log(f"[Error] Traceback: {traceback.format_exc()}")
            return False

    def _trust_and_pair_device(self, device_path: str) -> bool:
        """Trust and pair a Bluetooth device to persist the connection

        This is necessary for "Just Works" SSP connections from iOS devices.
        We ALWAYS call Pair() even if device reports as paired, because
        iOS "Just Works" SSP creates in-memory pairing that's not persisted.
        """
        try:
            device_obj = self.bus.get_object('org.bluez', device_path)
            device_props = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            device_iface = dbus.Interface(device_obj, 'org.bluez.Device1')

            # Set Trusted property first
            is_trusted = bool(device_props.Get('org.bluez.Device1', 'Trusted'))
            if not is_trusted:
                device_props.Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
                log(f"[DBus] ✓ Device {device_path} set to trusted")

            # ALWAYS call Pair() to force BlueZ to persist to disk
            # Even if device reports as "paired", this might be in-memory only
            log(f"[DBus] Calling Pair() on {device_path} to persist pairing...")
            device_iface.Pair()
            log(f"[DBus] ✓ Device {device_path} paired and persisted to disk")

            return True

        except dbus.exceptions.DBusException as e:
            # Ignore "AlreadyExists" error - means device is already paired
            if "AlreadyExists" in str(e):
                log(f"[DBus] Device {device_path} pairing already exists (disk persisted)")
                return True
            else:
                log(f"[Error] Failed to pair device {device_path}: {e}")
                return False
        except Exception as e:
            log(f"[Error] Failed to trust/pair device {device_path}: {e}")
            return False

    def start(self):
        """Start monitoring D-Bus for Bluetooth device connections"""
        if not DBUS_AVAILABLE:
            return

        log("[Bluetooth] Starting device connection monitoring...")

        try:
            # Subscribe to PropertiesChanged signals from BlueZ
            self.bus.add_signal_receiver(
                self._properties_changed_handler,
                dbus_interface='org.freedesktop.DBus.Properties',
                signal_name='PropertiesChanged',
                path_keyword='path'
            )

            log("[Bluetooth] Subscribed to BlueZ D-Bus signals")

            # Scan for already connected devices
            self._scan_for_connected_devices()

            # Start GLib main loop in a thread
            self.loop = GLib.MainLoop()
            self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
            self.loop_thread.start()

            log("[Bluetooth] GLib main loop started")

        except Exception as e:
            log(f"[Error] Failed to start Bluetooth monitor: {e}")

    def _scan_for_connected_devices(self):
        """Scan for already connected Bluetooth audio devices"""
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
                # Look for Device1 interfaces
                if 'org.bluez.Device1' in interfaces:
                    device_props = interfaces['org.bluez.Device1']

                    # Check if device is connected and is an audio device
                    if device_props.get('Connected', False) and self._is_audio_device(str(path)):
                        self.connected_devices.add(str(path))
                        log(f"[Bluetooth] Found connected A2DP device: {path}")

            # If we found connected devices, trigger stream creation
            if self.connected_devices:
                log(f"[Bluetooth] {len(self.connected_devices)} A2DP device(s) already connected")
                self.manager.on_device_connected()

        except Exception as e:
            log(f"[Error] Device scan failed: {e}")

    def stop(self):
        """Stop monitoring"""
        if hasattr(self, 'loop'):
            self.loop.quit()


def main():
    parser = argparse.ArgumentParser(description='Bluetooth stream lifecycle manager for Snapcast')
    parser.add_argument('--snapserver-host', default='localhost', help='Snapserver host')
    parser.add_argument('--snapserver-port', type=int, default=1780, help='Snapserver port')
    parser.add_argument('--idle-timeout', type=int, default=300, help='Idle timeout in seconds')

    args = parser.parse_args()

    # Use local variables instead of modifying globals
    snapserver_host = args.snapserver_host
    snapserver_port = args.snapserver_port
    idle_timeout = args.idle_timeout

    # Read Bluetooth device name from settings for stream naming
    # Pattern: "{deviceName} Bluetooth" (e.g., "Plum Audio Bluetooth")
    device_name = "Plum Audio"  # Default fallback
    try:
        settings_file = "/app/data/settings.json"
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as f:
                settings = json.load(f)
                device_name = settings.get('integrations', {}).get('bluetooth', {}).get('deviceName', 'Plum Audio')
        print(f"[Init] Read Bluetooth device name from settings: {device_name}", file=sys.stderr)
    except Exception as e:
        print(f"[Init] Could not read settings, using default device name: {e}", file=sys.stderr)

    # Update global stream ID with custom name
    globals()['BLUETOOTH_STREAM_ID'] = f"{device_name} Bluetooth"
    print(f"[Init] Bluetooth Stream ID: {globals()['BLUETOOTH_STREAM_ID']}", file=sys.stderr)

    log("=== Bluetooth Stream Lifecycle Manager Starting ===")
    log(f"Snapserver: {snapserver_host}:{snapserver_port}")
    log(f"Idle timeout: {idle_timeout}s")
    log("Monitoring BlueZ D-Bus for A2DP connections")

    if not DBUS_AVAILABLE:
        log("ERROR: D-Bus not available - cannot monitor Bluetooth connections")
        sys.exit(1)

    # Create Snapserver client
    snapserver = SnapserverClient(snapserver_host, snapserver_port)

    # Create lifecycle manager
    lifecycle = StreamLifecycleManager(snapserver, idle_timeout)

    # Create and start WebSocket monitor (runs in background thread)
    ws_monitor = SnapcastWebSocketMonitor(lifecycle, snapserver_host, snapserver_port)
    ws_monitor.start()

    # Create and start Bluetooth device monitor
    bt_monitor = BluetoothDeviceMonitor(lifecycle)

    # Run monitor (blocks)
    try:
        bt_monitor.start()

        # Keep main thread alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        log("Shutting down...")
        ws_monitor.stop()
        bt_monitor.stop()
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        log(f"{traceback.format_exc()}")
        ws_monitor.stop()
        bt_monitor.stop()


if __name__ == "__main__":
    main()
