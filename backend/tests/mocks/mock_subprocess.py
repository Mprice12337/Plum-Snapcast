"""
Mock subprocess for testing supervisorctl and other system commands
"""

from typing import Dict, List, Any, Optional
from unittest.mock import MagicMock
import re


class MockSubprocess:
    """
    Mock for subprocess.run that simulates supervisorctl commands.

    Usage:
        mock_proc = MockSubprocess()
        with patch('subprocess.run', mock_proc):
            # Your test code
            pass
    """

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.service_states: Dict[str, str] = {}
        self._default_services = [
            'shairport-sync-1', 'airplay-1-fifo-keeper', 'airplay-1-lifecycle-manager',
            'bluetoothd', 'bluetooth-init', 'bluealsa', 'bluealsa-aplay',
            'bluetooth-monitor', 'bluetooth-fifo-keeper', 'bluetooth-stream-lifecycle-manager',
            'spotifyd-1', 'spotify-1-fifo-keeper', 'spotify-1-lifecycle-manager',
            'gmrender-1', 'dlna-1-fifo-keeper', 'dlna-1-lifecycle-manager',
            'plexamp-stream-lifecycle-manager', 'snapclient', 'avahi'
        ]
        for service in self._default_services:
            self.service_states[service] = 'STOPPED'

    def __call__(self, cmd: List[str], *args, **kwargs) -> MagicMock:
        """Handle subprocess.run call"""
        self.calls.append({
            'cmd': cmd,
            'args': args,
            'kwargs': kwargs
        })

        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""

        # Parse supervisorctl commands
        if 'supervisorctl' in cmd:
            result = self._handle_supervisorctl(cmd)
        elif 'aplay' in cmd:
            result = self._handle_aplay(cmd)
        elif 'avahi-browse' in cmd:
            result = self._handle_avahi_browse(cmd)

        return result

    def _handle_supervisorctl(self, cmd: List[str]) -> MagicMock:
        """Handle supervisorctl commands"""
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""

        # Find the action (start, stop, restart, status)
        action = None
        service = None
        for i, part in enumerate(cmd):
            if part in ('start', 'stop', 'restart', 'status'):
                action = part
                if i + 1 < len(cmd):
                    service = cmd[i + 1]
                break

        if action == 'start' and service:
            if service in self.service_states:
                self.service_states[service] = 'RUNNING'
                result.stdout = f"{service}: started"
            else:
                result.returncode = 1
                result.stderr = f"ERROR (no such process): {service}"

        elif action == 'stop' and service:
            if service in self.service_states:
                self.service_states[service] = 'STOPPED'
                result.stdout = f"{service}: stopped"
            else:
                result.returncode = 1
                result.stderr = f"ERROR (no such process): {service}"

        elif action == 'restart' and service:
            if service in self.service_states:
                self.service_states[service] = 'RUNNING'
                result.stdout = f"{service}: stopped\n{service}: started"
            else:
                result.returncode = 1
                result.stderr = f"ERROR (no such process): {service}"

        elif action == 'status':
            if service:
                if service in self.service_states:
                    state = self.service_states[service]
                    result.stdout = f"{service}                         {state}"
                else:
                    result.returncode = 1
                    result.stderr = f"ERROR (no such process): {service}"
            else:
                # List all services
                lines = []
                for svc, state in self.service_states.items():
                    lines.append(f"{svc:<35} {state}")
                result.stdout = "\n".join(lines)

        return result

    def _handle_aplay(self, cmd: List[str]) -> MagicMock:
        """Handle aplay commands (audio device listing)"""
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""

        if '-l' in cmd or '--list-devices' in cmd:
            result.stdout = """**** List of PLAYBACK Hardware Devices ****
card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]
  Subdevices: 8/8
  Subdevice #0: subdevice #0
card 1: vc4hdmi0 [vc4-hdmi-0], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""
        return result

    def _handle_avahi_browse(self, cmd: List[str]) -> MagicMock:
        """Handle avahi-browse commands"""
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = ""  # Default empty, use mock_avahi_output fixture
        return result

    def set_service_state(self, service: str, state: str):
        """Set the state of a service for testing"""
        self.service_states[service] = state

    def add_service(self, service: str, state: str = 'STOPPED'):
        """Add a new service for testing"""
        self.service_states[service] = state

    def get_calls_for(self, cmd_pattern: str) -> List[Dict[str, Any]]:
        """Get all calls matching a command pattern"""
        return [
            call for call in self.calls
            if any(cmd_pattern in part for part in call['cmd'])
        ]

    def reset(self):
        """Reset all state"""
        self.calls.clear()
        for service in self.service_states:
            self.service_states[service] = 'STOPPED'


def mock_supervisorctl(states: Optional[Dict[str, str]] = None):
    """
    Create a mock subprocess specifically for supervisorctl.

    Args:
        states: Optional dict of service_name -> state to initialize

    Usage:
        with patch('subprocess.run', mock_supervisorctl({'shairport-sync-1': 'RUNNING'})):
            # Test code
            pass
    """
    mock = MockSubprocess()
    if states:
        for service, state in states.items():
            mock.set_service_state(service, state)
    return mock
