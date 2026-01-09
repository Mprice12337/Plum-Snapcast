"""
Shared pytest fixtures for Plum-Snapcast backend tests
"""

import json
import os
import sys
import tempfile
from typing import Dict, Any, Generator
from unittest.mock import MagicMock, patch

import pytest

# Add the scripts directory to Python path for imports
scripts_dir = os.path.join(os.path.dirname(__file__), '..', 'scripts')
sys.path.insert(0, scripts_dir)

# Import after path setup
from flask import Flask


# =============================================================================
# Default Test Data
# =============================================================================

DEFAULT_TEST_SETTINGS = {
    "version": 1,
    "deviceName": "Test Plum Snapcast",
    "hostname": "test-plum-snapcast",
    "integrations": {
        "airplay": {
            "endpoints": [
                {
                    "id": "1",
                    "enabled": True,
                    "deviceName": "Test AirPlay",
                    "port": 5050,
                    "udpPortBase": 6001
                }
            ]
        },
        "bluetooth": {
            "enabled": False,
            "deviceName": "Test Bluetooth",
            "adapter": "hci0",
            "autoPair": True,
            "discoverable": True
        },
        "spotify": {
            "bitrate": 320,
            "endpoints": [
                {
                    "id": "1",
                    "enabled": False,
                    "deviceName": "Test Spotify",
                    "zeroconfPort": 5354
                }
            ]
        },
        "dlna": {
            "endpoints": []
        },
        "plexamp": {
            "available": False,
            "enabled": False,
            "sourceName": "Plexamp"
        },
        "snapcast": True,
        "visualizer": {
            "enabled": True,
            "theme": "user",
            "type": "circular",
            "barCount": 128,
            "sensitivity": 50,
            "smoothing": 70
        }
    },
    "federation": {
        "enabled": False,
        "autoDiscover": True
    },
    "audio": {
        "output": {
            "device": "hw:Headphones",
            "device_type": "BUILTIN_HEADPHONES",
            "fallback_device": "hw:Headphones"
        },
        "input": {
            "devices": []
        }
    }
}


# =============================================================================
# File System Fixtures
# =============================================================================

@pytest.fixture
def temp_settings_file(tmp_path) -> Generator[str, None, None]:
    """Create a temporary settings file for testing"""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps(DEFAULT_TEST_SETTINGS))
    yield str(settings_file)


@pytest.fixture
def temp_data_dir(tmp_path) -> Generator[str, None, None]:
    """Create a temporary data directory"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    yield str(data_dir)


# =============================================================================
# Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for supervisorctl commands"""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="OK",
            stderr=""
        )
        yield mock_run


@pytest.fixture
def mock_os_chown():
    """Mock os.chown to avoid permission errors in tests"""
    with patch('os.chown'):
        yield


@pytest.fixture
def mock_os_chmod():
    """Mock os.chmod to avoid permission errors in tests"""
    with patch('os.chmod'):
        yield


# =============================================================================
# Flask App Fixtures
# =============================================================================

@pytest.fixture
def settings_app(temp_settings_file, mock_os_chown, mock_os_chmod) -> Flask:
    """Create Flask test app for Settings API"""
    from settings_api import create_settings_blueprint, SettingsManager

    app = Flask(__name__)
    app.config['TESTING'] = True

    manager = SettingsManager(settings_file=temp_settings_file)
    bp = create_settings_blueprint(manager)
    app.register_blueprint(bp)

    return app


@pytest.fixture
def settings_client(settings_app):
    """Create test client for Settings API"""
    return settings_app.test_client()


@pytest.fixture
def playback_app() -> Flask:
    """Create Flask test app for Playback API"""
    from playback_api import create_playback_blueprint, playback_store

    # Clear the global store between tests
    playback_store._data.clear()

    app = Flask(__name__)
    app.config['TESTING'] = True

    bp = create_playback_blueprint()
    app.register_blueprint(bp)

    return app


@pytest.fixture
def playback_client(playback_app):
    """Create test client for Playback API"""
    return playback_app.test_client()


@pytest.fixture
def integrations_app(temp_settings_file, mock_subprocess, mock_os_chown, mock_os_chmod) -> Flask:
    """Create Flask test app for Integrations API"""
    from integrations_api import create_integrations_blueprint
    from settings_api import SettingsManager

    app = Flask(__name__)
    app.config['TESTING'] = True

    # Store original __init__
    original_init = SettingsManager.__init__

    # Patch SettingsManager to always use temp file
    def patched_init(self, settings_file=None):
        original_init(self, settings_file=temp_settings_file)

    with patch.object(SettingsManager, '__init__', patched_init):
        bp = create_integrations_blueprint()
        app.register_blueprint(bp)

    return app


@pytest.fixture
def integrations_client(integrations_app):
    """Create test client for Integrations API"""
    return integrations_app.test_client()


@pytest.fixture
def audio_app(temp_settings_file, mock_subprocess, mock_os_chown, mock_os_chmod) -> Flask:
    """Create Flask test app for Audio API"""
    from audio_api import create_audio_blueprint, AudioConfigController
    from settings_api import SettingsManager

    app = Flask(__name__)
    app.config['TESTING'] = True

    # Create a settings manager with the temp file
    settings_manager = SettingsManager(settings_file=temp_settings_file)

    # Mock AudioDeviceManager since it accesses system devices
    with patch('audio_api.AudioDeviceManager') as MockDeviceManager:
        # Create mock device manager instance
        mock_device_mgr = MagicMock()
        mock_device_mgr.get_playback_devices.return_value = []
        mock_device_mgr.get_capture_devices.return_value = []
        mock_device_mgr.get_device_by_hw_id.return_value = None
        MockDeviceManager.return_value = mock_device_mgr

        # Create controller with our settings manager
        audio_controller = AudioConfigController(settings_manager=settings_manager)
        # Override the device manager with our mock
        audio_controller.device_manager = mock_device_mgr

        bp = create_audio_blueprint(audio_controller=audio_controller)
        app.register_blueprint(bp)

    return app


@pytest.fixture
def audio_client(audio_app):
    """Create test client for Audio API"""
    return audio_app.test_client()


# =============================================================================
# Test Data Factories
# =============================================================================

@pytest.fixture
def make_stream_data():
    """Factory for creating test stream data"""
    def _make_stream(
        stream_id: str = "test-stream",
        position: int = 0,
        duration: int = 180000,
        playback_status: str = "playing",
        **extra
    ) -> Dict[str, Any]:
        return {
            "position": position,
            "duration": duration,
            "playback_status": playback_status,
            **extra
        }
    return _make_stream


@pytest.fixture
def make_endpoint_data():
    """Factory for creating test endpoint data"""
    def _make_endpoint(
        device_name: str = "Test Device",
        enabled: bool = True
    ) -> Dict[str, Any]:
        return {
            "deviceName": device_name,
            "enabled": enabled
        }
    return _make_endpoint


# =============================================================================
# Federation Fixtures (for async tests)
# =============================================================================

@pytest.fixture
def mock_websocket():
    """Mock WebSocket connection for federation tests"""
    mock_ws = MagicMock()
    mock_ws.send = MagicMock()
    mock_ws.recv = MagicMock(return_value=json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {}
    }))
    mock_ws.close = MagicMock()
    return mock_ws


@pytest.fixture
def mock_avahi_output():
    """Sample Avahi browse output for testing discovery"""
    return """=;en0;IPv4;Plum Snapcast;_snapcast-http._tcp;local;plum-snapcast.local;192.168.1.100;1780;"version=0.27"
=;en0;IPv4;Kitchen Audio;_snapcast-http._tcp;local;kitchen-audio.local;192.168.1.101;1780;"version=0.27"
"""


# =============================================================================
# Environment Fixtures
# =============================================================================

@pytest.fixture
def clean_env():
    """Ensure a clean environment for tests that depend on env vars"""
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def plexamp_enabled_env(clean_env):
    """Set PLEXAMP_ENABLED=1 for tests"""
    os.environ['PLEXAMP_ENABLED'] = '1'
    yield


@pytest.fixture
def plexamp_disabled_env(clean_env):
    """Set PLEXAMP_ENABLED=0 for tests"""
    os.environ['PLEXAMP_ENABLED'] = '0'
    yield
