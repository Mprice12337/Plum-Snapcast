"""
Mock filesystem for testing file operations
"""

import json
import os
from typing import Dict, Any, Optional
from unittest.mock import MagicMock, patch


class MockFileSystem:
    """
    Mock filesystem for testing file read/write operations.

    Provides an in-memory filesystem that can be used to test code
    that reads/writes files without touching the actual filesystem.

    Usage:
        mock_fs = MockFileSystem()
        mock_fs.write_json('/app/data/settings.json', {'key': 'value'})

        with mock_fs.patch():
            # Your test code that reads/writes files
            pass
    """

    def __init__(self):
        self.files: Dict[str, str] = {}
        self.directories: set = set()

    def write_file(self, path: str, content: str):
        """Write content to a virtual file"""
        self.files[path] = content
        # Ensure parent directories exist
        parent = os.path.dirname(path)
        while parent and parent != '/':
            self.directories.add(parent)
            parent = os.path.dirname(parent)

    def read_file(self, path: str) -> str:
        """Read content from a virtual file"""
        if path not in self.files:
            raise FileNotFoundError(f"No such file: {path}")
        return self.files[path]

    def write_json(self, path: str, data: Any):
        """Write JSON data to a virtual file"""
        self.write_file(path, json.dumps(data, indent=2))

    def read_json(self, path: str) -> Any:
        """Read JSON data from a virtual file"""
        content = self.read_file(path)
        return json.loads(content)

    def exists(self, path: str) -> bool:
        """Check if a file or directory exists"""
        return path in self.files or path in self.directories

    def is_file(self, path: str) -> bool:
        """Check if path is a file"""
        return path in self.files

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory"""
        return path in self.directories

    def makedirs(self, path: str, exist_ok: bool = False):
        """Create a directory path"""
        if path in self.files:
            if not exist_ok:
                raise FileExistsError(f"File exists: {path}")
        parts = path.split('/')
        current = ''
        for part in parts:
            if part:
                current = current + '/' + part
                self.directories.add(current)

    def remove(self, path: str):
        """Remove a file"""
        if path in self.files:
            del self.files[path]
        else:
            raise FileNotFoundError(f"No such file: {path}")

    def listdir(self, path: str) -> list:
        """List directory contents"""
        if path not in self.directories and path != '/':
            raise FileNotFoundError(f"No such directory: {path}")

        contents = set()
        path = path.rstrip('/') + '/'

        for file_path in self.files:
            if file_path.startswith(path):
                remainder = file_path[len(path):]
                if '/' in remainder:
                    contents.add(remainder.split('/')[0])
                else:
                    contents.add(remainder)

        for dir_path in self.directories:
            if dir_path.startswith(path):
                remainder = dir_path[len(path):]
                if '/' in remainder:
                    contents.add(remainder.split('/')[0])
                else:
                    contents.add(remainder)

        return list(contents)

    def reset(self):
        """Clear all files and directories"""
        self.files.clear()
        self.directories.clear()

    def patch(self):
        """
        Return a context manager that patches file operations.

        Usage:
            with mock_fs.patch():
                with open('/path/to/file', 'w') as f:
                    f.write('content')
        """
        mock_fs = self

        class MockOpen:
            def __init__(self, path: str, mode: str = 'r', *args, **kwargs):
                self.path = path
                self.mode = mode
                self.content = ''
                self.position = 0

                if 'r' in mode:
                    if path not in mock_fs.files:
                        raise FileNotFoundError(f"No such file: {path}")
                    self.content = mock_fs.files[path]

            def read(self) -> str:
                content = self.content[self.position:]
                self.position = len(self.content)
                return content

            def write(self, content: str):
                self.content = content

            def writelines(self, lines):
                self.content = ''.join(lines)

            def readlines(self):
                return self.content.split('\n')

            def __enter__(self):
                return self

            def __exit__(self, *args):
                if 'w' in self.mode or 'a' in self.mode:
                    mock_fs.files[self.path] = self.content

            def __iter__(self):
                return iter(self.content.splitlines(keepends=True))

        def mock_exists(path: str) -> bool:
            return mock_fs.exists(path)

        def mock_makedirs(path: str, exist_ok: bool = False):
            mock_fs.makedirs(path, exist_ok=exist_ok)

        return patch.multiple(
            'builtins',
            open=MockOpen
        )


class MockSettingsFile:
    """
    Convenience class for mocking the settings.json file.

    Usage:
        mock_settings = MockSettingsFile()
        mock_settings.set({'deviceName': 'Test'})

        with mock_settings.patch():
            # Test code that reads/writes settings
            pass
    """

    DEFAULT_SETTINGS = {
        "version": 1,
        "deviceName": "Plum Snapcast",
        "hostname": "plum-snapcast",
        "integrations": {
            "airplay": {
                "endpoints": [
                    {"id": "1", "enabled": True, "deviceName": "Plum Audio", "port": 5050, "udpPortBase": 6001}
                ]
            },
            "bluetooth": {
                "enabled": False, "deviceName": "Plum Audio", "adapter": "hci0",
                "autoPair": True, "discoverable": True
            },
            "spotify": {
                "bitrate": 320,
                "endpoints": [
                    {"id": "1", "enabled": False, "deviceName": "Plum Audio", "zeroconfPort": 5354}
                ]
            },
            "dlna": {"endpoints": []},
            "plexamp": {"available": False, "enabled": False, "sourceName": "Plexamp"},
            "snapcast": True,
            "visualizer": {"enabled": True, "theme": "user", "type": "circular"}
        },
        "federation": {"enabled": False, "autoDiscover": True},
        "audio": {
            "output": {"device": "hw:Headphones", "device_type": "BUILTIN_HEADPHONES"},
            "input": {"devices": []}
        }
    }

    def __init__(self, path: str = '/app/data/settings.json'):
        self.path = path
        self._settings = self.DEFAULT_SETTINGS.copy()
        self._fs = MockFileSystem()

    def set(self, settings: Dict[str, Any]):
        """Set settings data"""
        self._settings = settings
        self._fs.write_json(self.path, settings)

    def update(self, updates: Dict[str, Any]):
        """Update settings with partial data"""
        self._settings.update(updates)
        self._fs.write_json(self.path, self._settings)

    def get(self) -> Dict[str, Any]:
        """Get current settings"""
        return self._settings.copy()

    def patch(self):
        """Return context manager for patching"""
        self._fs.write_json(self.path, self._settings)
        self._fs.makedirs(os.path.dirname(self.path), exist_ok=True)
        return self._fs.patch()
