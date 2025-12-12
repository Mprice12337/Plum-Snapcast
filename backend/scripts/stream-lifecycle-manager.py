#!/usr/bin/env python3
"""
Stream Lifecycle Manager for Plum-Snapcast

Manages dynamic creation/removal of Snapcast streams based on source activity.
Keeps audio services (AirPlay, Spotify, etc.) always discoverable but only
creates Snapcast streams when clients are actively connected/playing.

Features:
- Hybrid detection approach for reliability:
  * Monitors shairport-sync metadata pipe for instant session detection (pbeg, pend, disc, mden)
  * Monitors Snapcast WebSocket for stream status changes (playing/idle)
- Adds AirPlay stream to Snapserver when client connects
- Removes stream after idle timeout when client disconnects
- Event-driven timeout management (no polling)
- Communicates with Snapserver via JSON-RPC 2.0 (HTTP + WebSocket)
"""

import argparse
import base64
import json
import sys
import threading
import time
import xml.etree.ElementTree as ET
from enum import Enum
from pathlib import Path
from typing import Optional
import http.client
import websocket

# Configuration
METADATA_PIPE = "/tmp/shairport-sync-metadata"
SNAPSERVER_HOST = "localhost"
SNAPSERVER_PORT = 1780
LOG_FILE = "/tmp/stream-lifecycle-manager.log"

# Timeout configuration (in seconds)
IDLE_TIMEOUT = 300  # 5 minutes - time to wait after stream ends before removing

# Stream configuration
AIRPLAY_STREAM_ID = "AirPlay"
AIRPLAY_FIFO_PATH = "/tmp/snapfifo"
AIRPLAY_CONTROL_SCRIPT = "/usr/share/snapserver/plug-ins/airplay-control-script.py"


class StreamState(Enum):
    """Stream lifecycle states"""
    IDLE = "idle"           # No stream exists, no client connected
    ACTIVE = "active"       # Stream exists, client connected/playing
    TIMEOUT = "timeout"     # Client disconnected, waiting before removal


def log(message: str):
    """Log to both stderr and a file"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"{timestamp} [Lifecycle] {message}"
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

                # Only process updates for our AirPlay stream
                if stream_id == AIRPLAY_STREAM_ID and status:
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
    """Manages AirPlay stream lifecycle based on client activity"""

    def __init__(self, snapserver_client: SnapserverClient, idle_timeout: int = 300):
        self.client = snapserver_client
        self.idle_timeout = idle_timeout
        self.state = StreamState.IDLE
        self.state_lock = threading.Lock()
        self.timeout_timer = None

        log(f"Initialized - starting in IDLE state (timeout: {idle_timeout}s)")

    def on_stream_begin(self):
        """Handle pbeg (play stream begin) event"""
        with self.state_lock:
            if self.state == StreamState.IDLE:
                # No stream exists - create it
                log("Event: Stream BEGIN (pbeg) - State: IDLE → ACTIVE")
                self._add_stream()
                self.state = StreamState.ACTIVE

            elif self.state == StreamState.TIMEOUT:
                # Stream exists but in timeout - cancel removal
                log("Event: Stream BEGIN (pbeg) - State: TIMEOUT → ACTIVE")
                self._cancel_timeout()
                self.state = StreamState.ACTIVE

            elif self.state == StreamState.ACTIVE:
                # Stream already active
                log("Event: Stream BEGIN (pbeg) - State: ACTIVE (no change)")

    def on_stream_end(self):
        """Handle pend (play stream end) event"""
        with self.state_lock:
            if self.state == StreamState.ACTIVE:
                # Client disconnected - start timeout before removal
                log(f"Event: Stream END (pend) - State: ACTIVE → TIMEOUT ({self.idle_timeout}s)")
                self._start_timeout()
                self.state = StreamState.TIMEOUT

            elif self.state == StreamState.IDLE:
                log("Event: Stream END (pend) - State: IDLE (no stream to remove)")

            elif self.state == StreamState.TIMEOUT:
                log("Event: Stream END (pend) - State: TIMEOUT (already waiting)")

    def on_status_idle(self):
        """Handle Snapcast status change to 'idle' - DISABLED

        WebSocket status monitoring is disabled for AirPlay because Snapserver reports
        unstable status during active streaming (rapid idle/playing flips), causing
        state thrashing and choppy audio. We rely exclusively on metadata pipe events
        (pbeg/pend) which are reliable and only fire on actual client connect/disconnect.
        """
        # DISABLED - do nothing
        pass

    def on_status_playing(self):
        """Handle Snapcast status change to 'playing' - DISABLED

        WebSocket status monitoring is disabled for AirPlay because Snapserver reports
        unstable status during active streaming (rapid idle/playing flips), causing
        state thrashing and choppy audio. We rely exclusively on metadata pipe events
        (pbeg/pend) which are reliable and only fire on actual client connect/disconnect.
        """
        # DISABLED - do nothing
        pass

    def _add_stream(self):
        """Add AirPlay stream to Snapserver"""
        # CRITICAL: Clean up any orphaned control scripts BEFORE adding new stream
        # Snapcast doesn't clean these up automatically, and multiple control scripts
        # competing for FIFO reads causes choppy/sped-up audio
        self._cleanup_control_scripts()

        # Build stream URI - Note: Dynamic streams require controlscript in /usr/share/snapserver/plug-ins/
        # Static config can use /app/scripts/ but JSON-RPC API enforces the plug-ins directory
        stream_uri = (
            f"pipe://{AIRPLAY_FIFO_PATH}"
            f"?name={AIRPLAY_STREAM_ID}"
            f"&sampleformat=44100:16:2"
            f"&codec=pcm"
            f"&controlscript={AIRPLAY_CONTROL_SCRIPT}"
        )

        # Add stream first - Snapserver will start reading from FIFO
        success = self.client.add_stream(stream_uri)
        if not success:
            log("ERROR: Failed to add stream")
            # TODO: Implement retry logic
            return

        # Now stop FIFO keeper - Snapserver has taken over as the reader
        # The keeper's current cat operation will complete and Snapserver becomes the primary reader
        self._stop_fifo_keeper()

    def _remove_stream(self):
        """Remove AirPlay stream from Snapserver"""
        success = self.client.remove_stream(AIRPLAY_STREAM_ID)
        if not success:
            log("ERROR: Failed to remove stream")

        # Kill orphaned control scripts (Snapcast doesn't clean them up)
        self._cleanup_control_scripts()

        # Restart FIFO keeper after removing stream (keeps pipe open for shairport-sync)
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
        import subprocess
        try:
            subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'stop', 'airplay-fifo-keeper'],
                capture_output=True,
                timeout=5
            )
            log("FIFO keeper stopped")
        except Exception as e:
            log(f"Failed to stop FIFO keeper: {e}")

    def _start_fifo_keeper(self):
        """Start FIFO keeper via supervisorctl"""
        import subprocess
        try:
            subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'start', 'airplay-fifo-keeper'],
                capture_output=True,
                timeout=5
            )
            log("FIFO keeper started")
        except Exception as e:
            log(f"Failed to start FIFO keeper: {e}")

    def _cleanup_control_scripts(self):
        """Kill orphaned AirPlay control script processes

        Snapcast spawns control scripts when streams are dynamically added but doesn't
        clean them up when streams are removed. This causes multiple control scripts
        to compete for FIFO reads, resulting in choppy audio.
        """
        import subprocess
        try:
            # Find all airplay-control-script.py processes
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            killed_count = 0
            for line in result.stdout.splitlines():
                if 'airplay-control-script.py' in line and 'grep' not in line:
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


class MetadataMonitor:
    """Monitor shairport-sync metadata pipe for session events"""

    def __init__(self, lifecycle_manager: StreamLifecycleManager):
        self.manager = lifecycle_manager

    def parse_item(self, item_xml: str):
        """Parse XML item and detect session events"""
        try:
            root = ET.fromstring(item_xml)

            # Extract type and code
            type_elem = root.find("type")
            code_elem = root.find("code")
            if code_elem is None:
                return

            item_type = bytes.fromhex(type_elem.text).decode('ascii', errors='ignore') if type_elem is not None else ""
            code = bytes.fromhex(code_elem.text).decode('ascii', errors='ignore')

            # Check for session control events (ssnc type)
            if item_type == "ssnc":
                if code == "pbeg":
                    # Play stream begin - client connected
                    log("Metadata: pbeg (play stream begin)")
                    self.manager.on_stream_begin()

                elif code == "pend":
                    # Play stream end - client disconnected
                    log("Metadata: pend (play stream end)")
                    self.manager.on_stream_end()

                elif code == "disc":
                    # Client disconnected (alternative to pend for abrupt disconnects)
                    log("Metadata: disc (client disconnected)")
                    self.manager.on_stream_end()

                elif code == "mden":
                    # Metadata end - session ending
                    log("Metadata: mden (metadata stream end)")
                    self.manager.on_stream_end()

        except ET.ParseError:
            # Expected when buffer cuts mid-XML
            pass
        except Exception as e:
            log(f"Parse error: {e}")

    def run(self):
        """Monitor metadata pipe"""
        log(f"Starting metadata monitor: {METADATA_PIPE}")

        # Wait for pipe
        while not Path(METADATA_PIPE).exists():
            log(f"Waiting for metadata pipe: {METADATA_PIPE}")
            time.sleep(1)

        log(f"Metadata pipe found: {METADATA_PIPE}")

        # Read pipe line-by-line
        tmp = ""
        try:
            while True:
                with open(METADATA_PIPE, 'r') as pipe:
                    for line in pipe:
                        strip_line = line.strip()

                        if strip_line.endswith("</item>"):
                            # Complete item
                            item_xml = tmp + strip_line
                            self.parse_item(item_xml)
                            tmp = ""

                        elif strip_line.startswith("<item>"):
                            # New item starting
                            if tmp:
                                # Previous item incomplete - try to close it
                                item_xml = tmp + "</item>"
                                self.parse_item(item_xml)
                            tmp = strip_line

                        else:
                            # Middle of item
                            tmp += strip_line

        except Exception as e:
            log(f"Metadata monitor crashed: {e}")
            import traceback
            log(f"{traceback.format_exc()}")


def main():
    parser = argparse.ArgumentParser(description='Stream lifecycle manager for Snapcast')
    parser.add_argument('--snapserver-host', default='localhost', help='Snapserver host')
    parser.add_argument('--snapserver-port', type=int, default=1780, help='Snapserver port')
    parser.add_argument('--idle-timeout', type=int, default=300, help='Idle timeout in seconds')

    args = parser.parse_args()

    # Use local variables instead of modifying globals
    snapserver_host = args.snapserver_host
    snapserver_port = args.snapserver_port
    idle_timeout = args.idle_timeout

    log("=== Stream Lifecycle Manager Starting ===")
    log(f"Snapserver: {snapserver_host}:{snapserver_port}")
    log(f"Idle timeout: {idle_timeout}s")
    log(f"Monitoring: {METADATA_PIPE}")

    # Create Snapserver client
    snapserver = SnapserverClient(snapserver_host, snapserver_port)

    # Create lifecycle manager
    lifecycle = StreamLifecycleManager(snapserver, idle_timeout)

    # Create and start WebSocket monitor (runs in background thread)
    ws_monitor = SnapcastWebSocketMonitor(lifecycle, snapserver_host, snapserver_port)
    ws_monitor.start()

    # Create metadata monitor
    monitor = MetadataMonitor(lifecycle)

    # Run monitor (blocks)
    try:
        monitor.run()
    except KeyboardInterrupt:
        log("Shutting down...")
        ws_monitor.stop()
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        log(f"{traceback.format_exc()}")
        ws_monitor.stop()


if __name__ == "__main__":
    main()
