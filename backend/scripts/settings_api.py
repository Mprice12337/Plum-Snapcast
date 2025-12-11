#!/usr/bin/env python3
"""
Settings API
Provides GET/POST endpoints for server-side settings storage
Settings are stored in /app/data/settings.json
"""

import json
import logging
import os
import re
import subprocess
from typing import Dict, Any
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# Default settings structure
DEFAULT_SETTINGS = {
    "version": 1,  # Increments on every update for change detection
    "deviceName": "Plum Snapcast",
    "hostname": "plum-snapcast",
    "integrations": {
        "airplay": {
            "enabled": True,
            "deviceName": "Plum Audio"
        },
        "bluetooth": {
            "enabled": False,
            "deviceName": "Plum Audio",
            "adapter": "hci0",
            "autoPair": True,
            "discoverable": True
        },
        "spotify": {
            "enabled": False,
            "sourceName": "Spotify",
            "deviceName": "Plum Audio",
            "bitrate": 320
        },
        "dlna": {
            "enabled": False,
            "sourceName": "DLNA",
            "deviceName": "Plum Audio"
        },
        "plexamp": {
            "available": False,  # Determined by PLEXAMP_ENABLED env var
            "enabled": False,    # User toggle (only when available)
            "sourceName": "Plexamp"
        },
        "snapcast": True,
        "visualizer": False
    },
    "federation": {
        "enabled": False,
        "autoDiscover": True
        # localServerName removed - now uses deviceName
    }
}

SETTINGS_FILE = "/app/data/settings.json"


class SettingsManager:
    """Manages server-side settings persistence"""

    def __init__(self, settings_file: str = SETTINGS_FILE):
        self.settings_file = settings_file
        self._ensure_settings_file()

    def _ensure_settings_file(self):
        """Ensure settings file exists with default values"""
        if not os.path.exists(self.settings_file):
            logger.info(f"Creating settings file at {self.settings_file}")
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            self._save_settings(DEFAULT_SETTINGS)

    def _save_settings(self, settings: Dict[str, Any]):
        """Save settings to JSON file"""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            logger.info("Settings saved successfully")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            raise

    def get_settings(self) -> Dict[str, Any]:
        """Load settings from JSON file"""
        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)

            # Merge with defaults to ensure all keys exist
            merged = DEFAULT_SETTINGS.copy()
            for key in merged:
                if key in settings:
                    if isinstance(merged[key], dict):
                        merged[key].update(settings[key])
                    else:
                        merged[key] = settings[key]

            return merged
        except FileNotFoundError:
            logger.warning("Settings file not found, using defaults")
            return DEFAULT_SETTINGS.copy()
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            return DEFAULT_SETTINGS.copy()

    def update_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update settings (partial or full update)"""
        current = self.get_settings()

        # Deep merge new settings into current
        for key in new_settings:
            if key == 'version':
                continue  # Don't allow manual version updates
            if key in current and isinstance(current[key], dict) and isinstance(new_settings[key], dict):
                current[key].update(new_settings[key])
            else:
                current[key] = new_settings[key]

        # Increment version for change detection
        current['version'] = current.get('version', 0) + 1
        logger.info(f"Settings updated to version {current['version']}")

        self._save_settings(current)
        return current

    @staticmethod
    def validate_hostname(hostname: str) -> tuple[bool, str]:
        """
        Validate hostname according to DNS rules
        Returns: (is_valid, error_message)
        """
        if not hostname:
            return False, "Hostname cannot be empty"

        if len(hostname) > 63:
            return False, "Hostname must be 63 characters or less"

        # Must be lowercase alphanumeric + hyphens
        if not re.match(r'^[a-z0-9-]+$', hostname):
            return False, "Hostname must contain only lowercase letters, numbers, and hyphens"

        # Cannot start or end with hyphen
        if hostname.startswith('-') or hostname.endswith('-'):
            return False, "Hostname cannot start or end with a hyphen"

        return True, ""

    @staticmethod
    def sanitize_hostname(device_name: str) -> str:
        """Convert device name to valid hostname"""
        hostname = device_name.lower()
        hostname = ''.join(c if c.isalnum() or c == '-' else '-' for c in hostname)
        hostname = hostname.strip('-')
        hostname = hostname[:63]
        return hostname if hostname else "plum-snapcast"

    @staticmethod
    def update_avahi_hostname(hostname: str) -> tuple[bool, str]:
        """
        Update Avahi configuration with new hostname and restart service
        Returns: (success, message)
        """
        try:
            avahi_conf = "/etc/avahi/avahi-daemon.conf"

            # Read current config
            with open(avahi_conf, 'r') as f:
                lines = f.readlines()

            # Update or add host-name line in [server] section
            in_server_section = False
            hostname_updated = False
            new_lines = []

            for line in lines:
                if line.strip() == '[server]':
                    in_server_section = True
                    new_lines.append(line)
                elif line.strip().startswith('[') and in_server_section:
                    # Entering new section, add hostname if not yet added
                    if not hostname_updated:
                        new_lines.append(f'host-name={hostname}\n')
                        hostname_updated = True
                    in_server_section = False
                    new_lines.append(line)
                elif in_server_section and line.strip().startswith('host-name='):
                    # Replace existing hostname
                    new_lines.append(f'host-name={hostname}\n')
                    hostname_updated = True
                else:
                    new_lines.append(line)

            # If we never found host-name and still in server section, add it
            if in_server_section and not hostname_updated:
                new_lines.append(f'host-name={hostname}\n')

            # Write updated config
            with open(avahi_conf, 'w') as f:
                f.writelines(new_lines)

            logger.info(f"Updated Avahi hostname to: {hostname}")

            # Restart Avahi to apply new hostname (SIGHUP only reloads services, not hostname)
            result = subprocess.run(
                ['supervisorctl', '-c', '/app/supervisord/supervisord.conf', 'restart', 'avahi'],
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                logger.info("Avahi service restarted successfully")
                return True, f"Hostname updated to '{hostname}.local' and mDNS restarted"
            else:
                logger.error(f"Failed to restart Avahi: {result.stderr}")
                return False, f"Hostname updated but mDNS restart failed: {result.stderr}"

        except Exception as e:
            logger.error(f"Failed to update Avahi hostname: {e}")
            return False, f"Failed to update hostname: {str(e)}"


def create_settings_blueprint(settings_manager: SettingsManager = None) -> Blueprint:
    """Create Flask blueprint for settings API"""
    if settings_manager is None:
        settings_manager = SettingsManager()

    bp = Blueprint('settings', __name__)

    @bp.route("/api/settings", methods=["GET"])
    def get_settings():
        """Get current server settings"""
        try:
            settings = settings_manager.get_settings()
            return jsonify(settings)
        except Exception as e:
            logger.error(f"Get settings failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/settings", methods=["POST"])
    def update_settings():
        """Update server settings (partial or full update)"""
        try:
            new_settings = request.get_json()

            if not new_settings:
                return jsonify({"error": "No settings provided"}), 400

            updated = settings_manager.update_settings(new_settings)
            return jsonify(updated)
        except Exception as e:
            logger.error(f"Update settings failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/settings/device", methods=["POST"])
    def update_device_settings():
        """Update device name and/or hostname"""
        try:
            data = request.get_json()

            if not data:
                return jsonify({"error": "No data provided"}), 400

            device_name = data.get("deviceName")
            hostname = data.get("hostname")

            if not device_name and not hostname:
                return jsonify({"error": "Either deviceName or hostname must be provided"}), 400

            current = settings_manager.get_settings()
            updates = {}
            messages = []

            # Update device name
            if device_name:
                if not device_name.strip():
                    return jsonify({"error": "Device name cannot be empty"}), 400
                if len(device_name) > 100:
                    return jsonify({"error": "Device name must be 100 characters or less"}), 400

                updates["deviceName"] = device_name.strip()
                messages.append(f"Device name updated to '{device_name}'")
                logger.info(f"Device name updated to: {device_name}")

            # Update hostname
            if hostname:
                # Validate hostname
                is_valid, error_msg = SettingsManager.validate_hostname(hostname)
                if not is_valid:
                    return jsonify({"error": error_msg}), 400

                updates["hostname"] = hostname

                # Update Avahi configuration and restart service
                success, avahi_msg = SettingsManager.update_avahi_hostname(hostname)
                if success:
                    messages.append(avahi_msg)
                else:
                    logger.warning(f"Avahi update failed: {avahi_msg}")
                    messages.append(f"Warning: {avahi_msg}")

            # Save settings
            updated = settings_manager.update_settings(updates)

            return jsonify({
                "success": True,
                "message": "; ".join(messages),
                "settings": updated
            })

        except Exception as e:
            logger.error(f"Update device settings failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/settings/device/hostname/validate", methods=["POST"])
    def validate_hostname():
        """Validate a hostname"""
        try:
            data = request.get_json()
            hostname = data.get("hostname", "")

            is_valid, error_msg = SettingsManager.validate_hostname(hostname)

            return jsonify({
                "valid": is_valid,
                "error": error_msg if not is_valid else None
            })

        except Exception as e:
            logger.error(f"Hostname validation failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/settings/device/hostname/sanitize", methods=["POST"])
    def sanitize_hostname():
        """Sanitize device name to valid hostname"""
        try:
            data = request.get_json()
            device_name = data.get("deviceName", "")

            sanitized = SettingsManager.sanitize_hostname(device_name)

            return jsonify({
                "hostname": sanitized
            })

        except Exception as e:
            logger.error(f"Hostname sanitization failed: {e}")
            return jsonify({"error": str(e)}), 500

    return bp


# For standalone testing
if __name__ == "__main__":
    from flask import Flask
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)

    manager = SettingsManager()
    bp = create_settings_blueprint(manager)
    app.register_blueprint(bp)

    print("Settings API running on http://localhost:5002")
    app.run(host="0.0.0.0", port=5002, debug=True)
