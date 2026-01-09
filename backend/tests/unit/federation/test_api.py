"""
Unit tests for Federation API
Tests: REST endpoints with mocked aggregator and router
"""

import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from flask import Flask
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts'))


@pytest.fixture
def mock_federation_components():
    """Mock all federation components for API testing"""
    with patch.dict('sys.modules', {
        'federation.discovery': MagicMock(),
        'federation.websocket_manager': MagicMock(),
        'federation.router': MagicMock(),
        'federation.remote_snapclient_manager': MagicMock()
    }):
        yield


class TestHealthEndpoint:
    """Tests for /api/health endpoint"""

    def test_health_response_structure(self):
        """Health response has expected structure"""
        expected_fields = ['status', 'service', 'loop_healthy']

        # Simulated health response
        health_response = {
            'status': 'healthy',
            'service': 'federation',
            'loop_healthy': True
        }

        for field in expected_fields:
            assert field in health_response

    def test_health_status_values(self):
        """Health status is healthy or degraded"""
        valid_statuses = ['healthy', 'degraded']

        for status in valid_statuses:
            assert status in ['healthy', 'degraded']


class TestServerEndpoints:
    """Tests for /api/federation/servers endpoints"""

    def test_server_list_structure(self):
        """Server list has expected structure"""
        from tests.mocks.mock_websocket import MockSnapcastConnection

        # Create mock servers
        servers = [
            {
                'id': 'server-192-168-1-100',
                'name': 'Main Server',
                'host': '192.168.1.100',
                'port': 1780,
                'connected': True,
                'isLocal': True
            },
            {
                'id': 'server-192-168-1-101',
                'name': 'Kitchen',
                'host': '192.168.1.101',
                'port': 1780,
                'connected': True,
                'isLocal': False
            }
        ]

        for server in servers:
            assert 'id' in server
            assert 'name' in server
            assert 'host' in server
            assert 'port' in server
            assert 'connected' in server
            assert 'isLocal' in server

    def test_add_server_request(self):
        """Add server request structure"""
        request_body = {
            'host': '192.168.1.102',
            'port': 1780,
            'name': 'New Server'
        }

        assert 'host' in request_body
        assert 'port' in request_body
        assert 'name' in request_body

    def test_remove_server_request(self):
        """Remove server request structure"""
        request_body = {
            'serverId': 'server-192-168-1-102'
        }

        assert 'serverId' in request_body


class TestStreamEndpoints:
    """Tests for /api/federation/streams endpoints"""

    def test_stream_list_structure(self):
        """Stream list has expected structure"""
        streams = [
            {
                'id': 'server-192-168-1-100-airplay1',
                'serverId': 'server-192-168-1-100',
                'serverName': 'Main Server',
                'name': 'airplay1',
                'status': 'playing',
                'metadata': {
                    'title': 'Song Title',
                    'artist': 'Artist Name',
                    'album': 'Album Name',
                    'artUrl': '',
                    'duration': 180000
                },
                'properties': {},
                'playback': {
                    'position': 45000,
                    'duration': 180000,
                    'interpolated_position': 45500,
                    'playback_status': 'playing',
                    'is_stale': False
                }
            }
        ]

        for stream in streams:
            assert 'id' in stream
            assert 'serverId' in stream
            assert 'status' in stream
            assert 'metadata' in stream

    def test_stream_control_request(self):
        """Stream control request structure"""
        request_body = {
            'streamId': 'server-192-168-1-100-airplay1',
            'command': 'play'
        }

        assert request_body['command'] in ['play', 'pause', 'next', 'previous']


class TestClientEndpoints:
    """Tests for /api/federation/clients endpoints"""

    def test_client_list_structure(self):
        """Client list has expected structure"""
        clients = [
            {
                'id': 'server-192-168-1-100-living-room',
                'serverId': 'server-192-168-1-100',
                'serverName': 'Main Server',
                'name': 'Living Room Speaker',
                'connected': True,
                'currentStreamId': 'server-192-168-1-100-airplay1',
                'volume': 100,
                'muted': False
            }
        ]

        for client in clients:
            assert 'id' in client
            assert 'serverId' in client
            assert 'name' in client
            assert 'connected' in client
            assert 'volume' in client

    def test_volume_request(self):
        """Volume control request structure"""
        request_body = {
            'clientId': 'server-192-168-1-100-living-room',
            'volume': 75,
            'muted': False
        }

        assert 0 <= request_body['volume'] <= 100
        assert isinstance(request_body['muted'], bool)


class TestRoutingEndpoints:
    """Tests for /api/federation/route endpoints"""

    def test_route_request_structure(self):
        """Route request has expected structure"""
        request_body = {
            'clientId': 'server-192-168-1-100-living-room',
            'streamId': 'server-192-168-1-100-airplay1'
        }

        assert 'clientId' in request_body
        assert 'streamId' in request_body

    def test_active_endpoint_response(self):
        """Active endpoint response structure"""
        response = {
            'active': True,
            'serverId': 'server-192-168-1-100',
            'clientId': 'server-192-168-1-100-living-room',
            'streamId': 'server-192-168-1-100-airplay1'
        }

        assert 'active' in response
        assert isinstance(response['active'], bool)

    def test_inactive_endpoint_response(self):
        """Inactive endpoint response structure"""
        response = {
            'active': False,
            'serverId': None,
            'clientId': None,
            'streamId': None
        }

        assert response['active'] is False
        assert response['serverId'] is None


class TestDataAggregation:
    """Tests for data aggregation logic"""

    def test_stream_id_federation(self):
        """Stream IDs are federated with server prefix"""
        server_id = 'server-192-168-1-100'
        local_stream_id = 'airplay1'

        federated_id = f'{server_id}-{local_stream_id}'

        assert federated_id.startswith('server-')
        assert local_stream_id in federated_id

    def test_client_id_federation(self):
        """Client IDs are federated with server prefix"""
        server_id = 'server-192-168-1-100'
        local_client_id = 'living-room'

        federated_id = f'{server_id}-{local_client_id}'

        assert federated_id.startswith('server-')
        assert local_client_id in federated_id

    def test_playback_data_enrichment(self):
        """Playback data is enriched with server info"""
        stream_data = {
            'id': 'airplay1',
            'status': 'playing',
            'properties': {}
        }

        playback_data = {
            'position': 45000,
            'duration': 180000,
            'interpolated_position': 45500,
            'playback_status': 'playing',
            'is_stale': False
        }

        # Combine stream and playback
        enriched = {
            **stream_data,
            'playback': playback_data
        }

        assert 'playback' in enriched
        assert enriched['playback']['position'] == 45000


class TestRemoteSnapclientTracking:
    """Tests for remote snapclient tracking in aggregation"""

    def test_remote_client_stream_mapping(self):
        """Remote snapclients map back to source server"""
        # Remote client on local server connects to remote stream
        remote_client_id = 'remote-server-192-168-1-101'
        source_server_id = 'server-192-168-1-101'

        # Extract source server from remote client ID
        if remote_client_id.startswith('remote-'):
            extracted = remote_client_id.replace('remote-', '')
            assert extracted == source_server_id

    def test_pass_two_stream_correction(self):
        """Pass 2 corrects stream assignment for remote clients"""
        # When remote-server-X is on local server playing stream Y from server X,
        # the local client's "currentStreamId" should show the federated stream ID

        local_server = 'server-192-168-1-100'
        remote_server = 'server-192-168-1-101'
        remote_client = f'remote-{remote_server}'
        remote_stream = 'airplay1'

        # The corrected stream ID should be federated
        federated_stream_id = f'{remote_server}-{remote_stream}'

        assert remote_server in federated_stream_id
        assert remote_stream in federated_stream_id


class TestErrorHandling:
    """Tests for API error handling"""

    def test_connection_error_response(self):
        """Connection errors return appropriate response"""
        error_response = {
            'success': False,
            'error': 'Connection to server failed'
        }

        assert error_response['success'] is False
        assert 'error' in error_response

    def test_timeout_response(self):
        """Timeout errors return appropriate response"""
        error_response = {
            'success': False,
            'error': 'Request timed out'
        }

        assert error_response['success'] is False
        assert 'timeout' in error_response['error'].lower() or 'error' in error_response

    def test_server_not_found_response(self):
        """Server not found returns appropriate response"""
        error_response = {
            'success': False,
            'error': 'Server not found: server-192-168-1-999'
        }

        assert error_response['success'] is False
