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

    # AirPlay settings (multi-endpoint support)
    airplay = integrations.get('airplay', {})

    # Handle both old (single endpoint) and new (multi-endpoint) formats
    if 'endpoints' in airplay:
        # New format: array of endpoints
        endpoints = airplay['endpoints']
    elif 'deviceName' in airplay or 'enabled' in airplay:
        # Old format: single endpoint - convert to array
        endpoints = [{
            "id": "1",
            "enabled": airplay.get('enabled', True),
            "deviceName": airplay.get('deviceName', 'Plum Audio'),
            "port": 5050,
            "udpPortBase": 6001
        }]
    else:
        # No AirPlay config - create default single endpoint
        endpoints = [{
            "id": "1",
            "enabled": True,
            "deviceName": "Plum Audio",
            "port": 5050,
            "udpPortBase": 6001
        }]

    # Export endpoints as JSON string (will be parsed by setup script)
    print(f"export AIRPLAY_ENDPOINTS_JSON='{json.dumps(endpoints)}'")

    # Legacy env vars for backward compatibility (uses first endpoint)
    first_endpoint = endpoints[0] if endpoints else {"enabled": True, "deviceName": "Plum Audio"}
    print(f"export AIRPLAY_CONFIG_ENABLED={bool_to_env(first_endpoint.get('enabled', True))}")
    print(f"export AIRPLAY_SOURCE_NAME=\"AirPlay\"")
    print(f"export AIRPLAY_DEVICE_NAME=\"{first_endpoint.get('deviceName', 'Plum Audio')}\"")

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

    # Plexamp settings (only enable if both available AND enabled)
    plexamp = integrations.get('plexamp', {})
    plexamp_available = plexamp.get('available', False)
    plexamp_enabled = plexamp.get('enabled', False)
    print(f"export PLEXAMP_CONFIG_ENABLED={bool_to_env(plexamp_available and plexamp_enabled)}")
    print(f"export PLEXAMP_SOURCE_NAME=\"{plexamp.get('sourceName', 'Plexamp')}\"")

    # Federation settings (global server settings, not browser-local)
    federation = settings.get('federation', {})
    print(f"export FEDERATION_ENABLED={bool_to_env(federation.get('enabled', False))}")
    print(f"export FEDERATION_AUTO_DISCOVER={bool_to_env(federation.get('autoDiscover', True))}")

    # Device settings (used for federation local server name)
    device_name = settings.get('deviceName', 'Plum Snapcast')
    print(f"export DEVICE_NAME=\"{device_name}\"")

    # Audio settings
    audio = settings.get('audio', {})
    audio_output = audio.get('output', {})
    print(f"export AUDIO_OUTPUT_DEVICE=\"{audio_output.get('device', 'hw:Headphones')}\"")

    # Note: Snapclient, network, and other infrastructure settings remain in environment variables
    # Plexamp availability is determined by PLEXAMP_ENABLED env var (checked in migrate script)

if __name__ == "__main__":
    main()
