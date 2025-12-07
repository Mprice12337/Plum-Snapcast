#!/usr/bin/env python3
"""
Stream Lifecycle Manager for Plum-Snapcast

Manages dynamic creation/removal of Snapcast streams based on source activity.
Keeps audio services (AirPlay, Spotify, etc.) always discoverable but only
creates Snapcast streams when clients are actively connected/playing.

Features:
- Monitors shairport-sync metadata pipe for session events
- Adds AirPlay stream to Snapserver when client connects (pbeg)
- Removes stream after idle timeout when client disconnects (pend)
- Communicates with Snapserver via JSON-RPC 2.0
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
AIRPLAY_CONTROL_SCRIPT = "/app/scripts/airplay-control-script.py"


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


class StreamLifecycleManager:
    """Manages AirPlay stream lifecycle based on client activity"""

    def __init__(self, snapserver_client: SnapserverClient):
        self.client = snapserver_client
        self.state = StreamState.IDLE
        self.state_lock = threading.Lock()
        self.timeout_timer = None

        log("Initialized - starting in IDLE state")

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
                log(f"Event: Stream END (pend) - State: ACTIVE → TIMEOUT ({IDLE_TIMEOUT}s)")
                self._start_timeout()
                self.state = StreamState.TIMEOUT

            elif self.state == StreamState.IDLE:
                log("Event: Stream END (pend) - State: IDLE (no stream to remove)")

            elif self.state == StreamState.TIMEOUT:
                log("Event: Stream END (pend) - State: TIMEOUT (already waiting)")

    def _add_stream(self):
        """Add AirPlay stream to Snapserver"""
        # Build stream URI with control script
        stream_uri = (
            f"pipe://{AIRPLAY_FIFO_PATH}"
            f"?name={AIRPLAY_STREAM_ID}"
            f"&sampleformat=44100:16:2"
            f"&codec=pcm"
            f"&controlscript={AIRPLAY_CONTROL_SCRIPT}"
        )

        success = self.client.add_stream(stream_uri)
        if not success:
            log("ERROR: Failed to add stream - retrying in 5s")
            # TODO: Implement retry logic

    def _remove_stream(self):
        """Remove AirPlay stream from Snapserver"""
        success = self.client.remove_stream(AIRPLAY_STREAM_ID)
        if not success:
            log("ERROR: Failed to remove stream")

    def _start_timeout(self):
        """Start timeout timer before removing stream"""
        # Cancel any existing timer
        self._cancel_timeout()

        # Start new timer
        self.timeout_timer = threading.Timer(IDLE_TIMEOUT, self._on_timeout_expired)
        self.timeout_timer.daemon = True
        self.timeout_timer.start()
        log(f"Timeout timer started ({IDLE_TIMEOUT}s)")

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
    parser.add_argument('--snapserver-host', default=SNAPSERVER_HOST, help='Snapserver host')
    parser.add_argument('--snapserver-port', type=int, default=SNAPSERVER_PORT, help='Snapserver port')
    parser.add_argument('--idle-timeout', type=int, default=IDLE_TIMEOUT, help='Idle timeout in seconds')

    args = parser.parse_args()

    # Update globals
    global SNAPSERVER_HOST, SNAPSERVER_PORT, IDLE_TIMEOUT
    SNAPSERVER_HOST = args.snapserver_host
    SNAPSERVER_PORT = args.snapserver_port
    IDLE_TIMEOUT = args.idle_timeout

    log("=== Stream Lifecycle Manager Starting ===")
    log(f"Snapserver: {SNAPSERVER_HOST}:{SNAPSERVER_PORT}")
    log(f"Idle timeout: {IDLE_TIMEOUT}s")
    log(f"Monitoring: {METADATA_PIPE}")

    # Create Snapserver client
    snapserver = SnapserverClient(SNAPSERVER_HOST, SNAPSERVER_PORT)

    # Create lifecycle manager
    lifecycle = StreamLifecycleManager(snapserver)

    # Create metadata monitor
    monitor = MetadataMonitor(lifecycle)

    # Run monitor (blocks)
    try:
        monitor.run()
    except KeyboardInterrupt:
        log("Shutting down...")
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        log(f"{traceback.format_exc()}")


if __name__ == "__main__":
    main()
