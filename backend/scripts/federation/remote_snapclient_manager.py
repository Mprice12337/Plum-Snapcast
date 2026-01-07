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

    def __init__(self, local_server_id: str, audio_device: str = "hw:Headphones", latency: int = 0):
        """
        Initialize remote snapclient manager.

        Args:
            local_server_id: ID of the local server (e.g., "server-192-168-201-133")
            audio_device: ALSA audio device for output (default: hw:Headphones)
            latency: Snapclient latency in milliseconds (default: 0)
        """
        # Convert hw:X,Y format to default:CARD=name for remote snapclients
        # This allows ALSA's built-in dmix to handle device sharing
        self.local_server_id = local_server_id
        self.audio_device = self._convert_to_dmix_device(audio_device)
        self.latency = latency
        self.processes: Dict[str, subprocess.Popen] = {}  # {server_id: process}
        self.client_ids: Dict[str, str] = {}  # {server_id: snapcast_client_id}
        self.server_hosts: Dict[str, tuple] = {}  # {server_id: (host, port)}

        log(f"Initialized (local_server_id={local_server_id}, audio_device={audio_device} -> {self.audio_device}, latency={latency})")

    def _convert_to_dmix_device(self, audio_device: str) -> str:
        """
        Convert hw:X,Y format to default:CARD=name for dmix support.

        Remote snapclients need to use the 'default' device with explicit card
        specification to enable ALSA's dmix (device mixing), which allows multiple
        snapclient processes to share the same audio device.

        Args:
            audio_device: Device in hw:X,Y or hw:NAME format

        Returns:
            Device in default:CARD=NAME format
        """
        # Already in correct format
        if audio_device.startswith("default:"):
            return audio_device

        # Convert hw:X,Y or hw:NAME to default:CARD=NAME
        if audio_device.startswith("hw:"):
            device_spec = audio_device[3:]  # Remove "hw:" prefix

            # Map common device specifications to card names
            # hw:1,0 -> HiFiBerry DAC+ (snd_rpi_hifiberry_dacplus)
            # hw:0,0 or hw:Headphones -> bcm2835 Headphones
            if device_spec in ["1,0", "1"]:
                return "default:CARD=sndrpihifiberry"
            elif device_spec in ["0,0", "0", "Headphones"]:
                return "default:CARD=Headphones"
            elif "," in device_spec:
                # Generic hw:X,Y format - use card number
                card_num = device_spec.split(",")[0]
                return f"default:CARD={card_num}"
            else:
                # hw:NAME format - use name directly
                return f"default:CARD={device_spec}"

        # Fallback - return as-is
        log(f"Warning: Unknown audio device format '{audio_device}', using as-is")
        return audio_device

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

        Should be called periodically (e.g., every 10 seconds).
        """
        for server_id in list(self.processes.keys()):
            if not self.is_process_running(server_id):
                log(f"Remote snapclient for {server_id} has crashed, restarting")
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
