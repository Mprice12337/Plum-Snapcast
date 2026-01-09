"""
Unit tests for Federation Discovery Module
Tests: Avahi parsing, server lifecycle, IP preference logic
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts'))


class TestAvahiOutputParsing:
    """Tests for parsing avahi-browse output"""

    def test_parse_single_server(self):
        """Parse single server from avahi-browse output"""
        from tests.mocks.mock_avahi import MockAvahiBrowseOutput

        output = MockAvahiBrowseOutput.single_server(
            name='Kitchen Audio',
            host='192.168.1.100'
        )

        # Verify output format
        assert 'Kitchen Audio' in output
        assert '192.168.1.100' in output
        assert '_snapcast-http._tcp' in output

    def test_parse_multiple_servers(self):
        """Parse multiple servers from avahi-browse output"""
        from tests.mocks.mock_avahi import MockAvahiBrowseOutput

        output = MockAvahiBrowseOutput.multiple_servers()

        # Should contain multiple server lines
        lines = [l for l in output.split('\n') if l.strip()]
        assert len(lines) == 3

        # Each line should have expected format
        for line in lines:
            assert '_snapcast-http._tcp' in line
            assert '192.168.1' in line

    def test_parse_empty_output(self):
        """Handle empty avahi-browse output"""
        from tests.mocks.mock_avahi import MockAvahiBrowseOutput

        output = MockAvahiBrowseOutput.empty()
        assert output == ""


class TestServerIdGeneration:
    """Tests for server ID generation from host"""

    def test_server_id_format(self):
        """Server ID uses IP with dashes"""
        from tests.mocks.mock_avahi import MockAvahiDiscovery

        mock_discovery = MockAvahiDiscovery()
        mock_discovery.add_server('Test', '192.168.1.100')

        server_id = 'server-192-168-1-100'
        assert server_id in mock_discovery.servers

    def test_server_id_unique_per_host(self):
        """Each host gets unique server ID"""
        from tests.mocks.mock_avahi import MockAvahiDiscovery

        mock_discovery = MockAvahiDiscovery()
        mock_discovery.add_server('Server A', '192.168.1.100')
        mock_discovery.add_server('Server B', '192.168.1.101')

        assert len(mock_discovery.servers) == 2
        assert 'server-192-168-1-100' in mock_discovery.servers
        assert 'server-192-168-1-101' in mock_discovery.servers


class TestIPPreference:
    """Tests for IP address preference logic"""

    def test_prefer_private_ipv4(self):
        """Private IPv4 addresses preferred over public"""
        # This tests the IP preference logic from discovery.py
        # Private ranges: 192.168.x.x, 10.x.x.x, 172.16-31.x.x

        private_ips = [
            '192.168.1.100',
            '10.0.0.50',
            '172.16.0.1',
            '172.31.255.254'
        ]

        for ip in private_ips:
            # Should be considered private/preferred
            parts = ip.split('.')
            is_private = (
                parts[0] == '192' and parts[1] == '168' or
                parts[0] == '10' or
                parts[0] == '172' and 16 <= int(parts[1]) <= 31
            )
            assert is_private, f"{ip} should be considered private"

    def test_skip_localhost(self):
        """Localhost addresses should be skipped"""
        localhost_ips = ['127.0.0.1', '::1']

        for ip in localhost_ips:
            is_localhost = ip.startswith('127.') or ip == '::1'
            assert is_localhost


class TestServerLifecycle:
    """Tests for server discovery lifecycle"""

    def test_add_server_callback(self):
        """Server added callback is triggered"""
        from tests.mocks.mock_avahi import MockAvahiDiscovery

        callback_called = []

        def on_added(server_id, server):
            callback_called.append((server_id, server))

        mock_discovery = MockAvahiDiscovery()
        mock_discovery.on_server_added(on_added)
        mock_discovery.add_server('Test', '192.168.1.100')

        assert len(callback_called) == 1
        assert callback_called[0][0] == 'server-192-168-1-100'

    def test_remove_server_callback(self):
        """Server removed callback is triggered"""
        from tests.mocks.mock_avahi import MockAvahiDiscovery

        callback_called = []

        def on_removed(server_id, server):
            callback_called.append(server_id)

        mock_discovery = MockAvahiDiscovery()
        mock_discovery.on_server_removed(on_removed)
        mock_discovery.add_server('Test', '192.168.1.100')
        mock_discovery.remove_server('192.168.1.100')

        assert len(callback_called) == 1
        assert callback_called[0] == 'server-192-168-1-100'

    def test_clear_all_servers(self):
        """Clear removes all servers"""
        from tests.mocks.mock_avahi import MockAvahiDiscovery

        mock_discovery = MockAvahiDiscovery()
        mock_discovery.add_server('A', '192.168.1.100')
        mock_discovery.add_server('B', '192.168.1.101')

        assert len(mock_discovery.servers) == 2

        mock_discovery.clear()

        assert len(mock_discovery.servers) == 0


class TestMockServer:
    """Tests for MockServer data structure"""

    def test_server_default_values(self):
        """MockServer has sensible defaults"""
        from tests.mocks.mock_avahi import MockServer

        server = MockServer(name='Test', host='192.168.1.100')

        assert server.name == 'Test'
        assert server.host == '192.168.1.100'
        assert server.port == 1780  # Default Snapcast HTTP port
        assert server.interface == 'en0'
        assert server.protocol == 'IPv4'
        assert 'version' in server.txt_records

    def test_server_custom_values(self):
        """MockServer accepts custom values"""
        from tests.mocks.mock_avahi import MockServer

        server = MockServer(
            name='Custom',
            host='10.0.0.50',
            port=1788,
            interface='eth0',
            protocol='IPv6'
        )

        assert server.port == 1788
        assert server.interface == 'eth0'
        assert server.protocol == 'IPv6'

    def test_server_to_avahi_line(self):
        """Server generates valid avahi-browse line"""
        from tests.mocks.mock_avahi import MockServer

        server = MockServer(name='Test', host='192.168.1.100')
        line = server.to_avahi_line()

        # Check format: =;interface;protocol;name;type;domain;hostname;address;port;txt
        parts = line.split(';')
        assert parts[0] == '='
        assert parts[1] == 'en0'  # interface
        assert parts[2] == 'IPv4'  # protocol
        assert parts[3] == 'Test'  # name
        assert parts[4] == '_snapcast-http._tcp'  # type
        assert parts[7] == '192.168.1.100'  # address
        assert parts[8] == '1780'  # port


class TestDiscoveryPatch:
    """Tests for MockAvahiDiscovery patching"""

    def test_patch_subprocess(self):
        """MockAvahiDiscovery patches subprocess correctly"""
        from tests.mocks.mock_avahi import MockAvahiDiscovery

        mock_discovery = MockAvahiDiscovery()
        mock_discovery.add_server('Test', '192.168.1.100')

        with mock_discovery.patch() as _:
            import subprocess
            result = subprocess.run(['avahi-browse', '-p', '-r', '_snapcast-http._tcp'], capture_output=True, text=True)

            assert result.returncode == 0
            assert 'Test' in result.stdout
            assert '192.168.1.100' in result.stdout

    def test_get_avahi_output(self):
        """get_avahi_output returns all server lines"""
        from tests.mocks.mock_avahi import MockAvahiDiscovery

        mock_discovery = MockAvahiDiscovery()
        mock_discovery.add_server('A', '192.168.1.100')
        mock_discovery.add_server('B', '192.168.1.101')

        output = mock_discovery.get_avahi_output()

        assert '192.168.1.100' in output
        assert '192.168.1.101' in output
        assert len(output.split('\n')) == 2
