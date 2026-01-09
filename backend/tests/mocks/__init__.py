# Mock modules for testing
from .mock_subprocess import MockSubprocess, mock_supervisorctl
from .mock_filesystem import MockFileSystem
from .mock_avahi import MockAvahiDiscovery
from .mock_websocket import MockWebSocket, MockSnapcastConnection

__all__ = [
    'MockSubprocess',
    'mock_supervisorctl',
    'MockFileSystem',
    'MockAvahiDiscovery',
    'MockWebSocket',
    'MockSnapcastConnection',
]
