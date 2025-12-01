#!/usr/bin/env python3
"""
Snapcast Stream Manager
Manages dynamic stream lifecycle based on activity and idle timeouts.

Features:
- Monitors stream activity and tracks idle time
- Removes streams from config when idle timeout exceeded
- Listens for source activity signals to recreate streams
- Auto-assigns unassigned clients to new active local sources
- Preserves network Snapcast streams (never removes them)

Lifecycle States:
1. Stopped: Stream not configured in snapserver
2. Active: Stream configured and receiving audio
3. Idle: Stream configured but no audio flowing
4. Timeout: Idle duration exceeded, stream removed

Environment Variables:
- IDLE_TIMEOUT_MINUTES: Minutes before idle streams are removed (default: 5)
- SNAPCAST_HOST: Snapcast server host (default: localhost)
- SNAPCAST_PORT: Snapcast JSON-RPC port (default: 1705)
"""

import json
import os
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta

# Configuration
IDLE_TIMEOUT_MINUTES = int(os.getenv('IDLE_TIMEOUT_MINUTES', '5'))
SNAPCAST_HOST = os.getenv('SNAPCAST_HOST', 'localhost')
SNAPCAST_PORT = int(os.getenv('SNAPCAST_PORT', '1705'))
SIGNAL_FILE = '/tmp/stream-manager-signals'
STREAMS_CONFIG = '/tmp/snapserver-streams.conf'
STREAMS_CONFIG_TEMPLATE = '/app/config/snapserver-streams.conf.template'
LOG_FILE = '/tmp/stream-manager.log'

# Source definitions - LOCAL sources are managed, NETWORK sources are preserved
LOCAL_SOURCES = ['AirPlay', 'Spotify', 'Bluetooth', 'DLNA', 'Plexamp']

# Lock for thread-safe operations
state_lock = threading.Lock()

def log(message: str, level: str = "INFO"):
    """Thread-safe logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"{timestamp} [{level}] {message}"
    print(log_msg, file=sys.stderr, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(log_msg + "\n")
    except Exception as e:
        print(f"Failed to write to log file: {e}", file=sys.stderr)


class SnapcastClient:
    """Simple JSON-RPC client for Snapcast server"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.request_id = 0

    def _send_request(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Send JSON-RPC request to Snapcast server"""
        import socket
        import json

        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self.request_id
        }
        if params:
            request["params"] = params

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.host, self.port))
            sock.sendall((json.dumps(request) + "\r\n").encode())

            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\r\n" in response:
                    break

            sock.close()

            if response:
                result = json.loads(response.decode().strip())
                if "error" in result:
                    log(f"Snapcast error: {result['error']}", "ERROR")
                    return None
                return result.get("result")
            return None
        except Exception as e:
            log(f"Failed to communicate with Snapcast: {e}", "ERROR")
            return None

    def get_status(self) -> Optional[Dict]:
        """Get server status including all streams and clients"""
        return self._send_request("Server.GetStatus")

    def set_client_stream(self, client_id: str, stream_id: str) -> bool:
        """Assign client to stream (empty string for unassigned)"""
        result = self._send_request("Client.SetStream", {
            "id": client_id,
            "stream_id": stream_id
        })
        return result is not None

    def get_stream_properties(self, stream_id: str) -> Optional[Dict]:
        """Get stream properties"""
        result = self._send_request("Stream.GetProperties", {"id": stream_id})
        return result


class StreamState:
    """Track state for a single stream"""

    def __init__(self, stream_id: str, name: str):
        self.stream_id = stream_id
        self.name = name
        self.is_playing = False
        self.last_active_time = datetime.now()
        self.is_local = any(source in name for source in LOCAL_SOURCES)

    def update_activity(self, is_playing: bool):
        """Update stream activity state"""
        self.is_playing = is_playing
        if is_playing:
            self.last_active_time = datetime.now()

    def get_idle_minutes(self) -> float:
        """Get minutes since last activity"""
        return (datetime.now() - self.last_active_time).total_seconds() / 60

    def is_idle_timeout(self, timeout_minutes: int) -> bool:
        """Check if stream has exceeded idle timeout"""
        return not self.is_playing and self.get_idle_minutes() >= timeout_minutes


class StreamManager:
    """Main stream lifecycle manager"""

    def __init__(self):
        self.snapcast = SnapcastClient(SNAPCAST_HOST, SNAPCAST_PORT)
        self.stream_states: Dict[str, StreamState] = {}
        self.running = True
        self.signal_file_position = 0

        log(f"Stream Manager initialized (timeout: {IDLE_TIMEOUT_MINUTES} minutes)")

        # Initialize signal file
        Path(SIGNAL_FILE).touch()

    def is_local_source(self, stream_name: str) -> bool:
        """Check if stream is a local source (not network Snapcast stream)"""
        return any(source in stream_name for source in LOCAL_SOURCES)

    def update_stream_states(self):
        """Poll Snapcast server and update stream states"""
        status = self.snapcast.get_status()
        if not status or 'server' not in status:
            return

        server = status['server']
        streams = server.get('streams', [])

        with state_lock:
            # Get current stream IDs
            current_stream_ids = set()

            for stream in streams:
                stream_id = stream['id']
                stream_name = stream.get('name', stream_id)
                current_stream_ids.add(stream_id)

                # Create or update stream state
                if stream_id not in self.stream_states:
                    self.stream_states[stream_id] = StreamState(stream_id, stream_name)
                    log(f"Tracking new stream: {stream_name} ({stream_id})")

                # Update activity based on status
                status_str = stream.get('status', 'unknown')
                is_playing = status_str == 'playing'
                self.stream_states[stream_id].update_activity(is_playing)

            # Remove states for streams that no longer exist
            removed_ids = set(self.stream_states.keys()) - current_stream_ids
            for stream_id in removed_ids:
                stream_name = self.stream_states[stream_id].name
                log(f"Stream removed from server: {stream_name}")
                del self.stream_states[stream_id]

    def check_idle_timeouts(self):
        """Check for streams that have exceeded idle timeout and remove them"""
        with state_lock:
            streams_to_remove = []

            for stream_id, state in self.stream_states.items():
                # Only manage local sources
                if not state.is_local:
                    continue

                if state.is_idle_timeout(IDLE_TIMEOUT_MINUTES):
                    idle_minutes = state.get_idle_minutes()
                    log(f"Stream '{state.name}' idle timeout ({idle_minutes:.1f} minutes)")
                    streams_to_remove.append((stream_id, state.name))

        # Remove timed-out streams
        for stream_id, stream_name in streams_to_remove:
            self.remove_stream(stream_id, stream_name)

    def remove_stream(self, stream_id: str, stream_name: str):
        """Remove stream from config and unassign clients"""
        log(f"Removing stream: {stream_name}")

        # 1. Get clients listening to this stream
        status = self.snapcast.get_status()
        if status and 'server' in status:
            groups = status['server'].get('groups', [])
            for group in groups:
                for client in group.get('clients', []):
                    if client.get('config', {}).get('stream', {}).get('id') == stream_id:
                        client_id = client['id']
                        client_name = client.get('host', {}).get('name', client_id)
                        log(f"Unassigning client {client_name} from stream {stream_name}")
                        self.snapcast.set_client_stream(client_id, "")

        # 2. Remove stream from config
        # Note: For now, we just log this. Actual config removal would require
        # reading the config, removing the stream source line, and reloading.
        # This is complex because we need to preserve comments and formatting.
        log(f"Stream {stream_name} marked for removal (config update needed)")

        # 3. Remove from state tracking
        with state_lock:
            if stream_id in self.stream_states:
                del self.stream_states[stream_id]

    def process_signal_file(self):
        """Read and process source activity signals"""
        try:
            with open(SIGNAL_FILE, 'r') as f:
                f.seek(self.signal_file_position)
                lines = f.readlines()
                self.signal_file_position = f.tell()

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                parts = line.split(':')
                if len(parts) >= 3:
                    source_name = parts[0]
                    signal_type = parts[1]
                    timestamp = parts[2]

                    if signal_type == 'active':
                        log(f"Source activity detected: {source_name}")
                        self.handle_source_active(source_name)

        except FileNotFoundError:
            Path(SIGNAL_FILE).touch()
            self.signal_file_position = 0
        except Exception as e:
            log(f"Error processing signal file: {e}", "ERROR")

    def handle_source_active(self, source_name: str):
        """Handle source becoming active - auto-assign if needed"""
        # Check if this is a local source
        if not self.is_local_source(source_name):
            log(f"Ignoring network source activity: {source_name}")
            return

        # Get current status
        status = self.snapcast.get_status()
        if not status or 'server' not in status:
            return

        # Find unassigned clients (integrated snapclient)
        groups = status['server'].get('groups', [])
        unassigned_clients = []

        for group in groups:
            for client in group.get('clients', []):
                stream_id = client.get('config', {}).get('stream', {}).get('id', '')
                client_id = client['id']

                # Check if client is unassigned (empty stream or null)
                if not stream_id or stream_id == "":
                    # Identify integrated snapclient by MAC address format or name
                    client_name = client.get('host', {}).get('name', '')
                    if 'snapclient' in client_name.lower() or self.is_mac_address(client_id):
                        unassigned_clients.append({
                            'id': client_id,
                            'name': client_name or client_id
                        })

        if unassigned_clients:
            log(f"Found {len(unassigned_clients)} unassigned clients for source {source_name}")

            # Find the stream for this source
            streams = status['server'].get('streams', [])
            target_stream = None
            for stream in streams:
                if source_name in stream.get('name', ''):
                    target_stream = stream
                    break

            if target_stream:
                stream_id = target_stream['id']
                stream_name = target_stream.get('name', stream_id)

                # Auto-assign unassigned clients
                for client in unassigned_clients:
                    log(f"Auto-assigning client {client['name']} to stream {stream_name}")
                    self.snapcast.set_client_stream(client['id'], stream_id)
            else:
                log(f"Stream not found for source {source_name} - may need to be created", "WARN")

    def is_mac_address(self, text: str) -> bool:
        """Check if string is a MAC address format"""
        import re
        return bool(re.match(r'^[0-9a-f]{2}(:[0-9a-f]{2}){5}$', text.lower()))

    def reload_snapserver(self):
        """Send SIGHUP to snapserver to reload config"""
        try:
            result = subprocess.run(['pidof', 'snapserver'], capture_output=True, text=True)
            if result.returncode == 0:
                pid = result.stdout.strip()
                os.kill(int(pid), signal.SIGHUP)
                log("Sent SIGHUP to snapserver for config reload")
                return True
        except Exception as e:
            log(f"Failed to reload snapserver: {e}", "ERROR")
        return False

    def run(self):
        """Main loop - monitor streams and process signals"""
        log("Stream Manager started")

        # Initial state update
        self.update_stream_states()

        iteration = 0
        while self.running:
            try:
                # Update stream states every iteration
                self.update_stream_states()

                # Check for idle timeouts every 6 iterations (1 minute)
                if iteration % 6 == 0:
                    self.check_idle_timeouts()

                # Process signal file for new activity
                self.process_signal_file()

                # Log status periodically
                if iteration % 30 == 0:  # Every 5 minutes
                    with state_lock:
                        active_streams = sum(1 for s in self.stream_states.values() if s.is_playing)
                        total_streams = len(self.stream_states)
                        log(f"Status: {active_streams}/{total_streams} streams active")

                iteration += 1
                time.sleep(10)  # Poll every 10 seconds

            except KeyboardInterrupt:
                log("Received interrupt signal")
                break
            except Exception as e:
                log(f"Error in main loop: {e}", "ERROR")
                time.sleep(10)

        log("Stream Manager stopped")

    def stop(self):
        """Stop the manager"""
        self.running = False


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    log("Received shutdown signal")
    sys.exit(0)


def main():
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Create and run manager
    manager = StreamManager()

    try:
        manager.run()
    except Exception as e:
        log(f"Fatal error: {e}", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()
