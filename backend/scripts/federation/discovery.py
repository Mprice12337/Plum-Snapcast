#!/usr/bin/env python3
"""
Avahi/mDNS Server Discovery Module
Discovers Snapcast servers on the network via Avahi
"""

import logging
import subprocess
import re
import threading
import time
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class ServerInfo:
    """Represents a discovered Snapcast server"""

    def __init__(self, host: str, port: int, name: str, txt_records: Dict[str, str] = None):
        self.host = host
        self.port = port
        self.name = name
        self.txt_records = txt_records or {}
        self.last_seen = time.time()
        self.id = f"server-{host.replace('.', '-')}"

    def __repr__(self):
        return f"ServerInfo(id={self.id}, name={self.name}, host={self.host}, port={self.port})"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "last_seen": self.last_seen
        }


class AvahiDiscovery:
    """
    Discovers Snapcast servers using Avahi/mDNS
    Looks for _snapcast-jsonrpc._tcp services
    """

    SERVICE_TYPE = "_snapcast-jsonrpc._tcp"
    SCAN_INTERVAL = 30  # Rescan every 30 seconds
    STALE_TIMEOUT = 120  # Consider server stale after 2 minutes

    def __init__(self, callback: Optional[Callable[[List[ServerInfo]], None]] = None):
        self.servers: Dict[str, ServerInfo] = {}
        self.callback = callback
        self.running = False
        self.thread = None
        self._lock = threading.Lock()

    def start(self):
        """Start background discovery thread"""
        if self.running:
            logger.warning("Discovery already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self.thread.start()
        logger.info("Avahi discovery started")

    def stop(self):
        """Stop discovery thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Avahi discovery stopped")

    def get_servers(self) -> List[ServerInfo]:
        """Get list of currently known servers"""
        with self._lock:
            # Remove stale servers
            now = time.time()
            stale_ids = [
                sid for sid, server in self.servers.items()
                if now - server.last_seen > self.STALE_TIMEOUT
            ]
            for sid in stale_ids:
                logger.info(f"Removing stale server: {self.servers[sid]}")
                del self.servers[sid]

            return list(self.servers.values())

    def _discovery_loop(self):
        """Main discovery loop"""
        while self.running:
            try:
                self._scan_once()
            except Exception as e:
                logger.error(f"Discovery scan failed: {e}")

            # Sleep in small intervals to allow quick shutdown
            for _ in range(self.SCAN_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

    def _scan_once(self):
        """Perform one scan for Snapcast servers"""
        try:
            # Use avahi-browse to discover services
            # -t: terminate after timeout
            # -p: parseable output
            # -r: resolve host names
            result = subprocess.run(
                ["avahi-browse", "-t", "-p", "-r", self.SERVICE_TYPE],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                logger.warning(f"avahi-browse failed: {result.stderr}")
                return

            discovered = self._parse_avahi_output(result.stdout)

            with self._lock:
                # Update server list
                for server in discovered:
                    if server.id in self.servers:
                        # Update existing server
                        self.servers[server.id].last_seen = time.time()
                    else:
                        # New server discovered
                        logger.info(f"Discovered new server: {server}")
                        self.servers[server.id] = server

                # Notify callback if provided
                if self.callback:
                    try:
                        self.callback(list(self.servers.values()))
                    except Exception as e:
                        logger.error(f"Discovery callback failed: {e}")

        except subprocess.TimeoutExpired:
            logger.warning("avahi-browse timed out")
        except FileNotFoundError:
            logger.error("avahi-browse not found - is Avahi installed?")
        except Exception as e:
            logger.error(f"Scan failed: {e}")

    def _parse_avahi_output(self, output: str) -> List[ServerInfo]:
        """
        Parse avahi-browse output
        Format: =;interface;protocol;name;type;domain;hostname;address;port;txt
        Example: =;eth0;IPv4;Snapcast;_snapcast-jsonrpc._tcp;local;raspberrypi.local;192.168.1.100;1780;"version=0.34.0"
        """
        servers = []

        for line in output.splitlines():
            if not line.startswith("="):
                continue

            try:
                parts = line.split(";")
                if len(parts) < 9:
                    continue

                # Extract fields
                service_name = parts[3]
                hostname = parts[6]
                address = parts[7]
                port = int(parts[8])

                # Parse TXT records if present
                txt_records = {}
                if len(parts) > 9:
                    txt_data = parts[9]
                    # TXT records are in format "key=value" separated by spaces
                    for record in txt_data.strip('"').split():
                        if "=" in record:
                            key, value = record.split("=", 1)
                            txt_records[key] = value

                server = ServerInfo(
                    host=address,
                    port=port,
                    name=service_name or hostname,
                    txt_records=txt_records
                )
                servers.append(server)

            except Exception as e:
                logger.warning(f"Failed to parse avahi line: {line} - {e}")

        return servers

    def add_manual_server(self, host: str, port: int, name: str) -> ServerInfo:
        """Manually add a server (for static configuration)"""
        server = ServerInfo(host=host, port=port, name=name)
        with self._lock:
            self.servers[server.id] = server
            logger.info(f"Manually added server: {server}")
        return server


# For testing
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    def on_servers_changed(servers: List[ServerInfo]):
        print(f"\n=== Servers ({len(servers)}) ===")
        for server in servers:
            print(f"  {server}")

    discovery = AvahiDiscovery(callback=on_servers_changed)
    discovery.start()

    try:
        print("Discovering Snapcast servers (Press Ctrl+C to stop)...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        discovery.stop()
