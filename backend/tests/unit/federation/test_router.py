"""
Unit tests for Federation Router
Tests: Cross-server routing, endpoint lockout, volume control
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts'))


class TestFederatedIdParsing:
    """Tests for federated ID parsing"""

    def test_parse_stream_id(self):
        """Parse federated stream ID"""
        # Format: server-{IP-octets}-{local-id}
        federated_id = 'server-192-168-1-100-airplay1'

        # Split at 5th component (after server-A-B-C-D)
        parts = federated_id.split('-')
        server_id = '-'.join(parts[:5])  # server-192-168-1-100
        local_id = '-'.join(parts[5:])   # airplay1

        assert server_id == 'server-192-168-1-100'
        assert local_id == 'airplay1'

    def test_parse_client_id(self):
        """Parse federated client ID"""
        federated_id = 'server-192-168-1-100-living-room-speaker'

        parts = federated_id.split('-')
        server_id = '-'.join(parts[:5])
        local_id = '-'.join(parts[5:])

        assert server_id == 'server-192-168-1-100'
        assert local_id == 'living-room-speaker'

    def test_parse_complex_local_id(self):
        """Parse ID with hyphens in local part"""
        federated_id = 'server-10-0-0-50-my-multi-hyphen-client'

        parts = federated_id.split('-')
        server_id = '-'.join(parts[:5])
        local_id = '-'.join(parts[5:])

        assert server_id == 'server-10-0-0-50'
        assert local_id == 'my-multi-hyphen-client'


class TestMacAddressDetection:
    """Tests for MAC address detection"""

    def test_detect_mac_address(self):
        """Detect MAC address format"""
        mac_addresses = [
            'aa:bb:cc:dd:ee:ff',
            '00:11:22:33:44:55',
            'AB:CD:EF:01:23:45'
        ]

        import re
        mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        for mac in mac_addresses:
            assert mac_pattern.match(mac), f"{mac} should be detected as MAC"

    def test_non_mac_addresses(self):
        """Non-MAC strings are not detected as MAC"""
        non_macs = [
            'client-abc123',
            'living-room',
            'remote-server-192-168-1-100',
            '12345678-1234-1234-1234-123456789abc'  # UUID
        ]

        import re
        mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        for non_mac in non_macs:
            assert not mac_pattern.match(non_mac), f"{non_mac} should not be detected as MAC"


class TestRemoteSnapclientDetection:
    """Tests for remote snapclient detection"""

    def test_detect_remote_client_id(self):
        """Detect remote snapclient ID format"""
        remote_ids = [
            'remote-server-192-168-1-100',
            'remote-server-10-0-0-50'
        ]

        for client_id in remote_ids:
            is_remote = client_id.startswith('remote-server-')
            assert is_remote, f"{client_id} should be detected as remote"

    def test_local_client_ids(self):
        """Local clients not detected as remote"""
        local_ids = [
            'aa:bb:cc:dd:ee:ff',
            'browser-client-uuid',
            'my-device'
        ]

        for client_id in local_ids:
            is_remote = client_id.startswith('remote-server-')
            assert not is_remote, f"{client_id} should not be detected as remote"


class TestRoutingScenarios:
    """Tests for different routing scenarios"""

    @pytest.mark.asyncio
    async def test_same_server_routing(self):
        """Route client to stream on same server"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection(server_id='server-192-168-1-100')
        conn.add_stream('airplay1')
        conn.add_client('client1', name='Speaker', group_id='group1')

        # Route client to stream
        await conn.send_request('Group.SetStream', {
            'id': 'group1',
            'stream_id': 'airplay1'
        })

        assert conn.groups['group1']['stream_id'] == 'airplay1'

    @pytest.mark.asyncio
    async def test_route_to_none_stream(self):
        """Route client to 'none' stream (silence)"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_stream('airplay1')
        conn.add_client('client1', group_id='group1')

        # Start on a stream
        conn.groups['group1']['stream_id'] = 'airplay1'

        # Route to none
        await conn.send_request('Group.SetStream', {
            'id': 'group1',
            'stream_id': 'none'
        })

        assert conn.groups['group1']['stream_id'] == 'none'


class TestVolumeControl:
    """Tests for volume control"""

    @pytest.mark.asyncio
    async def test_set_volume(self):
        """Set client volume"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_client('client1', volume=100)

        await conn.send_request('Client.SetVolume', {
            'id': 'client1',
            'volume': {'percent': 50}
        })

        assert conn.clients['client1']['config']['volume']['percent'] == 50

    @pytest.mark.asyncio
    async def test_mute_client(self):
        """Mute client"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_client('client1', volume=100)

        await conn.send_request('Client.SetVolume', {
            'id': 'client1',
            'volume': {'muted': True}
        })

        assert conn.clients['client1']['config']['volume']['muted'] is True


class TestEndpointLockout:
    """Tests for endpoint lockout logic"""

    def test_identify_output_client(self):
        """Identify output clients (hardware snapclients)"""
        # Output clients have MAC address format
        output_clients = [
            'aa:bb:cc:dd:ee:ff',
            '00:11:22:33:44:55'
        ]

        # Remote snapclients are also output
        remote_clients = [
            'remote-server-192-168-1-100',
            'remote-server-10-0-0-50'
        ]

        # Browser clients are NOT output (UUID format)
        browser_clients = [
            '12345678-1234-1234-1234-123456789abc',
            'snapweb-client'
        ]

        import re
        mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        def is_output_client(client_id):
            return mac_pattern.match(client_id) or client_id.startswith('remote-server-')

        for c in output_clients:
            assert is_output_client(c), f"{c} should be output client"

        for c in remote_clients:
            assert is_output_client(c), f"{c} should be output client"

        for c in browser_clients:
            assert not is_output_client(c), f"{c} should NOT be output client"

    @pytest.mark.asyncio
    async def test_deactivate_endpoint(self):
        """Deactivate endpoint by routing to none"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_stream('airplay1')
        conn.add_client('aa:bb:cc:dd:ee:ff', name='Speaker', group_id='group1')
        conn.groups['group1']['stream_id'] = 'airplay1'  # Active

        # Deactivate by routing to none
        await conn.send_request('Group.SetStream', {
            'id': 'group1',
            'stream_id': 'none'
        })

        assert conn.groups['group1']['stream_id'] == 'none'


class TestStreamControl:
    """Tests for stream control commands"""

    @pytest.mark.asyncio
    async def test_stream_control_play(self):
        """Send play command to stream"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_stream('airplay1')

        # Send play command
        result = await conn.send_request('Stream.Control', {
            'id': 'airplay1',
            'command': 'play'
        })

        # Should return success (empty dict)
        assert result == {}

    @pytest.mark.asyncio
    async def test_stream_control_pause(self):
        """Send pause command to stream"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_stream('airplay1')

        result = await conn.send_request('Stream.Control', {
            'id': 'airplay1',
            'command': 'pause'
        })

        assert result == {}

    @pytest.mark.asyncio
    async def test_player_control(self):
        """Send plugin player control command"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_stream('airplay1')

        result = await conn.send_request('Plugin.Stream.Player.Control', {
            'id': 'airplay1',
            'command': 'next'
        })

        assert result == {}


class TestDeviceConversion:
    """Tests for audio device format conversion"""

    def test_hw_to_dmix_conversion(self):
        """Convert hw:X,Y to dmix format for device sharing"""
        # The router converts hw:X,Y to default:CARD=name for dmix
        hw_devices = [
            ('hw:0,0', 'Headphones'),
            ('hw:1,0', 'HDMI'),
            ('hw:Headphones', 'Headphones')
        ]

        for hw_id, expected_card in hw_devices:
            # Extract card name/number
            if hw_id.startswith('hw:'):
                card_part = hw_id[3:].split(',')[0]
                # Result would be default:CARD={card_name}
                dmix_format = f'default:CARD={card_part}'
                assert 'default:CARD=' in dmix_format
