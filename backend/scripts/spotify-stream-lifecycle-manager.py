#!/usr/bin/env python3
"""
Spotify Stream Lifecycle Manager for Plum-Snapcast

Manages dynamic creation/removal of Snapcast Spotify stream based on playback state.
Keeps Spotify Connect always discoverable/available but only creates Snapcast stream
when audio is actively playing.

Features:
- Monitors spotifyd D-Bus MPRIS interface for PlaybackStatus changes
- Adds Spotify stream to Snapserver when playback starts (Playing)
- Removes stream after idle timeout when playback stops (Paused/Stopped)
- Event-driven timeout management (no polling)
- Communicates with Snapserver via JSON-RPC 2.0 (HTTP + WebSocket)
- Coordinates with FIFO keeper to prevent spotifyd blocking
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
    print("[Warning] D-Bus not available - Spotify lifecycle management disabled", file=sys.stderr)

# Configuration
SNAPSERVER_HOST = "localhost"
SNAPSERVER_PORT = 1780
LOG_FILE = "/tmp/spotify-stream-lifecycle-manager.log"

# Timeout configuration (in seconds)
IDLE_TIMEOUT = 300  # 5 minutes - time to wait after playback stops before removing stream

# Stream configuration
SPOTIFY_STREAM_ID = "Spotify"
SPOTIFY_FIFO_PATH = "/tmp/spotifyfifo"
SPOTIFY_CONTROL_SCRIPT = "/usr/share/snapserver/plug-ins/spotify-control-script.py"


class StreamState(Enum):
    """Stream lifecycle states"""
    IDLE = "idle"           # No stream exists, no playback
    ACTIVE = "active"       # Stream exists, actively playing
    TIMEOUT = "timeout"     # Playback stopped, waiting before removal


def log(message: str):
    """Log to both stderr and a file"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"{timestamp} [Spotify-Lifecycle] {message}"
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

                # Only process updates for our Spotify stream
                if stream_id == SPOTIFY_STREAM_ID and status:
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
    """Manages Spotify stream lifecycle based on playback state"""

    def __init__(self, snapserver_client: SnapserverClient, idle_timeout: int = 300, instance_id: Optional[str] = None):
        self.client = snapserver_client
        self.idle_timeout = idle_timeout
        self.state = StreamState.IDLE
        self.state_lock = threading.Lock()
        self.timeout_timer = None
        self.instance_id = instance_id  # Instance ID for multi-instance mode

        log(f"Initialized - starting in IDLE state (timeout: {idle_timeout}s)")

    def on_playback_started(self):
        """Handle spotifyd playback started (Playing)"""
        with self.state_lock:
            if self.state == StreamState.IDLE:
                # No stream exists - create it
                log("Event: Playback STARTED - State: IDLE → ACTIVE")
                self._add_stream()
                self.state = StreamState.ACTIVE

            elif self.state == StreamState.TIMEOUT:
                # Stream exists but in timeout - cancel removal
                log("Event: Playback STARTED - State: TIMEOUT → ACTIVE")
                self._cancel_timeout()
                self.state = StreamState.ACTIVE

            elif self.state == StreamState.ACTIVE:
                # Stream already active
                log("Event: Playback STARTED - State: ACTIVE (no change)")

    def on_playback_stopped(self):
        """Handle spotifyd playback stopped (Paused/Stopped)"""
        with self.state_lock:
            if self.state == StreamState.ACTIVE:
                # Playback stopped - start timeout before removal
                log(f"Event: Playback STOPPED - State: ACTIVE → TIMEOUT ({self.idle_timeout}s)")
                self._start_timeout()
                self.state = StreamState.TIMEOUT

            elif self.state == StreamState.IDLE:
                log("Event: Playback STOPPED - State: IDLE (no stream to remove)")

            elif self.state == StreamState.TIMEOUT:
                log("Event: Playback STOPPED - State: TIMEOUT (already waiting)")

    def on_status_idle(self):
        """Handle Snapcast status change to 'idle' - DISABLED

        WebSocket status monitoring is disabled for Spotify because Snapserver reports
        unstable status during active streaming (rapid idle/playing flips), causing
        state thrashing. We rely exclusively on D-Bus MPRIS events (PlaybackStatus)
        which are reliable and only fire on actual playback state changes.
        """
        # DISABLED - do nothing
        pass

    def on_status_playing(self):
        """Handle Snapcast status change to 'playing' - DISABLED

        WebSocket status monitoring is disabled for Spotify because Snapserver reports
        unstable status during active streaming (rapid idle/playing flips), causing
        state thrashing. We rely exclusively on D-Bus MPRIS events (PlaybackStatus)
        which are reliable and only fire on actual playback state changes.
        """
        # DISABLED - do nothing
        pass

    def _add_stream(self):
        """Add Spotify stream to Snapserver"""
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
            f"pipe://{SPOTIFY_FIFO_PATH}"
            f"?name={SPOTIFY_STREAM_ID}"
            f"&sampleformat=44100:16:2"
            f"&codec=pcm"
            f"&controlscript={SPOTIFY_CONTROL_SCRIPT}"
        )

        # Now add stream - Snapserver will immediately start reading from FIFO
        success = self.client.add_stream(stream_uri)
        if not success:
            log("ERROR: Failed to add stream")
            # Restart fifo keeper if stream creation failed
            self._start_fifo_keeper()
            return

    def _remove_stream(self):
        """Remove Spotify stream from Snapserver"""
        # CRITICAL: Move all clients to fallback 'none' stream BEFORE removing this stream
        # This prevents clients from becoming orphaned when the stream disappears
        log(f"Moving clients from '{SPOTIFY_STREAM_ID}' to fallback stream before removal...")
        self.client.move_clients_to_fallback_stream(SPOTIFY_STREAM_ID)

        # Now remove the stream
        success = self.client.remove_stream(SPOTIFY_STREAM_ID)
        if not success:
            log("ERROR: Failed to remove stream")

        # Kill orphaned control scripts (Snapcast doesn't clean them up)
        self._cleanup_control_scripts()

        # Start FIFO keeper to prevent spotifyd from blocking
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
            # Use instance-aware service name if in multi-instance mode
            if self.instance_id:
                service_name = f'spotify-{self.instance_id}-fifo-keeper'
            else:
                service_name = 'spotify-fifo-keeper'

            result = subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'stop', service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                log(f"FIFO keeper stopped ({service_name})")
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
            # Use instance-aware service name if in multi-instance mode
            if self.instance_id:
                service_name = f'spotify-{self.instance_id}-fifo-keeper'
            else:
                service_name = 'spotify-fifo-keeper'

            # First check if it's already running
            status_result = subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'status', service_name],
                capture_output=True,
                text=True,
                timeout=5
            )

            # Use restart to ensure it starts even if in weird state
            result = subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'restart', service_name],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0 or 'started' in result.stdout.lower():
                log(f"FIFO keeper started ({service_name})")
            else:
                log(f"FIFO keeper start returned code {result.returncode}")
                log(f"  stdout: {result.stdout.strip()}")
                log(f"  stderr: {result.stderr.strip()}")

        except Exception as e:
            log(f"Failed to start FIFO keeper: {e}")

    def _cleanup_control_scripts(self):
        """Kill orphaned Spotify control script processes

        Snapcast spawns control scripts when streams are dynamically added but doesn't
        clean them up when streams are removed. This causes multiple control scripts
        to compete for FIFO reads, resulting in choppy audio.
        """
        try:
            # Use pgrep to find spotify-control-script processes
            # Wrapper scripts exec the main script with --instance-id parameter
            # So actual running process is: spotify-control-script.py --instance-id N
            if self.instance_id:
                search_pattern = f'spotify-control-script.py.*--instance-id {self.instance_id}'
            else:
                # Single-instance mode: match main script without instance-id
                search_pattern = 'spotify-control-script.py'

            log(f"Searching for orphaned control scripts: '{search_pattern}'")
            result = subprocess.run(
                ['pgrep', '-f', search_pattern],
                capture_output=True,
                text=True,
                timeout=5
            )

            killed_count = 0
            if result.returncode == 0 and result.stdout.strip():
                pids = [pid.strip() for pid in result.stdout.strip().split('\n') if pid.strip()]
                for pid_str in pids:
                    try:
                        pid = int(pid_str)
                        # Use SIGKILL (-9) for immediate termination
                        subprocess.run(['kill', '-9', str(pid)], timeout=2)
                        killed_count += 1
                        log(f"Killed orphaned control script: PID {pid}")
                    except (ValueError, subprocess.TimeoutExpired) as e:
                        log(f"Failed to kill PID {pid_str}: {e}")

            if killed_count == 0:
                log("No orphaned control scripts found")
            else:
                log(f"Cleaned up {killed_count} orphaned control script(s)")

        except Exception as e:
            log(f"Failed to cleanup control scripts: {e}")


class SpotifyPlaybackMonitor:
    """Monitor spotifyd D-Bus MPRIS interface for playback state changes"""

    def __init__(self, lifecycle_manager: StreamLifecycleManager):
        self.manager = lifecycle_manager
        self.bus = None
        self.current_playback_status = None

        if not DBUS_AVAILABLE:
            log("[Spotify] D-Bus not available - monitoring disabled")
            return

        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        # Use session bus if available, otherwise system bus
        try:
            self.bus = dbus.SessionBus()
            log("[Spotify] D-Bus monitor initialized (Session Bus)")
        except:
            try:
                self.bus = dbus.SystemBus()
                log("[Spotify] D-Bus monitor initialized (System Bus)")
            except:
                log("[Spotify] Failed to connect to any D-Bus")
                self.bus = None

    def _properties_changed_handler(self, interface, changed, invalidated, sender):
        """Handle D-Bus PropertiesChanged signals"""
        try:
            # We're interested in MediaPlayer2.Player interface
            if interface != 'org.mpris.MediaPlayer2.Player':
                return

            # Check if PlaybackStatus property changed
            if 'PlaybackStatus' in changed:
                playback_status = str(changed['PlaybackStatus']).lower()
                log(f"[DBus] PlaybackStatus changed: {playback_status}")

                if playback_status == 'playing':
                    # Playback started
                    if self.current_playback_status != 'playing':
                        self.current_playback_status = 'playing'
                        log(f"[DBus] Spotify started playing")
                        self.manager.on_playback_started()
                elif playback_status in ['paused', 'stopped']:
                    # Playback stopped
                    if self.current_playback_status == 'playing':
                        self.current_playback_status = playback_status
                        log(f"[DBus] Spotify stopped/paused")
                        self.manager.on_playback_stopped()

        except Exception as e:
            log(f"[Error] Properties changed handler failed: {e}")

    def _scan_for_players(self):
        """Scan for existing spotifyd player on D-Bus"""
        if not self.bus:
            return

        try:
            # Get list of all D-Bus names
            bus_proxy = self.bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus')
            bus_interface = dbus.Interface(bus_proxy, 'org.freedesktop.DBus')
            all_names = bus_interface.ListNames()

            # Look for any service starting with org.mpris.MediaPlayer2.spotifyd or librespot
            prefixes = ['org.mpris.MediaPlayer2.spotifyd', 'org.mpris.MediaPlayer2.librespot']

            for name in all_names:
                for prefix in prefixes:
                    if name.startswith(prefix):
                        try:
                            player_obj = self.bus.get_object(name, '/org/mpris/MediaPlayer2')
                            player_properties = dbus.Interface(player_obj, 'org.freedesktop.DBus.Properties')

                            log(f"[DBus] ✓ Found Spotify player: {name}")

                            # Get current playback status
                            try:
                                status = player_properties.Get('org.mpris.MediaPlayer2.Player', 'PlaybackStatus')
                                playback_status = str(status).lower()
                                self.current_playback_status = playback_status
                                log(f"[DBus] Current playback status: {playback_status}")

                                # If already playing, trigger stream creation
                                if playback_status == 'playing':
                                    log(f"[DBus] Spotify already playing - creating stream")
                                    self.manager.on_playback_started()

                            except Exception as e:
                                log(f"[DBus] Failed to get current playback status: {e}")

                            return

                        except dbus.DBusException as e:
                            log(f"[DBus] Failed to connect to {name}: {e}")
                            continue

            log("[DBus] No Spotify player found yet (will monitor for connections)")

        except Exception as e:
            log(f"[Error] Player scan failed: {e}")

    def start(self):
        """Start monitoring D-Bus for Spotify playback state changes"""
        if not DBUS_AVAILABLE or not self.bus:
            return

        log("[Spotify] Starting playback state monitoring...")

        try:
            # Subscribe to PropertiesChanged signals from MPRIS
            self.bus.add_signal_receiver(
                self._properties_changed_handler,
                dbus_interface='org.freedesktop.DBus.Properties',
                signal_name='PropertiesChanged',
                sender_keyword='sender'
            )

            log("[Spotify] Subscribed to MPRIS D-Bus signals")

            # Scan for already running Spotify player
            self._scan_for_players()

            # Start GLib main loop in a thread
            self.loop = GLib.MainLoop()
            self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
            self.loop_thread.start()

            log("[Spotify] GLib main loop started")

        except Exception as e:
            log(f"[Error] Failed to start Spotify monitor: {e}")

    def stop(self):
        """Stop monitoring"""
        if hasattr(self, 'loop'):
            self.loop.quit()


def main():
    parser = argparse.ArgumentParser(description='Spotify stream lifecycle manager for Snapcast')
    parser.add_argument('--instance-id', required=False, help='Instance ID for multi-instance mode (1, 2, 3, etc.)')
    parser.add_argument('--snapserver-host', default='localhost', help='Snapserver host')
    parser.add_argument('--snapserver-port', type=int, default=1780, help='Snapserver port')
    parser.add_argument('--idle-timeout', type=int, default=300, help='Idle timeout in seconds')

    args = parser.parse_args()

    # Multi-instance support: override paths based on instance-id
    instance_id = None
    if args.instance_id:
        instance_id = args.instance_id

        # Get endpoint name from settings.json for stream display name
        endpoint_name = None
        try:
            with open('/app/data/settings.json', 'r') as f:
                settings = json.load(f)
                endpoints = settings.get('integrations', {}).get('spotify', {}).get('endpoints', [])
                for endpoint in endpoints:
                    if endpoint.get('id') == instance_id:
                        endpoint_name = endpoint.get('deviceName', f'Endpoint {instance_id}')
                        break
        except Exception as e:
            print(f"[Init] WARNING: Could not read endpoint name from settings: {e}", file=sys.stderr)
            endpoint_name = f'Endpoint {instance_id}'

        # Override module-level constants GLOBALLY for this instance
        # Use format "Spotify - [device name]" for stream display name
        globals()['SPOTIFY_STREAM_ID'] = f"Spotify - {endpoint_name}" if endpoint_name else f"Spotify-{instance_id}"
        globals()['SPOTIFY_FIFO_PATH'] = f"/tmp/spotify-{instance_id}-fifo"
        globals()['SPOTIFY_CONTROL_SCRIPT'] = f"/usr/share/snapserver/plug-ins/spotify-control-script-{instance_id}.py"
        globals()['LOG_FILE'] = f"/tmp/spotify-lifecycle-{instance_id}.log"

        print(f"[Init] Multi-instance lifecycle manager: instance={instance_id}", file=sys.stderr)
        print(f"[Init] Stream ID: {globals()['SPOTIFY_STREAM_ID']}", file=sys.stderr)
        print(f"[Init] FIFO: {globals()['SPOTIFY_FIFO_PATH']}", file=sys.stderr)
        print(f"[Init] Control Script: {globals()['SPOTIFY_CONTROL_SCRIPT']}", file=sys.stderr)

    # Use local variables instead of modifying globals
    snapserver_host = args.snapserver_host
    snapserver_port = args.snapserver_port
    idle_timeout = args.idle_timeout

    log("=== Spotify Stream Lifecycle Manager Starting ===")
    log(f"Snapserver: {snapserver_host}:{snapserver_port}")
    log(f"Idle timeout: {idle_timeout}s")
    log("Monitoring spotifyd D-Bus MPRIS for PlaybackStatus changes")

    if not DBUS_AVAILABLE:
        log("ERROR: D-Bus not available - cannot monitor Spotify playback")
        sys.exit(1)

    # Create Snapserver client
    snapserver = SnapserverClient(snapserver_host, snapserver_port)

    # Create lifecycle manager (pass instance_id for multi-instance support)
    lifecycle = StreamLifecycleManager(snapserver, idle_timeout, instance_id=instance_id)

    # Create and start WebSocket monitor (runs in background thread)
    ws_monitor = SnapcastWebSocketMonitor(lifecycle, snapserver_host, snapserver_port)
    ws_monitor.start()

    # Create and start Spotify playback monitor
    spotify_monitor = SpotifyPlaybackMonitor(lifecycle)

    # Run monitor (blocks)
    try:
        spotify_monitor.start()

        # Keep main thread alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        log("Shutting down...")
        ws_monitor.stop()
        spotify_monitor.stop()
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        log(f"{traceback.format_exc()}")
        ws_monitor.stop()
        spotify_monitor.stop()


if __name__ == "__main__":
    main()
