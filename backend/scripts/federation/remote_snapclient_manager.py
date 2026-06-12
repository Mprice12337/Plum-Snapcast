#!/usr/bin/env python3
"""
Remote Snapclient Manager

Manages dynamic snapclient instances that connect to remote Snapcast servers
and output audio to the local audio device. Enables fast stream switching
between local and remote servers without reconnection delays.

Architecture:
- Multiple snapclients run simultaneously (one local, one per remote server)
- All output to the same audio device (hw:Headphones)
- Stream routing ensures only one is active (others play 'none' stream)
- Single decode path (server → snapclient → audio)
"""

import subprocess
import time
import os
import sys
from typing import Dict, Optional, List
import signal

def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [RemoteSnapclientManager] {message}", flush=True)


class RemoteSnapclientManager:
    """
    Manages remote snapclient processes.

    Each remote snapclient connects to a different Snapcast server and
    outputs audio to the local audio device. Only one snapclient is
    "active" at a time (others are routed to 'none' stream).
    """

    # Null ALSA device written by setup.sh — lets remote snapclients register as routing
    # presence on remote servers without competing for the real audio hardware.
    NULL_DEVICE = "plum_null"

    def __init__(self, local_server_id: str, audio_device: str = "hw:Headphones", latency: int = 0, mixer_type: str = "software", mixer_name: Optional[str] = None):
        """
        Initialize remote snapclient manager.

        Args:
            local_server_id: ID of the local server (e.g., "server-192-168-201-133")
            audio_device: ALSA audio device for output (default: hw:Headphones)
            latency: Snapclient latency in milliseconds (default: 0)
            mixer_type: Mixer type (software or hardware, default: software)
            mixer_name: Hardware mixer name if mixer_type is hardware (e.g., "Digital")
        """
        self.local_server_id = local_server_id
        # Remote snapclients use a null output: their only job is to appear as a
        # routing client on the remote server. Real audio comes from the main
        # snapclient (managed by supervisord/auto-switch). Using the real device
        # causes "Resource busy" conflicts on DACs without dmix configured.
        self.audio_device = self.NULL_DEVICE
        self.latency = latency
        self.mixer_type = mixer_type
        self.mixer_name = mixer_name
        self.processes: Dict[str, subprocess.Popen] = {}  # {server_id: process}
        self.client_ids: Dict[str, str] = {}  # {server_id: snapcast_client_id}
        self.server_hosts: Dict[str, tuple] = {}  # {server_id: (host, port)}
        self._last_restart: Dict[str, float] = {}  # {server_id: timestamp}

        log(f"Initialized (local_server_id={local_server_id}, audio_device={audio_device} -> {self.audio_device}, latency={latency}, mixer={mixer_type}:{mixer_name or 'none'})")

    def add_remote_server(self, server_id: str, host: str, port: int):
        """
        Add remote server and spawn snapclient process.

        Args:
            server_id: Unique server identifier (e.g., "server-192-168-1-138")
            host: Remote server hostname or IP
            port: Remote server port (default: 1704 for snapclient)
        """
        if server_id in self.processes:
            log(f"Remote server {server_id} already exists, skipping")
            return

        log(f"Adding remote server: {server_id} ({host}:{port})")

        # Build snapclient command with unique hostID
        # Use format: remote-<local-server-id> (indicates WHERE the client is FROM)
        # When this client appears on the remote server, it will be identifiable as coming from us
        # Example: If local_server_id is "server-192-168-201-138" and we're connecting to .133,
        # the client will appear on .133's server as "remote-server-192-168-201-138"
        host_id = f"remote-{self.local_server_id}"

        cmd = [
            "/usr/bin/snapclient",
            "--host", host,
            "--port", str(port or 1704),
            "--hostID", host_id,
            "--soundcard", self.audio_device,
            "--latency", str(self.latency)
            # No --mixer: null device has no hardware mixer
        ]

        try:
            # Spawn snapclient process with logging
            # Federation service already runs as snapcast user, so subprocess inherits
            log_file = f"/tmp/remote-snapclient-{server_id}.log"
            log_fd = open(log_file, "w")

            proc = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT
            )

            self.processes[server_id] = proc
            self.server_hosts[server_id] = (host, port)
            self._last_restart[server_id] = time.time()

            log(f"Remote snapclient spawned for {server_id} (PID: {proc.pid}, log: {log_file})")

            # Wait briefly for client to connect
            time.sleep(2)

            # Query remote server to find our client ID
            # This will be implemented when we integrate with WebSocket manager
            # For now, just log that we're waiting for client to appear
            log(f"Waiting for client to appear on {server_id}...")

        except Exception as e:
            log(f"Error spawning snapclient for {server_id}: {e}")
            if server_id in self.processes:
                del self.processes[server_id]
            if server_id in self.server_hosts:
                del self.server_hosts[server_id]

    def remove_remote_server(self, server_id: str):
        """
        Remove remote server and terminate snapclient process.

        Args:
            server_id: Server identifier to remove
        """
        if server_id not in self.processes:
            log(f"Remote server {server_id} not found, skipping removal")
            return

        log(f"Removing remote server: {server_id}")

        # Terminate snapclient process
        proc = self.processes[server_id]
        try:
            proc.terminate()
            proc.wait(timeout=5)
            log(f"Remote snapclient terminated for {server_id}")
        except subprocess.TimeoutExpired:
            log(f"Force killing remote snapclient for {server_id}")
            proc.kill()
            proc.wait()
        except Exception as e:
            log(f"Error terminating snapclient for {server_id}: {e}")

        # Clean up tracking
        del self.processes[server_id]
        if server_id in self.client_ids:
            del self.client_ids[server_id]
        if server_id in self.server_hosts:
            del self.server_hosts[server_id]

        log(f"Remote server {server_id} removed")

    def restart_remote_client(self, server_id: str):
        """
        Restart remote snapclient (e.g., after connection lost).

        Args:
            server_id: Server identifier to restart
        """
        if server_id not in self.server_hosts:
            log(f"Cannot restart {server_id}: server info not found")
            return

        log(f"Restarting remote client for {server_id}")

        host, port = self.server_hosts[server_id]
        self.remove_remote_server(server_id)
        time.sleep(1)  # Brief pause before reconnect
        self.add_remote_server(server_id, host, port)

    def get_client_id(self, server_id: str) -> Optional[str]:
        """
        Get snapcast client ID for a remote server.

        Args:
            server_id: Server identifier

        Returns:
            Client ID if known, None otherwise
        """
        return self.client_ids.get(server_id)

    def set_client_id(self, server_id: str, client_id: str):
        """
        Set snapcast client ID for a remote server.

        This is called by the router after querying the remote server
        to find our client.

        Args:
            server_id: Server identifier
            client_id: Snapcast client ID
        """
        self.client_ids[server_id] = client_id
        log(f"Set client ID for {server_id}: {client_id}")

    def get_active_servers(self) -> List[str]:
        """
        Get list of currently connected remote servers.

        Returns:
            List of server IDs
        """
        return list(self.processes.keys())

    def is_process_running(self, server_id: str) -> bool:
        """
        Check if remote snapclient process is still running.

        Args:
            server_id: Server identifier

        Returns:
            True if process is running, False otherwise
        """
        if server_id not in self.processes:
            return False

        proc = self.processes[server_id]
        return proc.poll() is None

    def cleanup_all(self):
        """
        Cleanup all remote snapclient processes.

        Called on shutdown.
        """
        log("Cleaning up all remote snapclients")

        for server_id in list(self.processes.keys()):
            self.remove_remote_server(server_id)

        log("All remote snapclients cleaned up")

    def monitor_processes(self):
        """
        Monitor snapclient processes and restart if crashed.

        A 30-second per-server cooldown prevents rapid crash-restart cycles
        that occur when a snapclient connects to an idle stream (no audio for
        5s closes ALSA, which causes an XRUN Broken pipe and process exit).
        Without the cooldown, the reconnect storm triggers Server.OnUpdate
        cascades that cause resyncs and audible glitches on all clients.
        """
        now = time.time()
        for server_id in list(self.processes.keys()):
            if not self.is_process_running(server_id):
                last = self._last_restart.get(server_id, 0)
                if now - last < 30:
                    continue  # still in cooldown, don't restart yet
                log(f"Remote snapclient for {server_id} has crashed, restarting")
                self._last_restart[server_id] = now
                self.restart_remote_client(server_id)


def main():
    """Test harness for RemoteSnapclientManager"""
    log("Starting RemoteSnapclientManager test harness")

    manager = RemoteSnapclientManager()

    # Example: Add a remote server
    # manager.add_remote_server("server-192-168-1-138", "192.168.1.138", 1704)

    # Keep running and monitor processes
    try:
        while True:
            manager.monitor_processes()
            time.sleep(10)
    except KeyboardInterrupt:
        log("Shutting down")
        manager.cleanup_all()


if __name__ == "__main__":
    main()
