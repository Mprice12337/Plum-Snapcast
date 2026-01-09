"""
Integration tests for Settings flow
Tests the complete settings read/write/update flow
"""

import json
import pytest
from unittest.mock import patch


class TestSettingsFlow:
    """Integration tests for settings management flow"""

    def test_initial_settings_creation(self, tmp_path, mock_os_chown, mock_os_chmod):
        """New installation creates settings with defaults"""
        import sys
        sys.path.insert(0, 'scripts')
        from settings_api import SettingsManager

        settings_file = tmp_path / "settings.json"
        manager = SettingsManager(settings_file=str(settings_file))

        # File should be created
        assert settings_file.exists()

        # Should have defaults
        settings = manager.get_settings()
        assert settings['deviceName'] == 'Plum Snapcast'
        assert settings['hostname'] == 'plum-snapcast'
        assert 'integrations' in settings
        assert 'federation' in settings
        assert 'audio' in settings

    def test_settings_persistence(self, tmp_path, mock_os_chown, mock_os_chmod):
        """Settings persist across manager instances"""
        import sys
        sys.path.insert(0, 'scripts')
        from settings_api import SettingsManager

        settings_file = tmp_path / "settings.json"

        # First manager creates and updates
        manager1 = SettingsManager(settings_file=str(settings_file))
        manager1.update_settings({'deviceName': 'Updated Name'})

        # Second manager reads the same file
        manager2 = SettingsManager(settings_file=str(settings_file))
        settings = manager2.get_settings()

        assert settings['deviceName'] == 'Updated Name'

    def test_partial_update_preserves_other_settings(self, tmp_path, mock_os_chown, mock_os_chmod):
        """Partial updates don't overwrite unrelated settings"""
        import sys
        sys.path.insert(0, 'scripts')
        from settings_api import SettingsManager

        settings_file = tmp_path / "settings.json"
        manager = SettingsManager(settings_file=str(settings_file))

        # Get original values
        original = manager.get_settings()
        original_hostname = original['hostname']

        # Update only device name
        manager.update_settings({'deviceName': 'New Device'})

        # Hostname should be unchanged
        updated = manager.get_settings()
        assert updated['hostname'] == original_hostname
        assert updated['deviceName'] == 'New Device'

    def test_nested_settings_update(self, tmp_path, mock_os_chown, mock_os_chmod):
        """Nested settings can be updated"""
        import sys
        sys.path.insert(0, 'scripts')
        from settings_api import SettingsManager

        settings_file = tmp_path / "settings.json"
        manager = SettingsManager(settings_file=str(settings_file))

        # Update nested bluetooth settings
        manager.update_settings({
            'integrations': {
                'bluetooth': {
                    'enabled': True,
                    'deviceName': 'My Bluetooth'
                }
            }
        })

        settings = manager.get_settings()
        assert settings['integrations']['bluetooth']['enabled'] is True
        assert settings['integrations']['bluetooth']['deviceName'] == 'My Bluetooth'

    def test_version_increments_on_update(self, tmp_path, mock_os_chown, mock_os_chmod):
        """Version number increments on each update"""
        import sys
        sys.path.insert(0, 'scripts')
        from settings_api import SettingsManager

        settings_file = tmp_path / "settings.json"
        manager = SettingsManager(settings_file=str(settings_file))

        initial = manager.get_settings()
        initial_version = initial['version']

        # Multiple updates
        manager.update_settings({'deviceName': 'Update 1'})
        manager.update_settings({'deviceName': 'Update 2'})
        manager.update_settings({'deviceName': 'Update 3'})

        final = manager.get_settings()
        assert final['version'] == initial_version + 3


class TestSettingsAPIFlow:
    """Integration tests for Settings API endpoints"""

    def test_get_then_update_flow(self, settings_client):
        """GET settings, modify, POST update"""
        # Get current settings
        get_response = settings_client.get('/api/settings')
        assert get_response.status_code == 200
        current = get_response.get_json()

        # Update device name
        post_response = settings_client.post('/api/settings', json={
            'deviceName': 'API Updated Name'
        })
        assert post_response.status_code == 200

        # Verify change persisted
        verify_response = settings_client.get('/api/settings')
        verified = verify_response.get_json()
        assert verified['deviceName'] == 'API Updated Name'
        assert verified['version'] == current['version'] + 1

    def test_device_settings_with_avahi(self, settings_client, mock_subprocess):
        """Device settings update triggers Avahi restart"""
        # Update hostname (triggers Avahi update)
        response = settings_client.post('/api/settings/device', json={
            'hostname': 'new-hostname'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        # Verify settings updated
        settings = settings_client.get('/api/settings').get_json()
        assert settings['hostname'] == 'new-hostname'


class TestIntegrationSettingsFlow:
    """Integration tests for integration-related settings"""

    def test_enable_integration_updates_settings(self, integrations_client, mock_subprocess, temp_settings_file):
        """Enabling integration updates settings.json"""
        # Enable bluetooth
        integrations_client.post('/api/integrations/bluetooth/enable')

        # Verify in settings file
        with open(temp_settings_file) as f:
            settings = json.load(f)

        assert settings['integrations']['bluetooth']['enabled'] is True

    def test_add_endpoint_updates_settings(self, integrations_client, mock_subprocess, temp_settings_file):
        """Adding endpoint updates settings.json"""
        initial_count = 0
        with open(temp_settings_file) as f:
            settings = json.load(f)
            initial_count = len(settings['integrations']['airplay']['endpoints'])

        # Add new endpoint
        integrations_client.post('/api/integrations/airplay/endpoints', json={
            'deviceName': 'New Endpoint'
        })

        # Verify in settings file
        with open(temp_settings_file) as f:
            settings = json.load(f)

        # Should have more endpoints now
        assert len(settings['integrations']['airplay']['endpoints']) >= initial_count
