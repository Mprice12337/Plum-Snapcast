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
    Looks for _snapcast-http._tcp services
    """

    SERVICE_TYPE = "_snapcast-http._tcp"
    SCAN_INTERVAL = 30  # Rescan every 30 seconds
    STALE_TIMEOUT = 120  # Consider server stale after 2 minutes

    def __init__(self, callback: Optional[Callable[[List[ServerInfo]], None]] = None):
        self.servers: Dict[str, ServerInfo] = {}
        self.callback = callback
        self.running = False
        self.thread = None
        self._lock = threading.Lock()

        # New callbacks for server lifecycle events
        self.on_server_added_callback: Optional[Callable[[ServerInfo], None]] = None
        self.on_server_removed_callback: Optional[Callable[[ServerInfo], None]] = None

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
                server_info = self.servers[sid]
                logger.info(f"Removing stale server: {server_info}")
                del self.servers[sid]

                # Notify callback of server removal
                if self.on_server_removed_callback:
                    try:
                        self.on_server_removed_callback(server_info)
                    except Exception as e:
                        logger.error(f"Server removed callback failed: {e}")

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
            # -p: parseable output
            # -r: resolve host names
            # Note: Not using -t to allow time for service resolution
            # Using Python timeout instead for overall operation timeout
            result = subprocess.run(
                ["timeout", "8", "avahi-browse", "-p", "-r", self.SERVICE_TYPE],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                # Check if Avahi daemon is not running yet (common during startup)
                if "Daemon not running" in result.stderr:
                    logger.debug("Avahi daemon not ready yet, will retry on next scan")
                else:
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

                        # Notify callback of new server
                        if self.on_server_added_callback:
                            try:
                                self.on_server_added_callback(server)
                            except Exception as e:
                                logger.error(f"Server added callback failed: {e}")

                # Notify general callback if provided
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
        # Use dict to deduplicate by hostname, preferring routable IPv4 addresses
        servers_by_hostname = {}

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

                # Skip unwanted addresses
                # Skip IPv6 link-local (fe80::)
                if address.startswith("fe80:"):
                    continue
                # Skip localhost
                if address in ("127.0.0.1", "::1"):
                    continue
                # Skip Docker bridge IPs
                if address.startswith("172.17.") or address.startswith("172.18."):
                    continue

                # Parse TXT records if present
                txt_records = {}
                if len(parts) > 9:
                    txt_data = parts[9]
                    # TXT records are in format "key=value" separated by spaces
                    for record in txt_data.strip('"').split():
                        if "=" in record:
                            key, value = record.split("=", 1)
                            txt_records[key] = value

                # Determine if this is a good address (prefer IPv4, especially private networks)
                is_ipv4 = ":" not in address
                is_private_ipv4 = is_ipv4 and (
                    address.startswith("192.168.") or
                    address.startswith("10.") or
                    address.startswith("172.")
                )

                # Create server info
                server = ServerInfo(
                    host=address,
                    port=1780,  # Always use HTTP port for WebSocket connections
                    name=service_name or hostname,
                    txt_records=txt_records
                )

                # If we haven't seen this hostname, add it
                if hostname not in servers_by_hostname:
                    servers_by_hostname[hostname] = server
                else:
                    # If we have seen it, prefer private IPv4 > IPv4 > IPv6
                    existing = servers_by_hostname[hostname]
                    existing_is_ipv4 = ":" not in existing.host
                    existing_is_private = existing_is_ipv4 and (
                        existing.host.startswith("192.168.") or
                        existing.host.startswith("10.") or
                        existing.host.startswith("172.")
                    )

                    # Replace if new address is better
                    if is_private_ipv4 and not existing_is_private:
                        servers_by_hostname[hostname] = server
                    elif is_ipv4 and not existing_is_ipv4:
                        servers_by_hostname[hostname] = server

            except Exception as e:
                logger.warning(f"Failed to parse avahi line: {line} - {e}")

        return list(servers_by_hostname.values())

    def add_manual_server(self, host: str, port: int, name: str) -> ServerInfo:
        """Manually add a server (for static configuration)"""
        server = ServerInfo(host=host, port=port, name=name)
        with self._lock:
            self.servers[server.id] = server
            logger.info(f"Manually added server: {server}")
        return server

    def edit_manual_server(self, old_server_id: str, host: str, port: int, name: str) -> ServerInfo:
        """Edit an existing manually added server"""
        with self._lock:
            # Remove old server entry
            if old_server_id in self.servers:
                logger.info(f"Removing old server: {self.servers[old_server_id]}")
                del self.servers[old_server_id]

            # Add new server with updated info
            server = ServerInfo(host=host, port=port, name=name)
            self.servers[server.id] = server
            logger.info(f"Updated server: {server}")
            return server

    def remove_manual_server(self, server_id: str):
        """Remove a manually added server"""
        with self._lock:
            if server_id in self.servers:
                server_info = self.servers[server_id]
                logger.info(f"Removing server: {server_info}")
                del self.servers[server_id]

                # Notify callback of server removal
                if self.on_server_removed_callback:
                    try:
                        self.on_server_removed_callback(server_info)
                    except Exception as e:
                        logger.error(f"Server removed callback failed: {e}")

    def set_server_added_callback(self, callback: Callable[[ServerInfo], None]):
        """Set callback for when a new server is discovered"""
        self.on_server_added_callback = callback
        logger.info("Server added callback registered")

    def set_server_removed_callback(self, callback: Callable[[ServerInfo], None]):
        """Set callback for when a server is removed"""
        self.on_server_removed_callback = callback
        logger.info("Server removed callback registered")


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
