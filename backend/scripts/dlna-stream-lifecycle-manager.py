#!/usr/bin/env python3
"""
DLNA/UPnP Dynamic Stream Lifecycle Manager

Monitors gmrender-resurrect metadata file for DLNA/UPnP playback activity
and dynamically manages Snapcast stream creation/removal.

Architecture:
- gmrender-resurrect runs continuously (UPnP renderer discovery)
- gmrender-metadata-bridge writes /tmp/dlna-metadata.json when playback occurs
- This script monitors the metadata file for activity
- Creates Snapcast stream when playback starts
- Removes stream after idle timeout when playback stops
- Coordinates with dlna-fifo-keeper to prevent gmrender blocking

Lifecycle States:
- IDLE: No stream, monitoring for activity
- ACTIVE: Stream exists, playback occurring
- TIMEOUT: Stream exists, idle timeout counting down

Activity Detection:
- Start: Metadata file created with status="Playing"
- End: Metadata file removed or status="Stopped"
"""

import asyncio
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from enum import Enum
from pathlib import Path
from typing import Dict, Optional
import websockets

# ===== CONFIGURATION =====
DLNA_STREAM_ID = "DLNA"
DLNA_FIFO_PATH = "/tmp/dlna-fifo"
DLNA_METADATA_FILE = "/tmp/dlna-metadata.json"
DLNA_CONTROL_SCRIPT = "/usr/share/snapserver/plug-ins/dlna-control-script.py"
IDLE_TIMEOUT = 300  # 5 minutes
SNAPSERVER_HOST = "localhost"
SNAPSERVER_HTTP_PORT = 1780
SNAPSERVER_WS_PORT = 1780

# ===== LOGGING =====
def log(message: str):
    """Centralized logging with timestamp and prefix"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [DLNA-Lifecycle] {message}", file=sys.stderr, flush=True)


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
        """Send JSON-RPC request to Snapserver HTTP endpoint"""
        try:
            request_data = {
                "jsonrpc": "2.0",
                "method": method,
                "id": self.request_id,
            }
            if params:
                request_data["params"] = params

            self.request_id += 1

            req = urllib.request.Request(
                self.base_url,
                data=json.dumps(request_data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )

            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.loads(response.read().decode('utf-8'))
                if "result" in result:
                    return result["result"]
                if "error" in result:
                    log(f"[SnapRPC] Error in {method}: {result['error']}")
                    return None
                return result

        except urllib.error.URLError as e:
            log(f"[SnapRPC] Connection error for {method}: {e}")
            return None
        except Exception as e:
            log(f"[SnapRPC] Error in {method}: {e}")
            return None

    def get_status(self) -> Optional[Dict]:
        """Get server status including all streams"""
        return self._send_request("Server.GetStatus")

    def stream_exists(self, stream_id: str) -> bool:
        """Check if a stream with given ID exists"""
        status = self.get_status()
        if not status or "server" not in status:
            return False

        streams = status.get("server", {}).get("streams", [])
        return any(stream.get("id") == stream_id for stream in streams)

    def add_stream(self, stream_uri: str) -> bool:
        """
        Add a stream to Snapserver using Server.Stream.AddStream.

        Args:
            stream_uri: Full stream URI (e.g., "pipe:///tmp/dlna-fifo?name=DLNA&...")

        Returns:
            True if successful, False otherwise
        """
        try:
            log(f"[SnapRPC] Adding stream: {stream_uri}")

            result = self._send_request("Server.Stream.AddStream", {"streamUri": stream_uri})

            if result:
                log(f"[SnapRPC] Stream added successfully: {DLNA_STREAM_ID}")
                return True
            else:
                log("[SnapRPC] AddStream failed (no result)")
                return False

        except Exception as e:
            log(f"[SnapRPC] Error adding stream: {e}")
            return False

    def remove_stream(self, stream_id: str) -> bool:
        """
        Remove a stream from Snapserver using Server.Stream.RemoveStream.

        Args:
            stream_id: Stream ID to remove

        Returns:
            True if successful, False otherwise
        """
        try:
            log(f"[SnapRPC] Removing stream: {stream_id}")

            result = self._send_request("Server.Stream.RemoveStream", {"id": stream_id})

            if result is not None:  # RemoveStream returns empty result on success
                log(f"[SnapRPC] Stream removed successfully: {stream_id}")
                return True
            else:
                log(f"[SnapRPC] RemoveStream failed for {stream_id}")
                return False

        except Exception as e:
            log(f"[SnapRPC] Error removing stream: {e}")
            return False


class StreamLifecycleManager:
    """
    Manages DLNA stream lifecycle based on metadata file changes.

    States:
    - IDLE: No stream, monitoring metadata file
    - ACTIVE: Stream created, playback detected
    - TIMEOUT: Stream exists but idle, counting down to removal
    """

    def __init__(self, snapserver_client: SnapserverClient, idle_timeout: int = IDLE_TIMEOUT):
        self.snapserver = snapserver_client
        self.idle_timeout = idle_timeout
        self.state = StreamState.IDLE
        self.timeout_task: Optional[asyncio.Task] = None
        self.state_lock = threading.Lock()
        self.last_activity_time = 0

        log(f"Initialized - starting in {self.state.value.upper()} state (timeout: {idle_timeout}s)")

    def on_playback_started(self):
        """Handle playback start event"""
        with self.state_lock:
            self.last_activity_time = time.time()

            if self.state == StreamState.IDLE:
                log("[Event] Playback started → Creating stream")
                self._add_stream()
                self.state = StreamState.ACTIVE

            elif self.state == StreamState.TIMEOUT:
                log("[Event] Playback resumed → Canceling timeout")
                self._cancel_timeout()
                self.state = StreamState.ACTIVE

            elif self.state == StreamState.ACTIVE:
                log("[Event] Playback continuing (already active)")

    def on_playback_stopped(self):
        """Handle playback stop event"""
        with self.state_lock:
            if self.state == StreamState.ACTIVE:
                log(f"[Event] Playback stopped → Starting {self.idle_timeout}s idle timeout")
                self.state = StreamState.TIMEOUT
                self._start_timeout()

            elif self.state == StreamState.TIMEOUT:
                log("[Event] Playback still stopped (timeout already running)")

            elif self.state == StreamState.IDLE:
                log("[Event] Playback stopped but stream not active (ignoring)")

    def on_activity_lost(self):
        """Handle complete activity loss (metadata file removed)"""
        with self.state_lock:
            if self.state != StreamState.IDLE:
                log("[Event] Activity lost (metadata removed) → Immediate stream removal")
                self._cancel_timeout()
                self._remove_stream()
                self.state = StreamState.IDLE

    def _add_stream(self):
        """Add DLNA stream to Snapserver"""
        try:
            # CRITICAL: Clean up any orphaned control scripts BEFORE adding new stream
            # Snapcast doesn't clean these up automatically, and multiple control scripts
            # competing for FIFO reads causes choppy/sped-up audio
            self._cleanup_control_scripts()

            # Construct stream URI with DLNA-specific parameters
            # DLNA outputs 44.1kHz/16-bit stereo via gmrender's GStreamer pipeline
            stream_uri = (
                f"pipe://{DLNA_FIFO_PATH}?"
                f"name={DLNA_STREAM_ID}&"
                f"sampleformat=44100:16:2&"
                f"codec=pcm&"
                f"controlscript={DLNA_CONTROL_SCRIPT}"
            )

            if self.snapserver.add_stream(stream_uri):
                log(f"[Stream] Created: {DLNA_STREAM_ID}")
            else:
                log(f"[Stream] Failed to create: {DLNA_STREAM_ID}")

        except Exception as e:
            log(f"[Stream] Error creating stream: {e}")

    def _remove_stream(self):
        """Remove DLNA stream from Snapserver"""
        try:
            if self.snapserver.remove_stream(DLNA_STREAM_ID):
                log(f"[Stream] Removed: {DLNA_STREAM_ID}")
            else:
                log(f"[Stream] Failed to remove: {DLNA_STREAM_ID}")

        except Exception as e:
            log(f"[Stream] Error removing stream: {e}")

    def _start_timeout(self):
        """Start idle timeout countdown"""
        self._cancel_timeout()  # Cancel any existing timeout

        async def timeout_coro():
            await asyncio.sleep(self.idle_timeout)
            with self.state_lock:
                if self.state == StreamState.TIMEOUT:
                    log(f"[Timeout] {self.idle_timeout}s elapsed → Removing stream")
                    self._remove_stream()
                    self.state = StreamState.IDLE

        self.timeout_task = asyncio.create_task(timeout_coro())

    def _cancel_timeout(self):
        """Cancel idle timeout"""
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()
            log("[Timeout] Canceled")


class DLNAMetadataMonitor:
    """
    Monitors /tmp/dlna-metadata.json for DLNA activity.

    The gmrender-metadata-bridge writes this file when DLNA content is playing.
    We detect activity based on:
    - File creation/modification with playback data
    - status field: "Playing", "Paused", or "Stopped"
    - File removal (no active playback)
    """

    def __init__(self, lifecycle_manager: StreamLifecycleManager):
        self.lifecycle_manager = lifecycle_manager
        self.metadata_file = Path(DLNA_METADATA_FILE)
        self.last_mtime = 0
        self.last_playback_status = None
        self.running = False
        self.monitor_task = None

        log("[DLNA] Metadata file monitor initialized")

    async def start(self):
        """Start monitoring metadata file"""
        log("[DLNA] Starting metadata file monitoring...")
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        log("[DLNA] Metadata monitoring started")

    async def stop(self):
        """Stop monitoring"""
        log("[DLNA] Stopping metadata monitoring...")
        self.running = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        log("[DLNA] Metadata monitoring stopped")

    async def _monitor_loop(self):
        """Main monitoring loop - checks metadata file for changes"""
        while self.running:
            try:
                await self._check_metadata_file()
            except Exception as e:
                log(f"[Error] Metadata monitoring error: {e}")

            await asyncio.sleep(0.5)  # Check every 500ms

    async def _check_metadata_file(self):
        """Check metadata file for activity changes"""
        try:
            if self.metadata_file.exists():
                # Get file modification time
                mtime = self.metadata_file.stat().st_mtime

                # File has been updated
                if mtime > self.last_mtime:
                    self.last_mtime = mtime

                    # Read and parse metadata
                    try:
                        with open(self.metadata_file, 'r') as f:
                            metadata = json.load(f)

                        playback_status = metadata.get('status', 'Stopped')
                        title = metadata.get('title')

                        # Log metadata updates
                        if title:
                            log(f"[Metadata] Update: {title} [{playback_status}]")
                        else:
                            log(f"[Metadata] Update: status={playback_status}")

                        # Detect state changes
                        if playback_status != self.last_playback_status:
                            log(f"[State] Playback status changed: {self.last_playback_status} → {playback_status}")

                            if playback_status == "Playing":
                                self.lifecycle_manager.on_playback_started()
                            elif playback_status in ["Stopped", "Paused"]:
                                self.lifecycle_manager.on_playback_stopped()

                            self.last_playback_status = playback_status

                        # Even if status hasn't changed, "Playing" indicates activity
                        elif playback_status == "Playing":
                            self.lifecycle_manager.on_playback_started()

                    except json.JSONDecodeError as e:
                        log(f"[Error] Metadata file JSON parse error: {e}")
                    except Exception as e:
                        log(f"[Error] Metadata file read error: {e}")

            else:
                # Metadata file doesn't exist
                if self.last_mtime > 0:
                    # File was removed (playback ended)
                    log("[Metadata] File removed (playback ended)")
                    self.last_mtime = 0
                    self.last_playback_status = None
                    self.lifecycle_manager.on_activity_lost()

        except Exception as e:
            log(f"[Error] Metadata file check error: {e}")


class WebSocketMonitor:
    """
    Monitors Snapserver WebSocket for stream status updates.
    Provides real-time feedback on stream lifecycle events.
    """

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.ws_url = f"ws://{SNAPSERVER_HOST}:{SNAPSERVER_WS_PORT}/jsonrpc"
        self.running = False
        self.ws_task = None
        log("WebSocket monitor initialized")

    async def start(self):
        """Start WebSocket monitoring"""
        self.running = True
        self.ws_task = asyncio.create_task(self._websocket_loop())
        log("WebSocket monitor started")

    async def stop(self):
        """Stop WebSocket monitoring"""
        self.running = False
        if self.ws_task:
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass
        log("WebSocket monitor stopped")

    async def _websocket_loop(self):
        """Main WebSocket loop with reconnection"""
        while self.running:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    log("WebSocket connected to Snapcast")

                    while self.running:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=30)
                            await self._handle_message(message)
                        except asyncio.TimeoutError:
                            # Send ping to keep connection alive
                            try:
                                await websocket.ping()
                            except:
                                log("WebSocket ping failed, reconnecting...")
                                break

            except Exception as e:
                if self.running:
                    log(f"WebSocket error: {e}, reconnecting in 5s...")
                    await asyncio.sleep(5)

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            method = data.get("method", "")

            # Log relevant stream events
            if method == "Stream.OnUpdate":
                params = data.get("params", {})
                stream_id = params.get("id")
                if stream_id == self.stream_id:
                    log(f"[WebSocket] Stream updated: {self.stream_id}")

            elif method == "Server.OnUpdate":
                # Server status changed (could be stream added/removed)
                pass

        except json.JSONDecodeError:
            pass
        except Exception as e:
            log(f"[WebSocket] Message handling error: {e}")


async def main():
    """Main entry point"""
    log("=== DLNA Stream Lifecycle Manager Starting ===")
    log(f"Snapserver: {SNAPSERVER_HOST}:{SNAPSERVER_HTTP_PORT}")
    log(f"Metadata file: {DLNA_METADATA_FILE}")
    log(f"FIFO path: {DLNA_FIFO_PATH}")
    log(f"Idle timeout: {IDLE_TIMEOUT}s")
    log("Monitoring gmrender-metadata-bridge for DLNA/UPnP activity")

    # Initialize components
    snapserver_client = SnapserverClient(SNAPSERVER_HOST, SNAPSERVER_HTTP_PORT)
    lifecycle_manager = StreamLifecycleManager(snapserver_client, IDLE_TIMEOUT)
    metadata_monitor = DLNAMetadataMonitor(lifecycle_manager)
    websocket_monitor = WebSocketMonitor(DLNA_STREAM_ID)

    # Start monitors
    await metadata_monitor.start()
    await websocket_monitor.start()

    try:
        # Run until interrupted
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        log("Shutting down...")

    finally:
        # Cleanup
        await metadata_monitor.stop()
        await websocket_monitor.stop()
        log("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)
