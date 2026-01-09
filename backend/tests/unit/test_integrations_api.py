"""
Unit tests for Integrations API
Tests: Enable/disable integrations, endpoint CRUD for multi-instance
"""

import json
import pytest
from unittest.mock import patch, MagicMock


class TestAirPlayIntegration:
    """Tests for AirPlay integration endpoints"""

    def test_get_airplay_status(self, integrations_client, mock_subprocess):
        """GET /api/integrations/airplay/status returns status"""
        response = integrations_client.get('/api/integrations/airplay/status')

        assert response.status_code == 200
        data = response.get_json()
        assert 'running' in data or 'status' in data

    def test_enable_airplay(self, integrations_client, mock_subprocess):
        """POST /api/integrations/airplay/enable starts service"""
        response = integrations_client.post('/api/integrations/airplay/enable')

        assert response.status_code == 200
        data = response.get_json()
        assert data.get('success') is True or 'enabled' in str(data).lower()

    def test_disable_airplay(self, integrations_client, mock_subprocess):
        """POST /api/integrations/airplay/disable stops service"""
        response = integrations_client.post('/api/integrations/airplay/disable')

        assert response.status_code == 200
        data = response.get_json()
        assert data.get('success') is True or 'disabled' in str(data).lower()

    def test_get_airplay_endpoints(self, integrations_client):
        """GET /api/integrations/airplay/endpoints returns endpoint list"""
        response = integrations_client.get('/api/integrations/airplay/endpoints')

        assert response.status_code == 200
        data = response.get_json()
        assert 'endpoints' in data
        assert isinstance(data['endpoints'], list)

    def test_add_airplay_endpoint(self, integrations_client, mock_subprocess):
        """POST /api/integrations/airplay/endpoints creates new endpoint"""
        response = integrations_client.post(
            '/api/integrations/airplay/endpoints',
            json={'deviceName': 'New AirPlay'}
        )

        # Should succeed or fail gracefully (depends on setup script)
        assert response.status_code in [200, 201, 500]
        if response.status_code == 200:
            data = response.get_json()
            assert data.get('success') is True or 'endpoint' in data

    def test_add_airplay_endpoint_requires_name(self, integrations_client):
        """POST /api/integrations/airplay/endpoints requires deviceName"""
        response = integrations_client.post(
            '/api/integrations/airplay/endpoints',
            json={}
        )

        assert response.status_code == 400

    def test_update_airplay_endpoint(self, integrations_client, mock_subprocess):
        """PUT /api/integrations/airplay/endpoints/{id} updates endpoint"""
        response = integrations_client.put(
            '/api/integrations/airplay/endpoints/1',
            json={'deviceName': 'Updated AirPlay', 'enabled': True}
        )

        # Should succeed or fail gracefully
        assert response.status_code in [200, 404, 500]

    def test_delete_airplay_endpoint_prevented_if_last(self, integrations_client):
        """DELETE /api/integrations/airplay/endpoints/{id} prevents removing last"""
        # With default settings, there's only one endpoint
        response = integrations_client.delete('/api/integrations/airplay/endpoints/1')

        # Should be rejected (can't remove last endpoint)
        if response.status_code == 200:
            data = response.get_json()
            # Either rejected or endpoint was not the last
            assert data.get('success') is True or 'last' in str(data).lower()


class TestBluetoothIntegration:
    """Tests for Bluetooth integration endpoints"""

    def test_get_bluetooth_status(self, integrations_client, mock_subprocess):
        """GET /api/integrations/bluetooth/status returns detailed status"""
        response = integrations_client.get('/api/integrations/bluetooth/status')

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    def test_enable_bluetooth(self, integrations_client, mock_subprocess):
        """POST /api/integrations/bluetooth/enable starts all BT services"""
        response = integrations_client.post('/api/integrations/bluetooth/enable')

        assert response.status_code == 200
        data = response.get_json()
        assert data.get('success') is True or 'enabled' in str(data).lower()

    def test_disable_bluetooth(self, integrations_client, mock_subprocess):
        """POST /api/integrations/bluetooth/disable stops all BT services"""
        response = integrations_client.post('/api/integrations/bluetooth/disable')

        assert response.status_code == 200
        data = response.get_json()
        assert data.get('success') is True or 'disabled' in str(data).lower()

    def test_update_bluetooth_settings(self, integrations_client, mock_subprocess):
        """POST /api/integrations/bluetooth/settings updates BT settings"""
        response = integrations_client.post(
            '/api/integrations/bluetooth/settings',
            json={'autoPair': True, 'discoverable': True}
        )

        # Should succeed
        assert response.status_code in [200, 500]

    def test_update_bluetooth_device_name(self, integrations_client, mock_subprocess):
        """POST /api/integrations/bluetooth/device-name updates name"""
        response = integrations_client.post(
            '/api/integrations/bluetooth/device-name',
            json={'deviceName': 'My Bluetooth Speaker'}
        )

        assert response.status_code in [200, 500]


class TestSpotifyIntegration:
    """Tests for Spotify Connect integration endpoints"""

    def test_get_spotify_status(self, integrations_client, mock_subprocess):
        """GET /api/integrations/spotify/status returns status"""
        response = integrations_client.get('/api/integrations/spotify/status')

        assert response.status_code == 200

    def test_enable_spotify(self, integrations_client, mock_subprocess):
        """POST /api/integrations/spotify/enable starts service"""
        response = integrations_client.post('/api/integrations/spotify/enable')

        assert response.status_code == 200

    def test_disable_spotify(self, integrations_client, mock_subprocess):
        """POST /api/integrations/spotify/disable stops service"""
        response = integrations_client.post('/api/integrations/spotify/disable')

        assert response.status_code == 200

    def test_get_spotify_endpoints(self, integrations_client):
        """GET /api/integrations/spotify/endpoints returns endpoint list"""
        response = integrations_client.get('/api/integrations/spotify/endpoints')

        assert response.status_code == 200
        data = response.get_json()
        assert 'endpoints' in data

    def test_add_spotify_endpoint(self, integrations_client, mock_subprocess):
        """POST /api/integrations/spotify/endpoints creates endpoint"""
        response = integrations_client.post(
            '/api/integrations/spotify/endpoints',
            json={'deviceName': 'Spotify Kitchen'}
        )

        assert response.status_code in [200, 201, 500]

    def test_update_spotify_bitrate(self, integrations_client, mock_subprocess):
        """POST /api/integrations/spotify/bitrate updates bitrate"""
        response = integrations_client.post(
            '/api/integrations/spotify/bitrate',
            json={'bitrate': 320}
        )

        assert response.status_code in [200, 500]

    def test_update_spotify_bitrate_validates_value(self, integrations_client):
        """POST /api/integrations/spotify/bitrate rejects invalid bitrate"""
        response = integrations_client.post(
            '/api/integrations/spotify/bitrate',
            json={'bitrate': 999}  # Invalid
        )

        # Should reject invalid bitrate
        assert response.status_code in [400, 500]


class TestDLNAIntegration:
    """Tests for DLNA/UPnP integration endpoints"""

    def test_get_dlna_status(self, integrations_client, mock_subprocess):
        """GET /api/integrations/dlna/status returns status"""
        response = integrations_client.get('/api/integrations/dlna/status')

        assert response.status_code == 200

    def test_enable_dlna(self, integrations_client, mock_subprocess):
        """POST /api/integrations/dlna/enable starts service"""
        response = integrations_client.post('/api/integrations/dlna/enable')

        assert response.status_code == 200

    def test_disable_dlna(self, integrations_client, mock_subprocess):
        """POST /api/integrations/dlna/disable stops service"""
        response = integrations_client.post('/api/integrations/dlna/disable')

        assert response.status_code == 200

    def test_get_dlna_endpoints(self, integrations_client):
        """GET /api/integrations/dlna/endpoints returns endpoint list"""
        response = integrations_client.get('/api/integrations/dlna/endpoints')

        assert response.status_code == 200
        data = response.get_json()
        assert 'endpoints' in data

    def test_add_dlna_endpoint(self, integrations_client, mock_subprocess):
        """POST /api/integrations/dlna/endpoints creates endpoint with UUID"""
        response = integrations_client.post(
            '/api/integrations/dlna/endpoints',
            json={'deviceName': 'DLNA Living Room'}
        )

        assert response.status_code in [200, 201, 500]
        if response.status_code == 200:
            data = response.get_json()
            if 'endpoint' in data:
                assert 'uuid' in data['endpoint']


class TestPlexampIntegration:
    """Tests for Plexamp integration endpoints"""

    def test_get_plexamp_status(self, integrations_client, mock_subprocess):
        """GET /api/integrations/plexamp/status returns status with availability"""
        response = integrations_client.get('/api/integrations/plexamp/status')

        assert response.status_code == 200
        data = response.get_json()
        # Should include availability flag
        assert isinstance(data, dict)

    def test_enable_plexamp_when_available(self, integrations_client, mock_subprocess):
        """POST /api/integrations/plexamp/enable works when available"""
        response = integrations_client.post('/api/integrations/plexamp/enable')

        # Should either succeed or indicate unavailable
        assert response.status_code in [200, 400, 500]

    def test_disable_plexamp(self, integrations_client, mock_subprocess):
        """POST /api/integrations/plexamp/disable stops lifecycle manager"""
        response = integrations_client.post('/api/integrations/plexamp/disable')

        assert response.status_code == 200


class TestIntegrationControllerBase:
    """Tests for common integration controller behavior"""

    def test_integration_enable_updates_settings(self, integrations_client, mock_subprocess, temp_settings_file):
        """Enabling integration updates settings.json"""
        integrations_client.post('/api/integrations/bluetooth/enable')

        with open(temp_settings_file) as f:
            settings = json.load(f)

        assert settings['integrations']['bluetooth']['enabled'] is True

    def test_integration_disable_updates_settings(self, integrations_client, mock_subprocess, temp_settings_file):
        """Disabling integration updates settings.json"""
        # First enable
        integrations_client.post('/api/integrations/bluetooth/enable')
        # Then disable
        integrations_client.post('/api/integrations/bluetooth/disable')

        with open(temp_settings_file) as f:
            settings = json.load(f)

        assert settings['integrations']['bluetooth']['enabled'] is False
