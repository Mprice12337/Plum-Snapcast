#!/usr/bin/env python3
"""
Integrations Actions API
Provides endpoints for controlling integration services (start/stop, config updates)
"""

import json
import logging
import os
import re
import subprocess
import sys
from typing import Dict, Any
from flask import Blueprint, jsonify, request

# Import SettingsManager to persist state changes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settings_api import SettingsManager

logger = logging.getLogger(__name__)

# Configuration file paths
SHAIRPORT_SYNC_CONF = "/app/config/shairport-sync.conf"
SUPERVISORCTL_CONF = "/app/supervisord/supervisord.conf"


class IntegrationController:
    """Controls integration services via supervisorctl"""

    def __init__(self):
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

    def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Get status of a supervisord service"""
        success, output = self._run_supervisorctl("status", service_name)

        if not success:
            return {"running": False, "status": "unknown", "error": output}

        # Parse supervisorctl status output
        # Format: "service_name    RUNNING   pid 123, uptime 1:23:45"
        parts = output.split()
        if len(parts) >= 2:
            status = parts[1]
            return {
                "running": status == "RUNNING",
                "status": status.lower(),
                "raw_output": output.strip()
            }

        return {"running": False, "status": "unknown", "raw_output": output}

    def start_service(self, service_name: str) -> tuple[bool, str]:
        """Start a supervisord service"""
        return self._run_supervisorctl("start", service_name)

    def stop_service(self, service_name: str) -> tuple[bool, str]:
        """Stop a supervisord service"""
        return self._run_supervisorctl("stop", service_name)

    def restart_service(self, service_name: str) -> tuple[bool, str]:
        """Restart a supervisord service"""
        return self._run_supervisorctl("restart", service_name)


class AirPlayController:
    """Controls AirPlay (shairport-sync) service"""

    def __init__(self, integration_controller: IntegrationController, settings_manager: SettingsManager = None):
        self.controller = integration_controller
        self.service_name = "shairport-sync"
        self.config_file = SHAIRPORT_SYNC_CONF
        self.settings_manager = settings_manager or SettingsManager()

    def enable(self) -> Dict[str, Any]:
        """Enable AirPlay service"""
        success, output = self.controller.start_service(self.service_name)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "airplay": {
                            "enabled": True
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist AirPlay enabled state: {e}")

        return {
            "success": success,
            "message": "AirPlay enabled" if success else "Failed to enable AirPlay",
            "details": output.strip()
        }

    def disable(self) -> Dict[str, Any]:
        """Disable AirPlay service"""
        success, output = self.controller.stop_service(self.service_name)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "airplay": {
                            "enabled": False
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist AirPlay disabled state: {e}")

        return {
            "success": success,
            "message": "AirPlay disabled" if success else "Failed to disable AirPlay",
            "details": output.strip()
        }

    def get_status(self) -> Dict[str, Any]:
        """Get AirPlay service status"""
        return self.controller.get_service_status(self.service_name)

    def update_device_name(self, device_name: str) -> Dict[str, Any]:
        """Update AirPlay device name in config and restart service"""
        try:
            # Validate device name
            if not device_name or len(device_name) > 50:
                return {
                    "success": False,
                    "message": "Invalid device name (must be 1-50 characters)"
                }

            # Escape special characters for sed
            device_name_escaped = device_name.replace('"', '\\"').replace('/', '\\/')

            # Use sed to update config (same approach as setup.sh)
            sed_pattern = f'/^general = {{/,/^}}/{{s/name = ".*";/name = "{device_name_escaped}";/}}'
            sed_cmd = ["sed", "-i", sed_pattern, self.config_file]

            result = subprocess.run(sed_cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                logger.error(f"sed command failed: {result.stderr}")
                return {
                    "success": False,
                    "message": "Failed to update config file",
                    "details": result.stderr.strip()
                }

            logger.info(f"Updated AirPlay device name to: {device_name}")

            # Restart service to apply changes
            success, output = self.controller.restart_service(self.service_name)

            if not success:
                logger.error(f"Failed to restart shairport-sync: {output}")

            # Update settings to persist device name and enabled state
            # Note: restarting the service enables it, so we set enabled=True
            if success:
                try:
                    self.settings_manager.update_settings({
                        "integrations": {
                            "airplay": {
                                "deviceName": device_name,
                                "enabled": True
                            }
                        }
                    })
                except Exception as e:
                    logger.error(f"Failed to persist AirPlay device name: {e}")

            return {
                "success": success,
                "message": f"Device name updated to '{device_name}'" if success else "Failed to restart AirPlay service",
                "device_name": device_name if success else None,
                "details": output.strip()
            }

        except Exception as e:
            logger.error(f"Failed to update device name: {e}")
            return {
                "success": False,
                "message": f"Error updating device name: {str(e)}"
            }


def create_integrations_blueprint(
    integration_controller: IntegrationController = None
) -> Blueprint:
    """Create Flask blueprint for integrations actions API"""

    if integration_controller is None:
        integration_controller = IntegrationController()

    airplay_controller = AirPlayController(integration_controller)

    bp = Blueprint('integrations', __name__)

    @bp.route("/api/integrations/airplay/enable", methods=["POST"])
    def airplay_enable():
        """Enable AirPlay service"""
        try:
            result = airplay_controller.enable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"AirPlay enable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/airplay/disable", methods=["POST"])
    def airplay_disable():
        """Disable AirPlay service"""
        try:
            result = airplay_controller.disable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"AirPlay disable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/airplay/status", methods=["GET"])
    def airplay_status():
        """Get AirPlay service status"""
        try:
            result = airplay_controller.get_status()
            return jsonify(result)
        except Exception as e:
            logger.error(f"AirPlay status check failed: {e}")
            return jsonify({"running": False, "status": "error", "error": str(e)}), 500

    @bp.route("/api/integrations/airplay/device-name", methods=["POST"])
    def airplay_update_device_name():
        """Update AirPlay device name"""
        try:
            data = request.get_json()
            if not data or "deviceName" not in data:
                return jsonify({"success": False, "message": "deviceName is required"}), 400

            device_name = data["deviceName"]
            result = airplay_controller.update_device_name(device_name)

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"AirPlay device name update failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    return bp


# For standalone testing
if __name__ == "__main__":
    from flask import Flask
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)

    controller = IntegrationController()
    bp = create_integrations_blueprint(controller)
    app.register_blueprint(bp)

    print("Integrations API running on http://localhost:5003")
    app.run(host="0.0.0.0", port=5003, debug=True)
