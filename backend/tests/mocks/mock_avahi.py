"""
Mock Avahi/mDNS discovery for testing
"""

from typing import List, Dict, Any, Optional
from unittest.mock import MagicMock, patch
import time


class MockServer:
    """Represents a mock Snapcast server for discovery"""

    def __init__(
        self,
        name: str,
        host: str,
        port: int = 1780,
        interface: str = "en0",
        protocol: str = "IPv4",
        hostname: str = None,
        txt_records: Dict[str, str] = None
    ):
        self.name = name
        self.host = host
        self.port = port
        self.interface = interface
        self.protocol = protocol
        self.hostname = hostname or f"{name.lower().replace(' ', '-')}.local"
        self.txt_records = txt_records or {"version": "0.27"}
        self.last_seen = time.time()

    def to_avahi_line(self) -> str:
        """Generate avahi-browse output line for this server"""
        txt = " ".join(f'"{k}={v}"' for k, v in self.txt_records.items())
        return (
            f"=;{self.interface};{self.protocol};{self.name};"
            f"_snapcast-http._tcp;local;{self.hostname};{self.host};{self.port};{txt}"
        )


class MockAvahiDiscovery:
    """
    Mock Avahi discovery for testing federation.

    Usage:
        mock_avahi = MockAvahiDiscovery()
        mock_avahi.add_server('Kitchen', '192.168.1.100')
        mock_avahi.add_server('Living Room', '192.168.1.101')

        with mock_avahi.patch():
            # Test code that uses avahi-browse
            pass
    """

    def __init__(self):
        self.servers: Dict[str, MockServer] = {}
        self._callbacks: Dict[str, callable] = {}

    def add_server(
        self,
        name: str,
        host: str,
        port: int = 1780,
        **kwargs
    ) -> MockServer:
        """Add a mock server to the discovery"""
        server = MockServer(name=name, host=host, port=port, **kwargs)
        server_id = f"server-{host.replace('.', '-')}"
        self.servers[server_id] = server

        # Trigger callback if registered
        if 'on_server_added' in self._callbacks:
            self._callbacks['on_server_added'](server_id, server)

        return server

    def remove_server(self, host: str):
        """Remove a server from discovery"""
        server_id = f"server-{host.replace('.', '-')}"
        if server_id in self.servers:
            server = self.servers.pop(server_id)

            # Trigger callback if registered
            if 'on_server_removed' in self._callbacks:
                self._callbacks['on_server_removed'](server_id, server)

    def get_avahi_output(self) -> str:
        """Generate avahi-browse output for all servers"""
        lines = []
        for server in self.servers.values():
            lines.append(server.to_avahi_line())
        return "\n".join(lines)

    def on_server_added(self, callback: callable):
        """Register callback for server added events"""
        self._callbacks['on_server_added'] = callback

    def on_server_removed(self, callback: callable):
        """Register callback for server removed events"""
        self._callbacks['on_server_removed'] = callback

    def clear(self):
        """Remove all servers"""
        self.servers.clear()

    def patch(self):
        """
        Return a context manager that patches avahi-browse subprocess calls.

        The patched subprocess.run will return the mock avahi output when
        avahi-browse is called.
        """
        mock_avahi = self

        def mock_subprocess_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""

            if 'avahi-browse' in ' '.join(cmd):
                result.stdout = mock_avahi.get_avahi_output()
            else:
                result.stdout = ""

            return result

        return patch('subprocess.run', mock_subprocess_run)


class MockAvahiBrowseOutput:
    """
    Static mock avahi-browse output generator for simple test cases.

    Usage:
        output = MockAvahiBrowseOutput.generate([
            {'name': 'Kitchen', 'host': '192.168.1.100'},
            {'name': 'Living Room', 'host': '192.168.1.101'}
        ])
    """

    @staticmethod
    def generate(servers: List[Dict[str, Any]]) -> str:
        """Generate avahi-browse output from server list"""
        lines = []
        for server_data in servers:
            server = MockServer(
                name=server_data.get('name', 'Unknown'),
                host=server_data.get('host', '192.168.1.1'),
                port=server_data.get('port', 1780),
                interface=server_data.get('interface', 'en0'),
                protocol=server_data.get('protocol', 'IPv4'),
                hostname=server_data.get('hostname'),
                txt_records=server_data.get('txt_records')
            )
            lines.append(server.to_avahi_line())
        return "\n".join(lines)

    @staticmethod
    def empty() -> str:
        """Return empty avahi output"""
        return ""

    @staticmethod
    def single_server(name: str = "Plum Snapcast", host: str = "192.168.1.100") -> str:
        """Return output for a single server"""
        return MockAvahiBrowseOutput.generate([{'name': name, 'host': host}])

    @staticmethod
    def multiple_servers() -> str:
        """Return output for multiple test servers"""
        return MockAvahiBrowseOutput.generate([
            {'name': 'Kitchen Audio', 'host': '192.168.1.100'},
            {'name': 'Living Room', 'host': '192.168.1.101'},
            {'name': 'Bedroom', 'host': '192.168.1.102'}
        ])
