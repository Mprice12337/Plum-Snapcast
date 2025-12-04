#!/usr/bin/env python3
"""
Settings API
Provides GET/POST endpoints for server-side settings storage
Settings are stored in /app/data/settings.json
"""

import json
import logging
import os
from typing import Dict, Any
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# Default settings structure
DEFAULT_SETTINGS = {
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
        "snapcast": True,
        "visualizer": False
    },
    "federation": {
        "enabled": False,
        "autoDiscover": True,
        "localServerName": "Snapcast Server"
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
            if key in current and isinstance(current[key], dict) and isinstance(new_settings[key], dict):
                current[key].update(new_settings[key])
            else:
                current[key] = new_settings[key]

        self._save_settings(current)
        return current


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
