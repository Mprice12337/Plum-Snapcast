#!/usr/bin/env python3
"""
Settings Loader
Loads settings from settings.json and outputs as environment variables
Used during container startup to configure services
"""

import json
import os
import sys

SETTINGS_FILE = "/app/data/settings.json"

def load_settings_from_file():
    """Load settings directly from JSON file"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load settings from file: {e}", file=sys.stderr)
    return None

def get_value(settings, path, default=""):
    """Get nested value from settings dict using dot notation"""
    keys = path.split('.')
    value = settings
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value

def bool_to_env(value):
    """Convert boolean to 0/1 for environment variable"""
    return "1" if value else "0"

def main():
    # Load settings from file
    settings = load_settings_from_file()

    if not settings:
        print("Error: Could not load settings", file=sys.stderr)
        sys.exit(1)

    # Extract integration settings
    integrations = settings.get('integrations', {})

    # AirPlay settings
    airplay = integrations.get('airplay', {})
    print(f"export AIRPLAY_CONFIG_ENABLED={bool_to_env(airplay.get('enabled', True))}")
    print(f"export AIRPLAY_SOURCE_NAME=\"AirPlay\"")
    print(f"export AIRPLAY_DEVICE_NAME=\"{airplay.get('deviceName', 'Plum Audio')}\"")

    # Bluetooth settings
    bluetooth = integrations.get('bluetooth', {})
    print(f"export BLUETOOTH_ENABLED={bool_to_env(bluetooth.get('enabled', False))}")
    print(f"export BLUETOOTH_SOURCE_NAME=\"Bluetooth\"")
    print(f"export BLUETOOTH_DEVICE_NAME=\"{bluetooth.get('deviceName', 'Plum Audio')}\"")
    print(f"export BLUETOOTH_ADAPTER=\"{bluetooth.get('adapter', 'hci0')}\"")
    print(f"export BLUETOOTH_AUTO_PAIR={bool_to_env(bluetooth.get('autoPair', True))}")
    print(f"export BLUETOOTH_DISCOVERABLE={bool_to_env(bluetooth.get('discoverable', True))}")

    # Spotify settings
    spotify = integrations.get('spotify', {})
    print(f"export SPOTIFY_CONFIG_ENABLED={bool_to_env(spotify.get('enabled', False))}")
    print(f"export SPOTIFY_SOURCE_NAME=\"{spotify.get('sourceName', 'Spotify')}\"")
    print(f"export SPOTIFY_DEVICE_NAME=\"{spotify.get('deviceName', 'Plum Audio')}\"")
    print(f"export SPOTIFY_BITRATE={spotify.get('bitrate', 320)}")

    # DLNA settings
    dlna = integrations.get('dlna', {})
    print(f"export DLNA_ENABLED={bool_to_env(dlna.get('enabled', False))}")
    print(f"export DLNA_SOURCE_NAME=\"{dlna.get('sourceName', 'DLNA')}\"")
    print(f"export DLNA_DEVICE_NAME=\"{dlna.get('deviceName', 'Plum Audio')}\"")

    # Federation settings (global server settings, not browser-local)
    federation = settings.get('federation', {})
    print(f"export FEDERATION_ENABLED={bool_to_env(federation.get('enabled', False))}")
    print(f"export FEDERATION_AUTO_DISCOVER={bool_to_env(federation.get('autoDiscover', True))}")

    # Device settings (used for federation local server name)
    device_name = settings.get('deviceName', 'Plum Snapcast')
    print(f"export DEVICE_NAME=\"{device_name}\"")

    # Note: Plexamp settings remain in environment variables as per architecture decision
    # Snapclient, network, and other settings also remain in environment variables

if __name__ == "__main__":
    main()
