#!/usr/bin/env python3
"""
Stream Lifecycle Manager for Plum-Snapcast

Manages dynamic creation/removal of Snapcast streams based on source activity.
Keeps audio services (AirPlay, Spotify, etc.) always discoverable but only
creates Snapcast streams when clients are actively connected/playing.

Features:
- Metadata pipe monitoring for stream creation (pbeg detection only)
- Automatic handoff to control script after stream creation
- WebSocket monitoring for stream status and removal
- Event-driven timeout management (no polling)
- Communicates with Snapserver via JSON-RPC 2.0 (HTTP + WebSocket)

Architecture:
1. Lifecycle manager monitors metadata pipe waiting for 'pbeg' (play begin)
2. On pbeg: Creates stream, then STOPS monitoring metadata pipe
3. Control script (started by Snapserver) takes over metadata pipe for updates
4. WebSocket monitor tracks stream status (playing/idle)
5. On idle timeout: Removes stream, restarts metadata monitoring for next session

This eliminates metadata pipe conflicts between lifecycle manager and control script.
"""

import argparse
import base64
import json
import subprocess
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
STREAM_END_SIGNAL_FILE = "/tmp/airplay-stream-end.signal"


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

    def __init__(self, snapserver_client: SnapserverClient, idle_timeout: int = 300, on_stream_removed_callback=None):
        self.client = snapserver_client
        self.idle_timeout = idle_timeout
        self.state = StreamState.IDLE
        self.state_lock = threading.Lock()
        self.timeout_timer = None
        self.on_stream_removed = on_stream_removed_callback  # Called after stream is removed

        # Fallback idle detection (for when pend event isn't generated)
        self.idle_start_time = None  # Timestamp when stream first went idle
        self.idle_check_interval = 30  # Check every 30 seconds
        self.idle_check_timer = None

        # Signal file monitoring
        self.last_signal_time = 0

        log(f"Initialized - starting in IDLE state (timeout: {idle_timeout}s)")

    def on_stream_begin(self):
        """Handle pbeg (play stream begin) event"""
        with self.state_lock:
            # Reset idle counter on new connection
            self.consecutive_idle_count = 0

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
                self.consecutive_idle_count = 0  # Reset counter

            elif self.state == StreamState.IDLE:
                log("Event: Stream END (pend) - State: IDLE (no stream to remove)")

            elif self.state == StreamState.TIMEOUT:
                log("Event: Stream END (pend) - State: TIMEOUT (already waiting)")

    def on_status_idle(self):
        """Handle Snapcast status change to 'idle'

        Implements fallback timeout for when pend event isn't generated (ungraceful disconnect).
        Start tracking idle time when stream first goes idle.
        """
        with self.state_lock:
            if self.state == StreamState.ACTIVE:
                if self.idle_start_time is None:
                    # First idle event - start tracking
                    self.idle_start_time = time.time()
                    log(f"Fallback: Stream went idle, starting idle timer")
                    # Start periodic check
                    self._start_idle_check()

    def on_status_playing(self):
        """Handle Snapcast status change to 'playing'

        Resets idle timer - indicates stream is actively playing.
        If we're in TIMEOUT state, cancel the timeout and return to ACTIVE.
        """
        with self.state_lock:
            # Reset idle tracking when playing
            if self.idle_start_time is not None:
                log("Fallback: Stream playing again, cancelling idle timer")
                self.idle_start_time = None
                self._cancel_idle_check()

            # If we're in timeout but stream is playing, cancel timeout and return to ACTIVE
            if self.state == StreamState.TIMEOUT:
                log("Stream playing while in TIMEOUT - cancelling timeout, returning to ACTIVE")
                self._cancel_timeout()
                self.state = StreamState.ACTIVE

    def _start_idle_check(self):
        """Start periodic idle duration check"""
        self._cancel_idle_check()
        self.idle_check_timer = threading.Timer(self.idle_check_interval, self._check_idle_duration)
        self.idle_check_timer.daemon = True
        self.idle_check_timer.start()

    def _cancel_idle_check(self):
        """Cancel periodic idle check"""
        if self.idle_check_timer and self.idle_check_timer.is_alive():
            self.idle_check_timer.cancel()
            self.idle_check_timer = None

    def _check_idle_duration(self):
        """Check how long stream has been idle and trigger removal if needed"""
        with self.state_lock:
            if self.state == StreamState.ACTIVE and self.idle_start_time is not None:
                idle_duration = time.time() - self.idle_start_time

                if idle_duration >= self.idle_timeout:
                    # Stream has been idle for longer than timeout threshold
                    # For ungraceful disconnect (no pend event), remove immediately
                    log(f"Fallback: Stream idle for {idle_duration:.0f}s (threshold: {self.idle_timeout}s) → removing stream")
                    self.state = StreamState.IDLE
                    self.idle_start_time = None
                    self._cancel_idle_check()
                    # Remove stream directly (no additional timeout needed for ungraceful disconnect)
                    self._remove_stream()
                else:
                    # Still idle but haven't reached threshold yet - check again later
                    remaining = self.idle_timeout - idle_duration
                    log(f"Fallback: Stream idle for {idle_duration:.0f}s, checking again in {self.idle_check_interval}s (timeout in {remaining:.0f}s)")
                    self._start_idle_check()  # Schedule next check

    def _add_stream(self):
        """Add AirPlay stream to Snapserver"""
        # CRITICAL: Clean up any orphaned control scripts BEFORE adding new stream
        # Snapcast doesn't clean these up automatically, and multiple control scripts
        # competing for FIFO reads causes choppy/sped-up audio
        self._cleanup_control_scripts()

        # CRITICAL: Remove any existing AirPlay stream BEFORE adding new one
        # This prevents duplicate streams which cause multiple FIFO readers
        status = self.client.get_status()
        if status and 'server' in status and 'streams' in status['server']:
            for stream in status['server']['streams']:
                if stream['id'] == AIRPLAY_STREAM_ID:
                    log(f"WARNING: AirPlay stream already exists - removing it first")
                    self.client.remove_stream(AIRPLAY_STREAM_ID)
                    # Give snapserver time to clean up
                    time.sleep(0.5)
                    break

        # CRITICAL: Stop FIFO keeper BEFORE adding stream to prevent multiple readers
        # If both cat and snapserver read simultaneously, audio data gets split between them
        # causing choppy/corrupt audio. Brief gap with no reader is better than two readers.
        self._stop_fifo_keeper()

        # NOTE: We do NOT remove the none stream here
        # The none stream reads from /tmp/none-fifo (for HA announcements)
        # AirPlay stream reads from /tmp/snapfifo (shairport-sync output)
        # They use different FIFOs so no conflict - none stream can stay active

        # Build stream URI - Note: Dynamic streams require controlscript in /usr/share/snapserver/plug-ins/
        # Static config can use /app/scripts/ but JSON-RPC API enforces the plug-ins directory
        stream_uri = (
            f"pipe://{AIRPLAY_FIFO_PATH}"
            f"?name={AIRPLAY_STREAM_ID}"
            f"&sampleformat=44100:16:2"
            f"&codec=pcm"
            f"&controlscript={AIRPLAY_CONTROL_SCRIPT}"
        )

        # Now add stream - Snapserver will immediately start reading from FIFO
        success = self.client.add_stream(stream_uri)
        if not success:
            log("ERROR: Failed to add stream")
            # Restart fifo keeper if stream creation failed
            self._start_fifo_keeper()
            return

    def _remove_stream(self):
        """Remove AirPlay stream from Snapserver"""
        # CRITICAL: Move all clients to fallback 'none' stream BEFORE removing this stream
        # This prevents clients from becoming orphaned when the stream disappears
        log(f"Moving clients from '{AIRPLAY_STREAM_ID}' to fallback stream before removal...")
        self.client.move_clients_to_fallback_stream(AIRPLAY_STREAM_ID)

        # Now remove the stream
        success = self.client.remove_stream(AIRPLAY_STREAM_ID)
        if not success:
            log("ERROR: Failed to remove stream")

        # Kill orphaned control scripts (Snapcast doesn't clean them up)
        self._cleanup_control_scripts()

        # Restart shairport-sync to close orphaned FIFO file handles
        # This prevents choppy audio on reconnection caused by multiple readers
        log("Restarting shairport-sync to close orphaned FIFO handles...")
        try:
            # Use stop + start instead of restart for better control
            # Stop shairport-sync first
            subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'stop', 'shairport-sync'],
                capture_output=True,
                text=True,
                timeout=30
            )
            log("shairport-sync stopped")

            # Wait for clean shutdown
            time.sleep(2)

            # Start shairport-sync
            subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'start', 'shairport-sync'],
                capture_output=True,
                text=True,
                timeout=30
            )
            log("shairport-sync started")

            # Wait for full startup before continuing
            time.sleep(3)
            log("shairport-sync restart complete")
        except subprocess.TimeoutExpired as e:
            log(f"WARNING: shairport-sync restart timed out: {e}")
            log("Waiting additional time for background restart to complete...")
            # Even if we timeout, wait to ensure the operation completes
            time.sleep(10)
        except Exception as e:
            log(f"WARNING: Failed to restart shairport-sync: {e}")
            # Wait anyway to be safe
            time.sleep(5)

        # Restart FIFO keeper after removing stream (keeps pipe open for shairport-sync)
        self._start_fifo_keeper()

        # Notify metadata monitor to resume monitoring (if callback set)
        if self.on_stream_removed:
            self.on_stream_removed()

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

    def _remove_none_stream(self):
        """Remove the none stream if it exists

        The none stream (none-{hostname}) is a placeholder that reads from /tmp/snapfifo.
        When a dynamic stream (AirPlay, Spotify, etc.) connects, we remove the none stream
        to prevent multiple readers from splitting audio data.
        """
        try:
            # Check if any none-* stream exists
            status = self.client.get_status()
            if status and 'server' in status and 'streams' in status['server']:
                streams = status['server']['streams']
                none_streams = [s for s in streams if s['id'].startswith('none-')]

                for stream in none_streams:
                    stream_id = stream['id']
                    log(f"Removing none stream '{stream_id}' to prevent FIFO conflict")
                    success = self.client.remove_stream(stream_id)
                    if success:
                        log(f"Successfully removed '{stream_id}' stream")
                    else:
                        log(f"WARNING: Failed to remove '{stream_id}' stream")
        except Exception as e:
            log(f"Error checking/removing none stream: {e}")

    def _cleanup_control_scripts(self):
        """Kill orphaned AirPlay control script processes

        Snapcast spawns control scripts when streams are dynamically added but doesn't
        clean them up when streams are removed. This causes multiple control scripts
        to compete for FIFO reads, resulting in choppy audio.
        """
        import subprocess
        try:
            # Use pgrep to find airplay-control-script.py processes (more reliable than ps aux parsing)
            result = subprocess.run(
                ['pgrep', '-f', 'airplay-control-script.py'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0 and result.stdout.strip():
                # pgrep found processes - kill them all
                pids = [pid.strip() for pid in result.stdout.strip().split('\n') if pid.strip()]
                killed_count = 0

                for pid_str in pids:
                    try:
                        pid = int(pid_str)
                        subprocess.run(['kill', str(pid)], timeout=2)
                        killed_count += 1
                        log(f"Killed orphaned control script: PID {pid}")
                    except (ValueError, subprocess.TimeoutExpired) as e:
                        log(f"Failed to kill PID {pid_str}: {e}")

                log(f"Cleaned up {killed_count} orphaned control script(s)")
            else:
                log("No orphaned control scripts found")

        except Exception as e:
            log(f"Failed to cleanup control scripts: {e}")

    def _check_signal_file(self):
        """Check if control script has signaled stream end via signal file

        The control script has exclusive access to the metadata pipe and writes
        to this signal file when it detects a 'pend' event. This allows the
        lifecycle manager to know when to start the stream removal timeout.
        """
        try:
            if Path(STREAM_END_SIGNAL_FILE).exists():
                mtime = Path(STREAM_END_SIGNAL_FILE).stat().st_mtime
                if mtime > self.last_signal_time:
                    log(f"Signal: Control script signaled stream end (mtime: {mtime})")
                    self.last_signal_time = mtime
                    self.on_stream_end()
        except Exception as e:
            # Only log real errors, not missing file (expected when no signal yet)
            if Path(STREAM_END_SIGNAL_FILE).exists():
                log(f"Signal: Error checking signal file: {e}")


class MetadataMonitor:
    """Monitor shairport-sync metadata pipe for session events

    Monitors ONLY for pbeg (play begin) to detect stream start.
    After detecting pbeg and creating stream, STOPS monitoring to give
    exclusive pipe access to the control script for metadata updates.
    Resumes monitoring after stream is removed.
    """

    def __init__(self, lifecycle_manager: StreamLifecycleManager):
        self.manager = lifecycle_manager
        self.should_stop = False
        self.pipe_handle = None

    def reset(self):
        """Reset monitor state to resume monitoring after stream removal"""
        self.should_stop = False
        self.pipe_handle = None
        log("Metadata: Monitor reset - ready to detect next pbeg")

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
            # We ONLY monitor for pbeg to detect stream start
            # After stream created, control script takes over metadata pipe
            if item_type == "ssnc":
                if code == "pbeg":
                    # Play stream begin - client connected
                    log("Metadata: pbeg (play stream begin)")
                    self.manager.on_stream_begin()

                    # CRITICAL: Stop monitoring metadata pipe immediately after pbeg
                    # This gives exclusive access to the control script for metadata updates
                    log("Metadata: Stopping pipe monitoring - handing off to control script")
                    self.should_stop = True
                    return  # Exit parse_item immediately

                # Note: We do NOT monitor pend, disc, or mden here
                # Control script and WebSocket monitoring handle stream end detection
                # This prevents metadata pipe conflicts

        except ET.ParseError:
            # Expected when buffer cuts mid-XML
            pass
        except Exception as e:
            log(f"Parse error: {e}")

    def run(self):
        """Monitor metadata pipe until pbeg detected, then hand off to control script"""
        log(f"Starting metadata monitor: {METADATA_PIPE}")

        # Wait for pipe
        while not Path(METADATA_PIPE).exists():
            log(f"Waiting for metadata pipe: {METADATA_PIPE}")
            time.sleep(1)

        log(f"Metadata pipe found: {METADATA_PIPE}")

        # Read pipe line-by-line until we detect pbeg
        tmp = ""
        try:
            while not self.should_stop:
                log("Metadata: Opening pipe for reading...")
                with open(METADATA_PIPE, 'r') as pipe:
                    self.pipe_handle = pipe
                    log("Metadata: Pipe opened, reading lines...")
                    line_count = 0
                    for line in pipe:
                        line_count += 1
                        if line_count % 100 == 0:
                            log(f"Metadata: Read {line_count} lines so far...")
                        # Check if we should stop (pbeg detected)
                        if self.should_stop:
                            log("Metadata: Exiting pipe monitor (pbeg detected)")
                            self.pipe_handle = None
                            return

                        strip_line = line.strip()

                        if strip_line.endswith("</item>"):
                            # Complete item
                            item_xml = tmp + strip_line
                            self.parse_item(item_xml)
                            tmp = ""

                            # Check again after parsing (parse_item may set should_stop)
                            if self.should_stop:
                                log("Metadata: Exiting pipe monitor (pbeg detected)")
                                self.pipe_handle = None
                                return

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
    log(f"Strategy: Metadata pipe monitoring for pbeg detection")
    log(f"          Control script handles metadata updates")
    log(f"          WebSocket monitoring for stream removal")

    # Create Snapserver client
    snapserver = SnapserverClient(snapserver_host, snapserver_port)

    # Create metadata monitor
    monitor = MetadataMonitor(None)  # Will set lifecycle manager below

    # Create lifecycle manager with callback to restart metadata monitoring
    def on_stream_removed():
        """Called when stream is removed - restart metadata monitoring"""
        log("Stream removed - restarting metadata monitor for next session")
        monitor.reset()
        # Run monitor in background thread (non-blocking)
        import threading

        def monitor_with_exception_handling():
            try:
                log("Metadata monitor thread starting...")
                monitor.run()
                log("Metadata monitor thread exited normally")
            except Exception as e:
                log(f"ERROR: Metadata monitor thread crashed: {e}")
                import traceback
                log(f"Traceback: {traceback.format_exc()}")

        monitor_thread = threading.Thread(target=monitor_with_exception_handling, daemon=True)
        monitor_thread.start()
        log("Metadata monitor thread started in background")

    lifecycle = StreamLifecycleManager(snapserver, idle_timeout, on_stream_removed_callback=on_stream_removed)
    monitor.manager = lifecycle  # Set the lifecycle manager reference

    # Create and start WebSocket monitor (runs in background thread)
    ws_monitor = SnapcastWebSocketMonitor(lifecycle, snapserver_host, snapserver_port)
    ws_monitor.start()

    # Run initial metadata monitor (blocks until pbeg detected)
    try:
        log("Starting initial metadata monitor (waiting for pbeg)...")
        monitor.run()

        # After pbeg detected and stream created, keep main thread alive
        # WebSocket monitor handles stream status, metadata monitor will restart on stream removal
        # Main loop monitors signal file for stream end events from control script
        log("Metadata monitor handed off to control script")
        log("WebSocket monitor active - waiting for stream lifecycle events")
        log("Signal file monitor active - checking for control script signals")

        while True:
            # Check signal file for stream end events (control script has metadata pipe access)
            lifecycle._check_signal_file()
            time.sleep(1)  # Check every second for responsive timeout triggers

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
