#!/usr/bin/env python3
"""
Plexamp Dynamic Stream Lifecycle Manager

Monitors Plexamp playback activity via PlayQueue.json file and dynamically manages
Snapcast stream creation/removal.

Architecture:
- Plexamp runs in separate Debian sidecar container (glibc requirement)
- Plexamp writes playback state to PlayQueue.json file
- This script monitors the file for changes
- Creates Snapcast stream when playback starts
- Removes stream after idle timeout when playback stops

Lifecycle States:
- IDLE: No stream, monitoring for activity
- ACTIVE: Stream exists, playback occurring
- TIMEOUT: Stream exists, idle timeout counting down

Activity Detection:
- Start: PlayQueue.json exists and contains playback data
- End: PlayQueue.json is empty or doesn't exist
"""

import json
import os
import sys
import time
import subprocess
from enum import Enum
from typing import Dict, Optional

# ===== CONFIGURATION =====
PLEXAMP_STREAM_ID = "Plexamp"
PLEXAMP_FIFO_PATH = "/tmp/snapcast-fifos/plexamp-fifo"
PLEXAMP_CONTROL_SCRIPT = "/usr/share/snapserver/plug-ins/plexamp-control-script.py"
PLEXAMP_PLAYQUEUE_FILE = "/tmp/plexamp-state/.local/share/Plexamp/PlayQueue.json"
PLEXAMP_API_HOST = "localhost"  # Both containers use host networking
PLEXAMP_API_PORT = 32500
POLL_INTERVAL = 5  # Check file every 5 seconds
IDLE_TIMEOUT = 300  # 5 minutes
SNAPSERVER_HOST = "localhost"
SNAPSERVER_HTTP_PORT = 1780

# ===== LOGGING =====
def log(message: str):
    """Centralized logging with timestamp and prefix"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [Plexamp-Lifecycle] {message}", file=sys.stderr, flush=True)


class StreamState(Enum):
    """Stream lifecycle states"""
    IDLE = "idle"          # No stream, waiting for activity
    ACTIVE = "active"      # Stream exists, activity detected
    TIMEOUT = "timeout"    # Stream exists, idle timeout counting


class SnapserverClient:
    """
    JSON-RPC client for Snapserver HTTP API.
    Handles stream management via AddStream/RemoveStream.
    """

    def __init__(self, host: str = SNAPSERVER_HOST, port: int = SNAPSERVER_HTTP_PORT):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}/jsonrpc"
        self.request_id = 1
        log(f"Snapserver HTTP client initialized: {self.base_url}")

    def _send_request(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Send JSON-RPC request to Snapserver HTTP endpoint using curl"""
        try:
            request_data = {
                "jsonrpc": "2.0",
                "method": method,
                "id": self.request_id,
            }
            if params:
                request_data["params"] = params

            self.request_id += 1

            # Use curl to send JSON-RPC request
            result = subprocess.run(
                ['curl', '-s', '-m', '5',
                 '-H', 'Content-Type: application/json',
                 '-d', json.dumps(request_data),
                 self.base_url],
                capture_output=True,
                text=True,
                timeout=7
            )

            if result.returncode != 0:
                log(f"[SnapRPC] curl failed in {method}: code {result.returncode}")
                return None

            response = json.loads(result.stdout)
            if "result" in response:
                return response["result"]
            if "error" in response:
                log(f"[SnapRPC] Error in {method}: {response['error']}")
                return None
            return None

        except subprocess.TimeoutExpired:
            log(f"[SnapRPC] Timeout in {method}")
            return None
        except json.JSONDecodeError as e:
            log(f"[SnapRPC] JSON decode error in {method}: {e}")
            return None
        except Exception as e:
            log(f"[SnapRPC] Exception in {method}: {e}")
            return None

    def stream_exists(self, stream_id: str) -> bool:
        """Check if stream exists in Snapserver"""
        try:
            result = self._send_request("Server.GetStatus")
            if not result or "server" not in result:
                return False

            streams = result.get("server", {}).get("streams", [])
            return any(s.get("id") == stream_id for s in streams)

        except Exception as e:
            log(f"Error checking stream existence: {e}")
            return False

    def get_stream_status(self, stream_id: str) -> Optional[str]:
        """
        Get stream status from Snapserver.
        Returns status string: "idle", "playing", or None if stream doesn't exist.
        """
        try:
            result = self._send_request("Server.GetStatus")
            if not result or "server" not in result:
                return None

            streams = result.get("server", {}).get("streams", [])
            for stream in streams:
                if stream.get("id") == stream_id:
                    return stream.get("status", "unknown")

            return None

        except Exception as e:
            log(f"Error checking stream status: {e}")
            return None

    def add_stream(self, stream_id: str) -> bool:
        """Add Plexamp stream to Snapserver"""
        try:
            # CRITICAL: Clean up any orphaned control scripts BEFORE adding new stream
            # Snapcast doesn't clean these up automatically, and multiple control scripts
            # competing for FIFO reads causes choppy/sped-up audio
            self._cleanup_plexamp_control_scripts()

            # Stream URI format: pipe:///tmp/snapcast-fifos/plexamp-fifo?name=Plexamp&sampleformat=44100:16:2&codec=pcm&controlscript=/usr/share/snapserver/plug-ins/plexamp-control-script.py
            stream_uri = (
                f"pipe://{PLEXAMP_FIFO_PATH}"
                f"?name={stream_id}"
                f"&sampleformat=44100:16:2"
                f"&codec=pcm"
                f"&controlscript={PLEXAMP_CONTROL_SCRIPT}"
            )

            log(f"[AddStream] Creating Plexamp stream: {stream_uri}")
            result = self._send_request("Stream.AddStream", {"streamUri": stream_uri})

            if result:
                log(f"[AddStream] ✓ Plexamp stream created successfully")
                return True
            else:
                log(f"[AddStream] ✗ Failed to create stream (check snapserver logs)")
                return False

        except Exception as e:
            log(f"[AddStream] Exception: {e}")
            return False

    def remove_stream(self, stream_id: str) -> bool:
        """Remove Plexamp stream from Snapserver"""
        try:
            log(f"[RemoveStream] Removing Plexamp stream: {stream_id}")
            result = self._send_request("Stream.RemoveStream", {"id": stream_id})

            if result:
                log(f"[RemoveStream] ✓ Plexamp stream removed successfully")
                return True
            else:
                log(f"[RemoveStream] ✗ Failed to remove stream (check snapserver logs)")
                return False

        except Exception as e:
            log(f"[RemoveStream] Exception: {e}")
            return False

    def get_status(self) -> Optional[Dict]:
        """Get server status"""
        return self._send_request("Server.GetStatus")

    def set_group_stream(self, group_id: str, stream_id: str) -> bool:
        """Set a group's stream"""
        log(f"Setting group {group_id} to stream {stream_id}")
        result = self._send_request("Group.SetStream", {"id": group_id, "stream_id": stream_id})

        if result is not None:
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

    def _cleanup_plexamp_control_scripts(self):
        """Kill orphaned Plexamp control script processes

        Snapcast spawns control scripts when streams are dynamically added but doesn't
        clean them up when streams are removed. This causes multiple control scripts
        to compete for FIFO reads, resulting in choppy audio.
        """
        try:
            # Find all plexamp-control-script.py processes
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            killed_count = 0
            for line in result.stdout.splitlines():
                if 'plexamp-control-script.py' in line and 'grep' not in line:
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


class PlexampMonitor:
    """
    Monitors Plexamp playback state via PlayQueue.json file.
    Detects when playback starts/stops based on file content.
    """

    def __init__(self):
        self.playqueue_file = PLEXAMP_PLAYQUEUE_FILE
        # Initialize last_modified to current file mtime (or current time if file doesn't exist)
        # This ensures we only detect activity from changes AFTER monitor starts
        if os.path.exists(self.playqueue_file):
            self.last_modified = os.path.getmtime(self.playqueue_file)
            log(f"Plexamp monitor initialized: existing PlayQueue.json (mtime: {self.last_modified})")
        else:
            self.last_modified = time.time()
            log(f"Plexamp monitor initialized: no existing PlayQueue.json")
        log(f"Plexamp API: {PLEXAMP_API_HOST}:{PLEXAMP_API_PORT}")

    def get_playback_state(self) -> Optional[Dict]:
        """
        Read PlayQueue.json file and extract playback state.
        Returns dict with 'has_queue' and track info if playing, None otherwise.
        """
        try:
            # Check if file exists
            if not os.path.exists(self.playqueue_file):
                return None

            # Check if file has been modified since last check
            current_mtime = os.path.getmtime(self.playqueue_file)

            # If file hasn't been modified since last check, don't consider it new activity
            if current_mtime <= self.last_modified:
                return None

            # Update last modified time
            self.last_modified = current_mtime

            # Read and parse the file
            with open(self.playqueue_file, 'r') as f:
                data = json.load(f)

            # Extract playback info from Plexamp PlayQueue structure
            # PlayQueue.json has structure: {"version":1,"data":{"MediaContainer":{...}}}
            data_obj = data.get("data")
            if data_obj is None:
                return None
            media_container = data_obj.get("MediaContainer", {})

            # Check if there's an active queue
            queue_size = media_container.get("size", 0)
            if queue_size == 0:
                return None

            # Extract current track info if available
            metadata_list = media_container.get("Metadata", [])
            if metadata_list and len(metadata_list) > 0:
                current_track = metadata_list[0]
                title = current_track.get("title", "Unknown")
                artist = current_track.get("grandparentTitle", "Unknown Artist")
                album = current_track.get("parentTitle", "Unknown Album")

                return {
                    "has_queue": True,
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "queue_size": queue_size
                }

            # Queue exists but no metadata yet
            return {"has_queue": True, "title": "Loading...", "artist": "", "album": "", "queue_size": queue_size}

        except FileNotFoundError:
            # File doesn't exist = no playback
            return None
        except json.JSONDecodeError as e:
            # Invalid JSON = possible corruption during write, treat as inactive
            log(f"Warning: Invalid JSON in PlayQueue.json: {e}")
            return None
        except Exception as e:
            log(f"Error reading PlayQueue.json: {e}")
            return None

    def is_playing(self) -> bool:
        """
        Check if Plexamp has active playback.
        Uses PlayQueue.json file monitoring to avoid HTTP API deadlock.
        """
        playback_state = self.get_playback_state()
        return playback_state is not None and playback_state.get('has_queue', False)


class StreamLifecycleManager:
    """
    Manages stream lifecycle based on playback state.
    Coordinates stream creation/removal with idle timeout.
    """

    def __init__(self):
        self.snapserver = SnapserverClient()
        self.plexamp_monitor = PlexampMonitor()
        self.state = StreamState.IDLE
        self.idle_timer = 0
        self.stream_id = PLEXAMP_STREAM_ID
        log("Stream lifecycle manager initialized")

    def check_activity(self) -> bool:
        """
        Check if Plexamp playback is active.
        Uses Snapcast stream status to detect actual audio flow.
        """
        # Check stream status from Snapcast
        stream_status = self.snapserver.get_stream_status(self.stream_id)

        # If stream exists, use Snapcast status to determine activity
        # "idle" = no audio data flowing, "playing" = audio flowing
        if stream_status is not None:
            return stream_status != "idle"

        # If stream doesn't exist, don't check for activity
        # Stream creation is handled separately in handle_idle_state
        return False

    def check_new_activity(self) -> bool:
        """
        Check if there's NEW Plexamp activity (file modification).
        Only used in IDLE state to detect when to create stream.
        """
        playback_state = self.plexamp_monitor.get_playback_state()
        return playback_state is not None and playback_state.get('has_queue', False)

    def handle_idle_state(self):
        """Handle IDLE state: monitor for new activity"""
        # Only create stream if there's NEW activity (PlayQueue.json modified)
        if self.check_new_activity():
            log("[IDLE → ACTIVE] New playback detected, creating stream")
            if self.snapserver.add_stream(self.stream_id):
                self.state = StreamState.ACTIVE
                self.idle_timer = 0
            else:
                log("[IDLE] Failed to create stream, staying in IDLE")

    def handle_active_state(self):
        """Handle ACTIVE state: monitor for inactivity"""
        if not self.check_activity():
            log("[ACTIVE → TIMEOUT] Playback stopped, starting idle timeout")
            self.state = StreamState.TIMEOUT
            self.idle_timer = IDLE_TIMEOUT
        else:
            # Reset idle timer if still active
            self.idle_timer = 0

    def handle_timeout_state(self):
        """Handle TIMEOUT state: countdown to stream removal"""
        if self.check_activity():
            log("[TIMEOUT → ACTIVE] Playback resumed, cancelling timeout")
            self.state = StreamState.ACTIVE
            self.idle_timer = 0
            return

        self.idle_timer -= POLL_INTERVAL

        if self.idle_timer <= 0:
            log(f"[TIMEOUT → IDLE] Idle timeout expired ({IDLE_TIMEOUT}s), removing stream")
            # CRITICAL: Move all clients to fallback 'none' stream BEFORE removing this stream
            # This prevents clients from becoming orphaned when the stream disappears
            log(f"Moving clients from '{self.stream_id}' to fallback stream before removal...")
            self.snapserver.move_clients_to_fallback_stream(self.stream_id)

            # Now remove the stream
            if self.snapserver.remove_stream(self.stream_id):
                self.state = StreamState.IDLE
                self.idle_timer = 0
            else:
                log("[TIMEOUT] Failed to remove stream, retrying in next cycle")
                self.idle_timer = 10  # Retry after 10s
        else:
            remaining_mins = self.idle_timer // 60
            log(f"[TIMEOUT] Idle timeout: {remaining_mins}m {self.idle_timer % 60}s remaining")

    def run(self):
        """Main lifecycle management loop"""
        log("=" * 60)
        log("Starting Plexamp Stream Lifecycle Manager")
        log(f"Stream ID: {self.stream_id}")
        log(f"FIFO Path: {PLEXAMP_FIFO_PATH}")
        log(f"Plexamp API: {PLEXAMP_API_HOST}:{PLEXAMP_API_PORT}")
        log(f"Poll Interval: {POLL_INTERVAL}s")
        log(f"Idle Timeout: {IDLE_TIMEOUT}s")
        log("=" * 60)

        # Initial state check
        if self.snapserver.stream_exists(self.stream_id):
            log(f"[Init] Stream already exists, starting in ACTIVE state")
            self.state = StreamState.ACTIVE
        else:
            log(f"[Init] No existing stream, starting in IDLE state")
            self.state = StreamState.IDLE

        while True:
            try:
                if self.state == StreamState.IDLE:
                    self.handle_idle_state()
                elif self.state == StreamState.ACTIVE:
                    self.handle_active_state()
                elif self.state == StreamState.TIMEOUT:
                    self.handle_timeout_state()

                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                log("Received shutdown signal")
                break
            except Exception as e:
                log(f"Error in lifecycle loop: {e}")
                time.sleep(POLL_INTERVAL)

        log("Stream lifecycle manager stopped")


def main():
    """Entry point"""
    try:
        manager = StreamLifecycleManager()
        manager.run()
    except Exception as e:
        log(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
