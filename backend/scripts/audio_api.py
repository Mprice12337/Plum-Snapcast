#!/usr/bin/env python3
"""
Audio Configuration API
Provides endpoints for audio device discovery and configuration
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Dict, Any, List, Optional, Tuple
from flask import Blueprint, jsonify, request

# Import AudioDeviceManager and SettingsManager
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_devices import AudioDeviceManager, DeviceType
from settings_api import SettingsManager

logger = logging.getLogger(__name__)

# Configuration
SUPERVISORCTL_CONF = "/app/supervisord/supervisord.conf"


class MPRISVolumeController:
    """
    Direct D-Bus/MPRIS volume control for integration sources.
    Works with AirPlay, Spotify, Bluetooth, etc.
    Uses subprocess approach to avoid D-Bus session bus connection issues.
    """

    # Map integration keywords to MPRIS service name patterns
    # Uses flexible keyword matching instead of strict regex patterns
    # to support custom stream names like "AirPlay - Office DeskPi - AP 1"
    INTEGRATION_MPRIS_MAP = {
        # AirPlay: org.mpris.MediaPlayer2.ShairportSync or ShairportSync.i*
        'airplay': r'org\.mpris\.MediaPlayer2\.ShairportSync(\.i\d+)?$',
        # Spotify: org.mpris.MediaPlayer2.spotifyd or spotifyd.instance*
        'spotify': r'org\.mpris\.MediaPlayer2\.spotifyd(\.instance\d+)?$',
        # Bluetooth: org.mpris.MediaPlayer2.* (various players)
        'bluetooth': r'org\.mpris\.MediaPlayer2\.',
        # DLNA: org.mpris.MediaPlayer2.GMediaRender or gmediarender*
        'dlna': r'org\.mpris\.MediaPlayer2\.GMediaRender',
        # Plexamp: org.mpris.MediaPlayer2.Plexamp
        'plexamp': r'org\.mpris\.MediaPlayer2\.Plexamp$',
    }

    def __init__(self):
        pass

    def _find_mpris_service_via_subprocess(self, stream_id: str) -> Optional[str]:
        """Find MPRIS service using dbus-send command"""
        try:
            # List all MPRIS services using dbus-send (use system bus, not session bus)
            result = subprocess.run(
                ['dbus-send', '--system', '--dest=org.freedesktop.DBus',
                 '--type=method_call', '--print-reply',
                 '/org/freedesktop/DBus', 'org.freedesktop.DBus.ListNames'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"Failed to list D-Bus services: {result.stderr}")
                return None

            # Parse output for MPRIS services
            mpris_services = []
            for line in result.stdout.split('\n'):
                if 'org.mpris.MediaPlayer2.' in line:
                    # Extract service name from dbus-send output
                    # Format: string "org.mpris.MediaPlayer2.ShairportSync"
                    match = re.search(r'"(org\.mpris\.MediaPlayer2\.[^"]+)"', line)
                    if match:
                        mpris_services.append(match.group(1))

            logger.debug(f"Found MPRIS services: {mpris_services}")

            # Match stream ID to service using flexible keyword matching
            # Check if any integration keyword appears in the stream ID (case-insensitive)
            stream_id_lower = stream_id.lower()

            for keyword, mpris_pattern in self.INTEGRATION_MPRIS_MAP.items():
                if keyword in stream_id_lower:
                    logger.debug(f"Stream '{stream_id}' contains keyword '{keyword}', looking for MPRIS pattern: {mpris_pattern}")
                    for service in mpris_services:
                        if re.match(mpris_pattern, service):
                            logger.info(f"Found MPRIS service {service} for stream {stream_id}")
                            return service
                    # Keyword found but no matching service
                    logger.warning(f"Keyword '{keyword}' found in stream ID but no matching MPRIS service")

            logger.warning(f"No MPRIS service found for stream {stream_id}")
            return None

        except Exception as e:
            logger.error(f"Error finding MPRIS service: {e}")
            return None

    def _find_mpris_service(self, stream_id: str) -> Optional[str]:
        """Find MPRIS service - wrapper that calls subprocess implementation"""
        return self._find_mpris_service_via_subprocess(stream_id)

    def _find_bluetooth_transport(self) -> Optional[str]:
        """Find active Bluetooth MediaTransport1 object path for volume control"""
        try:
            # Use dbus-send to get all BlueZ managed objects
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 '--dest=org.bluez', '/',
                 'org.freedesktop.DBus.ObjectManager.GetManagedObjects'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.debug(f"Failed to get BlueZ managed objects: {result.stderr}")
                return None

            # Parse the output to find MediaTransport1 paths
            # Format: object path "/org/bluez/.../fdN" followed by interface lines
            # When we see MediaTransport1, the preceding object path is the transport
            lines = result.stdout.split('\n')
            current_path = None

            for line in lines:
                # Look for object path lines - format: object path "/org/bluez/hci0/dev_.../fd0"
                path_match = re.search(r'object path "(/org/bluez/[^"]+)"', line)
                if path_match:
                    current_path = path_match.group(1)

                # Check if this object has MediaTransport1 interface
                # Format: string "org.bluez.MediaTransport1"
                if current_path and 'org.bluez.MediaTransport1' in line:
                    logger.info(f"Found Bluetooth transport: {current_path}")
                    return current_path

            logger.debug("No active Bluetooth MediaTransport1 found")
            return None

        except subprocess.TimeoutExpired:
            logger.error("Timeout finding Bluetooth transport")
            return None
        except Exception as e:
            logger.error(f"Error finding Bluetooth transport: {e}")
            return None

    def _set_bluetooth_volume(self, volume: int) -> Tuple[bool, str]:
        """Set Bluetooth volume via MediaTransport1 (AVRCP Absolute Volume)"""
        transport_path = self._find_bluetooth_transport()
        if not transport_path:
            return False, "No active Bluetooth audio connection found"

        try:
            # Convert 0-100 to 0-127 for AVRCP
            raw_volume = int(round(volume * 1.27))
            raw_volume = max(0, min(127, raw_volume))

            # Set volume using dbus-send on system bus
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 '--dest=org.bluez',
                 transport_path,
                 'org.freedesktop.DBus.Properties.Set',
                 'string:org.bluez.MediaTransport1',
                 'string:Volume',
                 f'variant:uint16:{raw_volume}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                # Check if it's because Absolute Volume isn't supported
                if 'not supported' in result.stderr.lower() or 'permission' in result.stderr.lower():
                    return False, "Device does not support AVRCP Absolute Volume control"
                logger.error(f"Failed to set Bluetooth volume: {result.stderr}")
                return False, f"Failed to set Bluetooth volume: {result.stderr}"

            logger.info(f"Set Bluetooth volume to {volume}% (raw: {raw_volume}/127)")
            return True, f"Volume set to {volume}%"

        except subprocess.TimeoutExpired:
            return False, "Timeout setting Bluetooth volume"
        except Exception as e:
            logger.error(f"Error setting Bluetooth volume: {e}")
            return False, f"Error: {str(e)}"

    def _get_bluetooth_volume(self) -> Tuple[bool, int, str]:
        """Get Bluetooth volume via MediaTransport1"""
        transport_path = self._find_bluetooth_transport()
        if not transport_path:
            return False, 0, "No active Bluetooth audio connection found"

        try:
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 '--dest=org.bluez',
                 transport_path,
                 'org.freedesktop.DBus.Properties.Get',
                 'string:org.bluez.MediaTransport1',
                 'string:Volume'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return False, 0, f"Failed to get Bluetooth volume: {result.stderr}"

            # Parse volume from output - format: variant uint16 XX
            match = re.search(r'uint16\s+(\d+)', result.stdout)
            if match:
                raw_volume = int(match.group(1))
                volume_percent = int(round(raw_volume / 1.27))
                return True, volume_percent, f"Volume: {volume_percent}%"

            return False, 0, "Could not parse Bluetooth volume"

        except Exception as e:
            return False, 0, f"Error: {str(e)}"

    # Plexamp HTTP API constants (separate container, no D-Bus access)
    PLEXAMP_HOST = "127.0.0.1"
    PLEXAMP_PORT = 32500

    def _set_plexamp_volume(self, volume: int) -> Tuple[bool, str]:
        """Set Plexamp volume via HTTP API (separate container, no MPRIS/D-Bus access)"""
        try:
            # Plexamp uses 0-100 scale same as our API
            url = f"http://{self.PLEXAMP_HOST}:{self.PLEXAMP_PORT}/player/playback/setParameters?volume={volume}"
            result = subprocess.run(
                ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
                 '--connect-timeout', '2', url],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0 and result.stdout.strip() == '200':
                logger.info(f"Set Plexamp volume to {volume}% via HTTP API")
                return True, f"Volume set to {volume}%"
            else:
                logger.error(f"Failed to set Plexamp volume: HTTP {result.stdout}")
                return False, f"Failed to set Plexamp volume: HTTP {result.stdout}"

        except subprocess.TimeoutExpired:
            return False, "Timeout setting Plexamp volume"
        except Exception as e:
            logger.error(f"Error setting Plexamp volume: {e}")
            return False, f"Error: {str(e)}"

    def _get_plexamp_volume(self) -> Tuple[bool, int, str]:
        """Get Plexamp volume via HTTP timeline API"""
        try:
            import xml.etree.ElementTree as ET
            url = f"http://{self.PLEXAMP_HOST}:{self.PLEXAMP_PORT}/player/timeline/poll?wait=0"
            result = subprocess.run(
                ['curl', '-s', '--connect-timeout', '2', url],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return False, 0, f"Failed to get Plexamp timeline: {result.stderr}"

            # Parse XML response for volume attribute
            try:
                root = ET.fromstring(result.stdout)
                for timeline in root.findall('.//Timeline'):
                    volume = timeline.get('volume')
                    if volume is not None:
                        return True, int(volume), f"Volume: {volume}%"
            except ET.ParseError:
                pass

            return False, 0, "Could not parse Plexamp volume"

        except Exception as e:
            return False, 0, f"Error: {str(e)}"

    def set_volume(self, stream_id: str, volume: int) -> Tuple[bool, str]:
        """
        Set volume for a stream via D-Bus

        Args:
            stream_id: Stream ID (e.g., airplay1, spotify2)
            volume: Volume level (0-100)

        Returns:
            Tuple of (success, message)
        """
        # Extract local stream ID from federated ID if needed
        # Format: "server-192-168-7-122-airplay1" -> "airplay1"
        local_stream_id = stream_id
        if stream_id.startswith("server-"):
            parts = stream_id.split("-")
            if len(parts) >= 6:
                local_stream_id = "-".join(parts[5:])
                logger.debug(f"Extracted local stream ID: {local_stream_id} from {stream_id}")

        # Check if this is a Bluetooth stream - use MediaTransport1 for AVRCP volume
        if 'bluetooth' in local_stream_id.lower():
            return self._set_bluetooth_volume(volume)

        # Check if this is a Plexamp stream - use HTTP API (separate container, no D-Bus)
        if 'plexamp' in local_stream_id.lower():
            return self._set_plexamp_volume(volume)

        # Find MPRIS service for non-Bluetooth streams
        service = self._find_mpris_service(local_stream_id)
        if not service:
            return False, f"No MPRIS service found for stream {local_stream_id}"

        try:
            # Convert 0-100 to 0.0-1.0 for MPRIS
            mpris_volume = max(0.0, min(1.0, volume / 100.0))

            # Try standard MPRIS Properties.Set first (works for spotifyd, standard MPRIS players)
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 f'--dest={service}',
                 '/org/mpris/MediaPlayer2',
                 'org.freedesktop.DBus.Properties.Set',
                 'string:org.mpris.MediaPlayer2.Player',
                 'string:Volume',
                 f'variant:double:{mpris_volume}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                logger.info(f"Set volume for {local_stream_id} ({service}) to {volume}% via Properties.Set")
                return True, f"Volume set to {volume}%"

            # Fallback to ShairportSync's custom SetVolume method
            logger.debug(f"Properties.Set failed, trying SetVolume method: {result.stderr}")
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 f'--dest={service}',
                 '/org/mpris/MediaPlayer2',
                 'org.mpris.MediaPlayer2.Player.SetVolume',
                 f'double:{mpris_volume}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"dbus-send failed: {result.stderr}")
                return False, f"Failed to set volume: {result.stderr}"

            logger.info(f"Set volume for {local_stream_id} ({service}) to {volume}% via SetVolume method")
            return True, f"Volume set to {volume}%"

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout setting volume for {local_stream_id}")
            return False, "Timeout setting volume"
        except Exception as e:
            logger.error(f"Failed to set volume for {local_stream_id}: {e}")
            return False, f"Error setting volume: {str(e)}"

    def get_volume(self, stream_id: str) -> Tuple[bool, int, str]:
        """
        Get volume for a stream via D-Bus

        Args:
            stream_id: Stream ID (e.g., airplay1, spotify2)

        Returns:
            Tuple of (success, volume, message)
        """
        # Extract local stream ID from federated ID if needed
        local_stream_id = stream_id
        if stream_id.startswith("server-"):
            parts = stream_id.split("-")
            if len(parts) >= 6:
                local_stream_id = "-".join(parts[5:])

        # Check if this is a Bluetooth stream - use MediaTransport1
        if 'bluetooth' in local_stream_id.lower():
            return self._get_bluetooth_volume()

        # Check if this is a Plexamp stream - use HTTP API (separate container)
        if 'plexamp' in local_stream_id.lower():
            return self._get_plexamp_volume()

        # Find MPRIS service for non-Bluetooth streams
        service = self._find_mpris_service(local_stream_id)
        if not service:
            return False, 0, f"No MPRIS service found for stream {local_stream_id}"

        try:
            # Get volume using dbus-send (use system bus, not session bus)
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 f'--dest={service}',
                 '/org/mpris/MediaPlayer2',
                 'org.freedesktop.DBus.Properties.Get',
                 'string:org.mpris.MediaPlayer2.Player',
                 'string:Volume'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"dbus-send failed: {result.stderr}")
                return False, 0, f"Failed to get volume: {result.stderr}"

            # Parse output to get volume value
            # Format: "variant       double 0.5"
            match = re.search(r'double\s+([\d.]+)', result.stdout)
            if not match:
                logger.error(f"Could not parse volume from dbus-send output: {result.stdout}")
                return False, 0, "Failed to parse volume"

            mpris_volume = float(match.group(1))
            volume = int(mpris_volume * 100)

            logger.debug(f"Got volume for {local_stream_id}: {volume}% (MPRIS: {mpris_volume:.2f})")
            return True, volume, f"Volume: {volume}%"

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout getting volume for {local_stream_id}")
            return False, 0, "Timeout getting volume"
        except Exception as e:
            logger.error(f"Failed to get volume for {local_stream_id}: {e}")
            return False, 0, f"Error getting volume: {str(e)}"


class AudioConfigController:
    """Controls audio device configuration and snapclient service"""

    def __init__(self, settings_manager: SettingsManager = None):
        self.settings_manager = settings_manager or SettingsManager()
        self.device_manager = AudioDeviceManager()
        self.supervisorctl_cmd = [
            "supervisorctl",
            "-c",
            SUPERVISORCTL_CONF
        ]

    def _run_supervisorctl(self, *args) -> tuple[bool, str]:
        """Run supervisorctl command and return success status and output"""
        try:
            cmd = self.supervisorctl_cmd + list(args)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            success = result.returncode == 0
            output = result.stdout + result.stderr
            logger.info(f"supervisorctl {' '.join(args)}: {output.strip()}")
            return success, output
        except subprocess.TimeoutExpired:
            logger.error(f"supervisorctl timeout: {' '.join(args)}")
            return False, "Command timed out"
        except Exception as e:
            logger.error(f"supervisorctl error: {e}")
            return False, str(e)

    def get_output_devices(self) -> List[Dict[str, Any]]:
        """Get all available playback devices"""
        try:
            devices = self.device_manager.get_playback_devices()
            return [device.to_dict() for device in devices]
        except Exception as e:
            logger.error(f"Failed to get output devices: {e}")
            raise

    def get_input_devices(self) -> List[Dict[str, Any]]:
        """Get all available capture devices"""
        try:
            devices = self.device_manager.get_capture_devices()
            return [device.to_dict() for device in devices]
        except Exception as e:
            logger.error(f"Failed to get input devices: {e}")
            raise

    def get_current_output_device(self) -> Dict[str, Any]:
        """Get currently configured output device"""
        try:
            settings = self.settings_manager.get_settings()
            audio_settings = settings.get("audio", {})
            output_settings = audio_settings.get("output", {})

            device_hw_id = output_settings.get("device", "hw:Headphones")
            device_type = output_settings.get("device_type", "BUILTIN_HEADPHONES")

            # Try to get device info from device manager
            device = self.device_manager.get_device_by_hw_id(device_hw_id, is_playback=True)

            if device:
                return {
                    "hw_id": device.hw_id,
                    "hw_name": device.hw_name,
                    "friendly_name": device.friendly_name,
                    "type": device.type.value,
                    "is_available": device.is_available
                }
            else:
                # Device not found - return settings data
                logger.warning(f"Configured device {device_hw_id} not found")
                return {
                    "hw_id": device_hw_id,
                    "hw_name": None,
                    "friendly_name": f"Unknown Device ({device_hw_id})",
                    "type": device_type,
                    "is_available": False
                }

        except Exception as e:
            logger.error(f"Failed to get current output device: {e}")
            raise

    def set_output_device(self, hw_id: str) -> Dict[str, Any]:
        """
        Set output device and restart snapclient

        Args:
            hw_id: Hardware ID (e.g., hw:0,0 or hw:Headphones)

        Returns:
            Dictionary with success status and details
        """
        try:
            # Validate device exists
            device = self.device_manager.get_device_by_hw_id(hw_id, is_playback=True)

            if not device:
                logger.error(f"Device {hw_id} not found")
                return {
                    "success": False,
                    "error": f"Device {hw_id} not found or unavailable",
                    "fallback_device": "hw:Headphones"
                }

            logger.info(f"Setting output device to: {device.friendly_name} ({hw_id})")

            # Update settings FIRST (before restarting service)
            # This ensures the service reads the new device when it starts
            try:
                self.settings_manager.update_settings({
                    "audio": {
                        "output": {
                            "device": hw_id,
                            "device_type": device.type.value,
                            "fallback_device": "hw:Headphones"
                        }
                    }
                })
                logger.info("Settings updated successfully")
            except Exception as e:
                logger.error(f"Failed to update settings: {e}")
                return {
                    "success": False,
                    "error": f"Failed to save settings: {str(e)}"
                }

            # Check if snapclient is enabled
            settings = self.settings_manager.get_settings()
            snapclient_enabled = os.getenv("SNAPCLIENT_ENABLED", "1").strip() in ("1", "true", "True", "yes")

            if not snapclient_enabled:
                logger.info("Snapclient is disabled, skipping service restart")
                return {
                    "success": True,
                    "message": f"Output device changed to {device.friendly_name} (will apply when snapclient is enabled)",
                    "device": {
                        "hw_id": device.hw_id,
                        "friendly_name": device.friendly_name
                    }
                }

            # Stop snapclient
            logger.info("Stopping snapclient service...")
            stop_success, stop_output = self._run_supervisorctl("stop", "snapclient")

            if not stop_success:
                logger.warning(f"Failed to stop snapclient: {stop_output}")
                # Continue anyway - it might not be running

            # Wait for clean shutdown
            time.sleep(2)

            # Start snapclient (will read new settings via get-settings.py)
            logger.info("Starting snapclient service with new device...")
            start_success, start_output = self._run_supervisorctl("start", "snapclient")

            if not start_success:
                logger.error(f"Failed to start snapclient: {start_output}")
                return {
                    "success": False,
                    "error": f"Device settings saved but failed to restart snapclient: {start_output}",
                    "details": start_output
                }

            # Wait for service to initialize
            time.sleep(3)

            # Verify service started successfully
            verify_success, verify_output = self._run_supervisorctl("status", "snapclient")

            if not verify_success or "RUNNING" not in verify_output:
                logger.error(f"Snapclient failed to start: {verify_output}")
                return {
                    "success": False,
                    "error": "Service failed to start with new device",
                    "details": verify_output
                }

            logger.info(f"Successfully changed output device to {device.friendly_name}")

            return {
                "success": True,
                "message": f"Output device changed to {device.friendly_name}",
                "device": {
                    "hw_id": device.hw_id,
                    "friendly_name": device.friendly_name
                }
            }

        except Exception as e:
            logger.error(f"Failed to set output device: {e}")
            return {
                "success": False,
                "error": f"Error setting output device: {str(e)}"
            }

    def test_output_device(self, hw_id: str) -> Dict[str, Any]:
        """
        Test an output device (play brief test sound)

        Args:
            hw_id: Hardware ID (e.g., hw:0,0 or hw:Headphones)

        Returns:
            Dictionary with success status and message
        """
        try:
            logger.info(f"Testing output device: {hw_id}")

            # Validate device exists
            device = self.device_manager.get_device_by_hw_id(hw_id, is_playback=True)

            if not device:
                return {
                    "success": False,
                    "message": f"Device {hw_id} not found"
                }

            # Run device test
            success, message = self.device_manager.test_device(hw_id, is_playback=True)

            return {
                "success": success,
                "message": message,
                "device": {
                    "hw_id": device.hw_id,
                    "friendly_name": device.friendly_name
                }
            }

        except Exception as e:
            logger.error(f"Failed to test device: {e}")
            return {
                "success": False,
                "message": f"Error testing device: {str(e)}"
            }

    def get_configured_input_devices(self) -> List[Dict[str, Any]]:
        """Get list of configured input devices from settings"""
        try:
            settings = self.settings_manager.get_settings()
            audio_settings = settings.get("audio", {})
            input_settings = audio_settings.get("input", {})
            configured_devices = input_settings.get("devices", [])

            # Enrich with current device availability
            available_devices = {d.hw_id: d for d in self.device_manager.get_capture_devices()}

            enriched = []
            for config in configured_devices:
                hw_id = config.get("hw_id")
                device_info = available_devices.get(hw_id)

                enriched.append({
                    "hw_id": hw_id,
                    "custom_name": config.get("custom_name", ""),
                    "enabled": config.get("enabled", False),
                    "is_available": device_info is not None if device_info else False,
                    "device_info": device_info.to_dict() if device_info else None
                })

            return enriched

        except Exception as e:
            logger.error(f"Failed to get configured input devices: {e}")
            raise

    def add_or_update_input_device(self, hw_id: str, custom_name: str = None, enabled: bool = None) -> Dict[str, Any]:
        """
        Add or update input device configuration

        Args:
            hw_id: Hardware ID
            custom_name: Custom stream name (optional)
            enabled: Enable/disable state (optional)

        Returns:
            Dictionary with success status and updated config
        """
        try:
            # Validate device exists
            device = self.device_manager.get_device_by_hw_id(hw_id, is_playback=False)

            if not device:
                return {
                    "success": False,
                    "error": f"Input device {hw_id} not found or unavailable"
                }

            logger.info(f"Configuring input device: {device.friendly_name} ({hw_id})")

            # Get current settings
            settings = self.settings_manager.get_settings()
            audio_settings = settings.get("audio", {})
            input_settings = audio_settings.get("input", {})
            devices = input_settings.get("devices", [])

            # Find existing config or create new one
            existing_config = None
            for config in devices:
                if config.get("hw_id") == hw_id:
                    existing_config = config
                    break

            if existing_config:
                # Update existing
                if custom_name is not None:
                    existing_config["custom_name"] = custom_name
                if enabled is not None:
                    old_enabled = existing_config.get("enabled", False)
                    existing_config["enabled"] = enabled

                    # Trigger stream manager if enabled state changed
                    if old_enabled != enabled:
                        self._trigger_stream_manager()
            else:
                # Add new
                new_config = {
                    "hw_id": hw_id,
                    "custom_name": custom_name or device.friendly_name,
                    "enabled": enabled if enabled is not None else False
                }
                devices.append(new_config)

                # Trigger stream manager if enabled
                if new_config["enabled"]:
                    self._trigger_stream_manager()

            # Save settings
            self.settings_manager.update_settings({
                "audio": {
                    "input": {
                        "devices": devices
                    }
                }
            })

            logger.info(f"Input device configuration saved: {hw_id}")

            return {
                "success": True,
                "message": "Input device configured successfully",
                "device": {
                    "hw_id": hw_id,
                    "custom_name": custom_name or device.friendly_name,
                    "enabled": enabled if enabled is not None else (existing_config.get("enabled", False) if existing_config else False)
                }
            }

        except Exception as e:
            logger.error(f"Failed to configure input device: {e}")
            return {
                "success": False,
                "error": f"Error configuring input device: {str(e)}"
            }

    def remove_input_device(self, hw_id: str) -> Dict[str, Any]:
        """
        Remove input device configuration

        Args:
            hw_id: Hardware ID

        Returns:
            Dictionary with success status
        """
        try:
            logger.info(f"Removing input device configuration: {hw_id}")

            # Get current settings
            settings = self.settings_manager.get_settings()
            audio_settings = settings.get("audio", {})
            input_settings = audio_settings.get("input", {})
            devices = input_settings.get("devices", [])

            # Find and remove device
            was_enabled = False
            devices_filtered = []
            for config in devices:
                if config.get("hw_id") == hw_id:
                    was_enabled = config.get("enabled", False)
                    continue  # Skip this device (remove it)
                devices_filtered.append(config)

            if len(devices) == len(devices_filtered):
                return {
                    "success": False,
                    "error": f"Input device {hw_id} not found in configuration"
                }

            # Save updated settings
            self.settings_manager.update_settings({
                "audio": {
                    "input": {
                        "devices": devices_filtered
                    }
                }
            })

            # Trigger stream manager if device was enabled
            if was_enabled:
                self._trigger_stream_manager()

            logger.info(f"Input device configuration removed: {hw_id}")

            return {
                "success": True,
                "message": "Input device configuration removed"
            }

        except Exception as e:
            logger.error(f"Failed to remove input device: {e}")
            return {
                "success": False,
                "error": f"Error removing input device: {str(e)}"
            }

    def toggle_input_device(self, hw_id: str) -> Dict[str, Any]:
        """
        Toggle input device enabled state

        Args:
            hw_id: Hardware ID

        Returns:
            Dictionary with success status and new state
        """
        try:
            # Get current settings
            settings = self.settings_manager.get_settings()
            audio_settings = settings.get("audio", {})
            input_settings = audio_settings.get("input", {})
            devices = input_settings.get("devices", [])

            # Find device and toggle
            found = False
            new_state = False
            for config in devices:
                if config.get("hw_id") == hw_id:
                    found = True
                    new_state = not config.get("enabled", False)
                    config["enabled"] = new_state
                    break

            if not found:
                return {
                    "success": False,
                    "error": f"Input device {hw_id} not found in configuration"
                }

            # Save settings
            self.settings_manager.update_settings({
                "audio": {
                    "input": {
                        "devices": devices
                    }
                }
            })

            # Trigger stream manager
            self._trigger_stream_manager()

            logger.info(f"Input device {hw_id} toggled to: {new_state}")

            return {
                "success": True,
                "message": f"Input device {'enabled' if new_state else 'disabled'}",
                "enabled": new_state
            }

        except Exception as e:
            logger.error(f"Failed to toggle input device: {e}")
            return {
                "success": False,
                "error": f"Error toggling input device: {str(e)}"
            }

    def _trigger_stream_manager(self):
        """Trigger the input stream manager to update Snapcast streams"""
        try:
            logger.info("Triggering input stream manager...")
            # Run the stream manager script
            result = subprocess.run(
                ["python3", "/app/scripts/manage_input_streams.py"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"Stream manager executed successfully: {result.stdout}")
            else:
                logger.error(f"Stream manager failed: {result.stderr}")

        except Exception as e:
            logger.error(f"Failed to trigger stream manager: {e}")


def create_audio_blueprint(audio_controller: AudioConfigController = None) -> Blueprint:
    """Create Flask blueprint for audio configuration API"""

    if audio_controller is None:
        audio_controller = AudioConfigController()

    # Initialize MPRIS volume controller
    mpris_controller = MPRISVolumeController()

    bp = Blueprint('audio', __name__)

    @bp.route("/api/audio/devices/output", methods=["GET"])
    def get_output_devices():
        """Get all available output devices"""
        try:
            devices = audio_controller.get_output_devices()
            return jsonify(devices)
        except Exception as e:
            logger.error(f"Get output devices failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/audio/devices/input", methods=["GET"])
    def get_input_devices():
        """Get all available input devices"""
        try:
            devices = audio_controller.get_input_devices()
            return jsonify(devices)
        except Exception as e:
            logger.error(f"Get input devices failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/audio/output/current", methods=["GET"])
    def get_current_output():
        """Get currently configured output device"""
        try:
            device = audio_controller.get_current_output_device()
            return jsonify(device)
        except Exception as e:
            logger.error(f"Get current output failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/audio/output/device", methods=["POST"])
    def set_output_device():
        """Set output device"""
        try:
            data = request.get_json()

            if not data or "hw_id" not in data:
                return jsonify({"success": False, "error": "hw_id is required"}), 400

            hw_id = data["hw_id"]
            result = audio_controller.set_output_device(hw_id)

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Set output device failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/audio/output/test", methods=["POST"])
    def test_output_device():
        """Test an output device"""
        try:
            data = request.get_json()

            if not data or "hw_id" not in data:
                return jsonify({"success": False, "message": "hw_id is required"}), 400

            hw_id = data["hw_id"]
            result = audio_controller.test_output_device(hw_id)

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Test output device failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/audio/input/devices", methods=["GET"])
    def get_configured_input_devices():
        """Get configured input devices from settings"""
        try:
            devices = audio_controller.get_configured_input_devices()
            return jsonify(devices)
        except Exception as e:
            logger.error(f"Get configured input devices failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/audio/input/device", methods=["POST"])
    def add_or_update_input_device():
        """Add or update input device configuration"""
        try:
            data = request.get_json()

            if not data or "hw_id" not in data:
                return jsonify({"success": False, "error": "hw_id is required"}), 400

            hw_id = data["hw_id"]
            custom_name = data.get("custom_name")
            enabled = data.get("enabled")

            result = audio_controller.add_or_update_input_device(hw_id, custom_name, enabled)

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Add/update input device failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/audio/input/device/<path:hw_id>", methods=["DELETE"])
    def remove_input_device(hw_id: str):
        """Remove input device configuration"""
        try:
            # URL decode hw_id (handles : and , characters)
            import urllib.parse
            hw_id = urllib.parse.unquote(hw_id)

            result = audio_controller.remove_input_device(hw_id)

            status_code = 200 if result["success"] else 404
            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Remove input device failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/audio/input/device/<path:hw_id>/toggle", methods=["POST"])
    def toggle_input_device(hw_id: str):
        """Toggle input device enabled state"""
        try:
            # URL decode hw_id (handles : and , characters)
            import urllib.parse
            hw_id = urllib.parse.unquote(hw_id)

            result = audio_controller.toggle_input_device(hw_id)

            status_code = 200 if result["success"] else 404
            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Toggle input device failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/audio/source-volume", methods=["POST"])
    def set_source_volume():
        """
        Set source volume for a stream (controls AirPlay/Spotify/Bluetooth/etc volume via D-Bus MPRIS)
        This endpoint is always available regardless of federation status
        """
        try:
            data = request.get_json()
            stream_id = data.get("streamId")
            volume = data.get("volume")

            logger.info(f"Source volume request - streamId: '{stream_id}', volume: {volume}")

            if not stream_id or volume is None:
                return jsonify({"error": "streamId and volume required"}), 400

            # The streamId might be a friendly name from the frontend, but we need the actual stream ID
            # Try to extract the actual stream ID from the Snapcast API
            # For now, let's accept it and let the MPRIS controller handle it

            # Use direct D-Bus MPRIS control
            success, message = mpris_controller.set_volume(stream_id, int(volume))

            if success:
                return jsonify({"success": True, "message": message})
            else:
                logger.warning(f"Failed to set volume for '{stream_id}': {message}")
                return jsonify({"success": False, "message": message}), 400

        except Exception as e:
            logger.error(f"Set source volume failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/audio/source-volume", methods=["GET"])
    def get_source_volume():
        """
        Get source volume for a stream via D-Bus MPRIS
        Query parameter: streamId
        """
        try:
            stream_id = request.args.get("streamId")

            if not stream_id:
                return jsonify({"error": "streamId parameter required"}), 400

            # Get volume via D-Bus MPRIS
            success, volume, message = mpris_controller.get_volume(stream_id)

            if success:
                return jsonify({"success": True, "volume": volume, "message": message})
            else:
                return jsonify({"success": False, "volume": 0, "message": message}), 400

        except Exception as e:
            logger.error(f"Get source volume failed: {e}")
            return jsonify({"error": str(e)}), 500

    return bp


# For standalone testing
if __name__ == "__main__":
    from flask import Flask
    from flask_cors import CORS

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    app = Flask(__name__)
    CORS(app)

    controller = AudioConfigController()
    bp = create_audio_blueprint(controller)
    app.register_blueprint(bp)

    print("Audio API running on http://localhost:5004")
    app.run(host="0.0.0.0", port=5004, debug=True)
