"""
Mock WebSocket for testing federation and Snapcast connections
"""

import asyncio
import json
from typing import Dict, Any, List, Optional, Callable
from unittest.mock import MagicMock, AsyncMock


class MockWebSocket:
    """
    Mock WebSocket connection for testing.

    Usage:
        mock_ws = MockWebSocket()
        mock_ws.add_response('Server.GetStatus', {'server': {...}})

        async with mock_ws.connect('ws://localhost:1780/jsonrpc') as ws:
            await ws.send('{"method": "Server.GetStatus"}')
            response = await ws.recv()
    """

    def __init__(self):
        self.messages_sent: List[str] = []
        self.responses: Dict[str, Any] = {}
        self.notifications: List[Dict[str, Any]] = []
        self._message_id = 0
        self._connected = False
        self._url: Optional[str] = None

    def add_response(self, method: str, result: Any):
        """Add a response for a specific JSON-RPC method"""
        self.responses[method] = result

    def add_notification(self, method: str, params: Any):
        """Add a notification to be sent"""
        self.notifications.append({
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        })

    async def connect(self, url: str):
        """Simulate connection"""
        self._url = url
        self._connected = True
        return self

    async def send(self, message: str):
        """Simulate sending a message"""
        self.messages_sent.append(message)

    async def recv(self) -> str:
        """Simulate receiving a message"""
        # Check for pending notifications first
        if self.notifications:
            notification = self.notifications.pop(0)
            return json.dumps(notification)

        # Parse the last sent message to generate response
        if self.messages_sent:
            last_message = json.loads(self.messages_sent[-1])
            method = last_message.get('method', '')
            msg_id = last_message.get('id', self._message_id)
            self._message_id = msg_id + 1

            if method in self.responses:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": self.responses[method]
                })

        # Default empty response
        return json.dumps({
            "jsonrpc": "2.0",
            "id": self._message_id,
            "result": {}
        })

    async def close(self):
        """Simulate closing connection"""
        self._connected = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    @property
    def closed(self) -> bool:
        return not self._connected


class MockSnapcastConnection:
    """
    Mock Snapcast connection for testing federation router and API.

    Simulates a full Snapcast server with streams, groups, and clients.

    Usage:
        mock_conn = MockSnapcastConnection(server_id='server-192-168-1-100')
        mock_conn.add_stream('airplay1', status='playing')
        mock_conn.add_client('client-abc123', 'Living Room Speaker')

        with mock_conn.patch():
            # Test code
            pass
    """

    def __init__(
        self,
        server_id: str = 'server-192-168-1-100',
        server_name: str = 'Test Server',
        host: str = '192.168.1.100',
        port: int = 1780
    ):
        self.server_id = server_id
        self.server_name = server_name
        self.host = host
        self.port = port

        self.streams: Dict[str, Dict[str, Any]] = {}
        self.groups: Dict[str, Dict[str, Any]] = {}
        self.clients: Dict[str, Dict[str, Any]] = {}

        self._connected = True
        self._requests: List[Dict[str, Any]] = []

        # Add default 'none' stream
        self.add_stream('none', status='idle')

    def add_stream(
        self,
        stream_id: str,
        status: str = 'idle',
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Add a stream to the mock server"""
        self.streams[stream_id] = {
            'id': stream_id,
            'status': status,
            'properties': {
                'metadata': metadata or {},
                'canPlay': True,
                'canPause': True,
                'canGoNext': True,
                'canGoPrevious': True,
                'canSeek': True
            },
            'uri': {
                'raw': f'pipe:///tmp/{stream_id}-fifo?name={stream_id}',
                'scheme': 'pipe',
                'host': '',
                'path': f'/tmp/{stream_id}-fifo',
                'query': {'name': stream_id}
            }
        }

    def add_client(
        self,
        client_id: str,
        name: str = 'Test Client',
        group_id: Optional[str] = None,
        volume: int = 100,
        muted: bool = False,
        connected: bool = True
    ):
        """Add a client to the mock server"""
        # Create group if not specified
        if not group_id:
            group_id = f'group-{client_id}'

        self.clients[client_id] = {
            'id': client_id,
            'config': {
                'name': name,
                'volume': {'percent': volume, 'muted': muted}
            },
            'connected': connected,
            'host': {'name': name, 'mac': 'aa:bb:cc:dd:ee:ff'}
        }

        # Create or update group
        if group_id not in self.groups:
            self.groups[group_id] = {
                'id': group_id,
                'name': '',
                'stream_id': 'none',
                'muted': False,
                'clients': []
            }
        self.groups[group_id]['clients'].append(self.clients[client_id])

    def get_server_status(self) -> Dict[str, Any]:
        """Get full server status"""
        return {
            'server': {
                'groups': list(self.groups.values()),
                'streams': list(self.streams.values())
            }
        }

    async def send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """Handle JSON-RPC requests"""
        self._requests.append({'method': method, 'params': params})

        if method == 'Server.GetStatus':
            return self.get_server_status()

        elif method == 'Group.SetStream':
            group_id = params.get('id')
            stream_id = params.get('stream_id')
            if group_id in self.groups:
                self.groups[group_id]['stream_id'] = stream_id
            return {}

        elif method == 'Client.SetVolume':
            client_id = params.get('id')
            volume = params.get('volume', {})
            if client_id in self.clients:
                self.clients[client_id]['config']['volume'].update(volume)
            return {}

        elif method == 'Stream.Control':
            # Simulate stream control
            return {}

        elif method == 'Plugin.Stream.Player.Control':
            # Simulate playback control
            return {}

        return {}

    async def get_status(self) -> Dict[str, Any]:
        """Get server status (convenience method)"""
        return await self.send_request('Server.GetStatus')

    @property
    def connected(self) -> bool:
        return self._connected

    def disconnect(self):
        self._connected = False

    def reconnect(self):
        self._connected = True


def create_mock_snapcast_status(
    streams: Optional[List[Dict]] = None,
    clients: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    Create a mock Snapcast server status response.

    Usage:
        status = create_mock_snapcast_status(
            streams=[{'id': 'airplay1', 'status': 'playing'}],
            clients=[{'id': 'client1', 'name': 'Speaker'}]
        )
    """
    mock_streams = []
    if streams:
        for s in streams:
            mock_streams.append({
                'id': s.get('id', 'stream1'),
                'status': s.get('status', 'idle'),
                'properties': s.get('properties', {
                    'metadata': {},
                    'canPlay': True,
                    'canPause': True
                }),
                'uri': {
                    'raw': f"pipe:///tmp/{s.get('id', 'stream1')}-fifo"
                }
            })
    else:
        mock_streams = [{
            'id': 'none',
            'status': 'idle',
            'properties': {},
            'uri': {'raw': 'pipe:///tmp/none-fifo'}
        }]

    mock_groups = []
    mock_clients = []
    if clients:
        for c in clients:
            client_data = {
                'id': c.get('id', 'client1'),
                'config': {
                    'name': c.get('name', 'Test Client'),
                    'volume': {'percent': c.get('volume', 100), 'muted': c.get('muted', False)}
                },
                'connected': c.get('connected', True),
                'host': {'name': c.get('name', 'Test'), 'mac': 'aa:bb:cc:dd:ee:ff'}
            }
            mock_clients.append(client_data)

            group_id = c.get('group_id', f"group-{c.get('id', 'client1')}")
            mock_groups.append({
                'id': group_id,
                'name': '',
                'stream_id': c.get('stream_id', 'none'),
                'muted': False,
                'clients': [client_data]
            })
    else:
        mock_groups = [{'id': 'group1', 'name': '', 'stream_id': 'none', 'muted': False, 'clients': []}]

    return {
        'server': {
            'groups': mock_groups,
            'streams': mock_streams
        }
    }
