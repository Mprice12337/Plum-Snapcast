#!/usr/bin/env python3
"""
Audio Configuration API
Provides endpoints for audio device discovery and configuration
"""

import json
import logging
import os
import subprocess
import sys
import time
from typing import Dict, Any, List
from flask import Blueprint, jsonify, request

# Import AudioDeviceManager and SettingsManager
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_devices import AudioDeviceManager, DeviceType
from settings_api import SettingsManager

logger = logging.getLogger(__name__)

# Configuration
SUPERVISORCTL_CONF = "/app/supervisord/supervisord.conf"


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


def create_audio_blueprint(audio_controller: AudioConfigController = None) -> Blueprint:
    """Create Flask blueprint for audio configuration API"""

    if audio_controller is None:
        audio_controller = AudioConfigController()

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
