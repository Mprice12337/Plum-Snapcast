"""
Unit tests for Federation WebSocket Manager
Tests: Connection management, JSON-RPC handling, reconnection logic
"""

import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts'))


class TestMockWebSocket:
    """Tests for MockWebSocket functionality"""

    def test_mock_websocket_basics(self):
        """MockWebSocket provides basic WebSocket interface"""
        from tests.mocks.mock_websocket import MockWebSocket

        ws = MockWebSocket()
        assert ws._connected is False

    @pytest.mark.asyncio
    async def test_mock_websocket_connect(self):
        """MockWebSocket simulates connection"""
        from tests.mocks.mock_websocket import MockWebSocket

        ws = MockWebSocket()
        await ws.connect('ws://localhost:1780/jsonrpc')

        assert ws._connected is True
        assert ws._url == 'ws://localhost:1780/jsonrpc'

    @pytest.mark.asyncio
    async def test_mock_websocket_send(self):
        """MockWebSocket tracks sent messages"""
        from tests.mocks.mock_websocket import MockWebSocket

        ws = MockWebSocket()
        await ws.connect('ws://localhost:1780/jsonrpc')

        await ws.send('{"method": "Server.GetStatus"}')

        assert len(ws.messages_sent) == 1
        assert 'Server.GetStatus' in ws.messages_sent[0]

    @pytest.mark.asyncio
    async def test_mock_websocket_receive_response(self):
        """MockWebSocket returns configured responses"""
        from tests.mocks.mock_websocket import MockWebSocket

        ws = MockWebSocket()
        ws.add_response('Server.GetStatus', {'server': {'groups': [], 'streams': []}})
        await ws.connect('ws://localhost:1780/jsonrpc')

        # Send request
        await ws.send(json.dumps({
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'Server.GetStatus'
        }))

        # Receive response
        response = await ws.recv()
        data = json.loads(response)

        assert data['jsonrpc'] == '2.0'
        assert data['id'] == 1
        assert 'result' in data
        assert 'server' in data['result']

    @pytest.mark.asyncio
    async def test_mock_websocket_close(self):
        """MockWebSocket simulates close"""
        from tests.mocks.mock_websocket import MockWebSocket

        ws = MockWebSocket()
        await ws.connect('ws://localhost:1780/jsonrpc')
        await ws.close()

        assert ws._connected is False
        assert ws.closed is True


class TestMockSnapcastConnection:
    """Tests for MockSnapcastConnection functionality"""

    def test_connection_default_state(self):
        """MockSnapcastConnection has correct default state"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection(
            server_id='server-192-168-1-100',
            server_name='Test Server'
        )

        assert conn.server_id == 'server-192-168-1-100'
        assert conn.server_name == 'Test Server'
        assert conn.connected is True
        assert 'none' in conn.streams  # Default stream

    def test_add_stream(self):
        """MockSnapcastConnection.add_stream adds stream"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_stream('airplay1', status='playing', metadata={'title': 'Test Song'})

        assert 'airplay1' in conn.streams
        assert conn.streams['airplay1']['status'] == 'playing'
        assert conn.streams['airplay1']['properties']['metadata']['title'] == 'Test Song'

    def test_add_client(self):
        """MockSnapcastConnection.add_client adds client and group"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_client('client-abc', name='Living Room', volume=75)

        assert 'client-abc' in conn.clients
        assert conn.clients['client-abc']['config']['name'] == 'Living Room'
        assert conn.clients['client-abc']['config']['volume']['percent'] == 75

        # Should have created a group
        assert len(conn.groups) > 0

    @pytest.mark.asyncio
    async def test_send_request_get_status(self):
        """MockSnapcastConnection handles Server.GetStatus"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_stream('airplay1')
        conn.add_client('client1', name='Speaker')

        result = await conn.send_request('Server.GetStatus')

        assert 'server' in result
        assert 'groups' in result['server']
        assert 'streams' in result['server']

    @pytest.mark.asyncio
    async def test_send_request_group_set_stream(self):
        """MockSnapcastConnection handles Group.SetStream"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_stream('airplay1')
        conn.add_client('client1', name='Speaker', group_id='group1')

        # Route group to stream
        await conn.send_request('Group.SetStream', {
            'id': 'group1',
            'stream_id': 'airplay1'
        })

        assert conn.groups['group1']['stream_id'] == 'airplay1'

    @pytest.mark.asyncio
    async def test_send_request_client_set_volume(self):
        """MockSnapcastConnection handles Client.SetVolume"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        conn.add_client('client1', name='Speaker', volume=100)

        # Set volume
        await conn.send_request('Client.SetVolume', {
            'id': 'client1',
            'volume': {'percent': 50, 'muted': False}
        })

        assert conn.clients['client1']['config']['volume']['percent'] == 50

    def test_disconnect_reconnect(self):
        """MockSnapcastConnection disconnect/reconnect"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()
        assert conn.connected is True

        conn.disconnect()
        assert conn.connected is False

        conn.reconnect()
        assert conn.connected is True


class TestCreateMockSnapcastStatus:
    """Tests for create_mock_snapcast_status helper"""

    def test_default_status(self):
        """create_mock_snapcast_status returns valid structure"""
        from tests.mocks.mock_websocket import create_mock_snapcast_status

        status = create_mock_snapcast_status()

        assert 'server' in status
        assert 'groups' in status['server']
        assert 'streams' in status['server']

    def test_with_streams(self):
        """create_mock_snapcast_status with custom streams"""
        from tests.mocks.mock_websocket import create_mock_snapcast_status

        status = create_mock_snapcast_status(
            streams=[
                {'id': 'airplay1', 'isPlaying': True},
                {'id': 'spotify1', 'isPlaying': False}
            ]
        )

        stream_ids = [s['id'] for s in status['server']['streams']]
        assert 'airplay1' in stream_ids
        assert 'spotify1' in stream_ids

    def test_with_clients(self):
        """create_mock_snapcast_status with custom clients"""
        from tests.mocks.mock_websocket import create_mock_snapcast_status

        status = create_mock_snapcast_status(
            clients=[
                {'id': 'client1', 'name': 'Speaker A', 'volume': 75},
                {'id': 'client2', 'name': 'Speaker B', 'volume': 50}
            ]
        )

        # Clients should be in groups
        all_clients = []
        for group in status['server']['groups']:
            all_clients.extend(group['clients'])

        client_ids = [c['id'] for c in all_clients]
        assert 'client1' in client_ids
        assert 'client2' in client_ids


class TestNotificationHandling:
    """Tests for WebSocket notification handling"""

    @pytest.mark.asyncio
    async def test_mock_websocket_notification(self):
        """MockWebSocket can simulate server notifications"""
        from tests.mocks.mock_websocket import MockWebSocket

        ws = MockWebSocket()
        ws.add_notification('Stream.OnUpdate', {
            'id': 'airplay1',
            'status': 'playing'
        })

        await ws.connect('ws://localhost:1780/jsonrpc')

        # Receive the notification
        notification = await ws.recv()
        data = json.loads(notification)

        assert data['method'] == 'Stream.OnUpdate'
        assert data['params']['id'] == 'airplay1'
        assert data['params']['status'] == 'playing'

    @pytest.mark.asyncio
    async def test_mock_websocket_queued_notifications(self):
        """MockWebSocket queues notifications until connected"""
        from tests.mocks.mock_websocket import MockWebSocket

        ws = MockWebSocket()
        ws.add_notification('Event1', {'data': 1})
        ws.add_notification('Event2', {'data': 2})

        # Not connected yet, notifications queued
        await ws.connect('ws://localhost:1780/jsonrpc')

        # First notification
        n1 = json.loads(await ws.recv())
        assert n1['method'] == 'Event1'

        # Second notification
        n2 = json.loads(await ws.recv())
        assert n2['method'] == 'Event2'


class TestConnectionState:
    """Tests for tracking connection state"""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """MockWebSocket works as context manager"""
        from tests.mocks.mock_websocket import MockWebSocket

        async with MockWebSocket() as ws:
            await ws.connect('ws://localhost:1780/jsonrpc')
            assert ws._connected is True

        assert ws._connected is False

    @pytest.mark.asyncio
    async def test_request_tracking(self):
        """MockSnapcastConnection tracks requests"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        conn = MockSnapcastConnection()

        # Send some requests
        await conn.send_request('Server.GetStatus')
        await conn.send_request('Client.SetVolume', {'id': 'c1', 'volume': {'percent': 50}})

        assert len(conn._requests) == 2
        assert conn._requests[0]['method'] == 'Server.GetStatus'
        assert conn._requests[1]['method'] == 'Client.SetVolume'
