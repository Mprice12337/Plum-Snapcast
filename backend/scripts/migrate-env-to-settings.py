#!/usr/bin/env python3
"""
Migration Script: Environment Variables to Settings File
Reads integration configuration from environment variables and migrates to settings.json
Run this once during upgrade to convert from env-based config to settings-based config
"""

import json
import os
import sys

SETTINGS_FILE = "/app/data/settings.json"

def bool_from_env(value, default=False):
    """Convert environment variable string to boolean"""
    if value is None:
        return default
    return value.strip() in ("1", "true", "True", "TRUE", "yes", "Yes", "YES")

def main():
    print("=" * 60)
    print("Environment Variables → Settings Migration")
    print("=" * 60)

    # Load existing settings if they exist
    existing_settings = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                existing_settings = json.load(f)
            print(f"\n✓ Loaded existing settings from {SETTINGS_FILE}")
        except Exception as e:
            print(f"\n✗ Warning: Could not load existing settings: {e}")
            print("  Starting with default settings...")
    else:
        print(f"\n• No existing settings file found at {SETTINGS_FILE}")
        print("  Creating new settings from environment variables...")

    # Helper to sanitize hostname from device name
    def sanitize_hostname(device_name):
        """Convert device name to valid hostname (lowercase, alphanumeric + hyphens)"""
        hostname = device_name.lower()
        hostname = ''.join(c if c.isalnum() or c == '-' else '-' for c in hostname)
        hostname = hostname.strip('-')
        hostname = hostname[:63]  # DNS label max length
        return hostname if hostname else "plum-snapcast"

    # Build settings from environment variables
    default_device_name = "Plum Snapcast"

    # Handle AirPlay endpoint migration
    # If existing settings has old format (single endpoint), migrate to new format (array of endpoints)
    existing_airplay = existing_settings.get("integrations", {}).get("airplay", {})
    if "endpoints" in existing_airplay:
        # Already using new multi-endpoint format
        airplay_config = existing_airplay
    elif "deviceName" in existing_airplay or "enabled" in existing_airplay:
        # Old single-endpoint format - migrate to array
        airplay_config = {
            "endpoints": [
                {
                    "id": "1",
                    "enabled": existing_airplay.get("enabled", bool_from_env(os.getenv("AIRPLAY_CONFIG_ENABLED"), True)),
                    "deviceName": existing_airplay.get("deviceName", os.getenv("AIRPLAY_DEVICE_NAME", "Plum Audio")),
                    "port": 5050,
                    "udpPortBase": 6001
                }
            ]
        }
    else:
        # No existing AirPlay config - create default single endpoint
        airplay_config = {
            "endpoints": [
                {
                    "id": "1",
                    "enabled": bool_from_env(os.getenv("AIRPLAY_CONFIG_ENABLED"), True),
                    "deviceName": os.getenv("AIRPLAY_DEVICE_NAME", "Plum Audio"),
                    "port": 5050,
                    "udpPortBase": 6001
                }
            ]
        }

    # Handle Spotify endpoint migration
    # If existing settings has old format (single endpoint), migrate to new format (array of endpoints)
    existing_spotify = existing_settings.get("integrations", {}).get("spotify", {})
    if "endpoints" in existing_spotify:
        # Already using new multi-endpoint format
        spotify_config = existing_spotify
    elif "deviceName" in existing_spotify or "enabled" in existing_spotify:
        # Old single-endpoint format - migrate to array
        # Preserve bitrate at integration level (shared setting)
        # CRITICAL: Preserve enabled state from existing config
        spotify_config = {
            "bitrate": existing_spotify.get("bitrate", int(os.getenv("SPOTIFY_BITRATE", "320"))),
            "endpoints": [
                {
                    "id": "1",
                    "enabled": existing_spotify.get("enabled", bool_from_env(os.getenv("SPOTIFY_CONFIG_ENABLED"), False)),
                    "deviceName": existing_spotify.get("deviceName", os.getenv("SPOTIFY_DEVICE_NAME", "Plum Audio")),
                    "zeroconfPort": 5354
                }
            ]
        }
    else:
        # No existing Spotify config - create default (disabled by default)
        spotify_config = {
            "bitrate": int(os.getenv("SPOTIFY_BITRATE", "320")),
            "endpoints": []  # Start with no endpoints
        }

    # Handle DLNA/UPnP endpoint migration
    # If existing settings has old format (single endpoint), migrate to new format (array of endpoints)
    import uuid as uuid_lib
    existing_dlna = existing_settings.get("integrations", {}).get("dlna", {})
    if "endpoints" in existing_dlna:
        # Already using new multi-endpoint format
        dlna_config = existing_dlna
    elif "deviceName" in existing_dlna or "enabled" in existing_dlna:
        # Old single-endpoint format - migrate to array
        # CRITICAL: Preserve enabled state from existing config
        dlna_config = {
            "endpoints": [
                {
                    "id": "1",
                    "enabled": existing_dlna.get("enabled", bool_from_env(os.getenv("DLNA_ENABLED"), False)),
                    "deviceName": existing_dlna.get("deviceName", os.getenv("DLNA_DEVICE_NAME", "Plum Audio")),
                    "port": 49494,
                    "uuid": existing_dlna.get("uuid", str(uuid_lib.uuid4()))
                }
            ]
        }
    else:
        # No existing DLNA config - create default (disabled by default)
        dlna_config = {
            "endpoints": []  # Start with no endpoints
        }

    settings = {
        "deviceName": existing_settings.get("deviceName", default_device_name),
        "hostname": existing_settings.get("hostname", sanitize_hostname(default_device_name)),
        "integrations": {
            "airplay": airplay_config,
            "bluetooth": {
                "enabled": bool_from_env(os.getenv("BLUETOOTH_ENABLED"), False),
                "deviceName": os.getenv("BLUETOOTH_DEVICE_NAME", "Plum Audio"),
                "adapter": os.getenv("BLUETOOTH_ADAPTER", "hci0"),
                "autoPair": bool_from_env(os.getenv("BLUETOOTH_AUTO_PAIR"), True),
                "discoverable": bool_from_env(os.getenv("BLUETOOTH_DISCOVERABLE"), True)
            },
            "spotify": spotify_config,
            "dlna": dlna_config,
            "plexamp": {
                # Check if Plexamp is available (configured in docker-compose)
                "available": bool_from_env(os.getenv("PLEXAMP_ENABLED"), False),
                # If available, default to enabled; otherwise disabled
                "enabled": bool_from_env(os.getenv("PLEXAMP_ENABLED"), False),
                "sourceName": os.getenv("PLEXAMP_SOURCE_NAME", "Plexamp")
            },
            "snapcast": existing_settings.get("integrations", {}).get("snapcast", True),
            "visualizer": existing_settings.get("integrations", {}).get("visualizer", {
                "enabled": True,
                "theme": "user",
                "type": "circular",
                "barCount": 128,
                "sensitivity": 50,
                "smoothing": 70,
                "smoothingType": "catmull-rom",
                "frequencyScale": "logarithmic-smooth",
                "idleState": "circle",
                "symmetry": 1,
                "mirror": False,
                "invert": False,
                "taper": True,
                "mixedFlip": False,
                "rotate": False,
                "rotationSpeed": 30,
                "rotationDirection": "clockwise",
                "cycleEnabled": False,
                "cyclePresetIds": [],
                "advanced": {
                    "bassAnalysis": False,
                    "particles": False
                }
            })
        },
        "federation": {
            "enabled": bool_from_env(os.getenv("FEDERATION_ENABLED"), False),
            "autoDiscover": bool_from_env(os.getenv("FEDERATION_AUTO_DISCOVER"), True)
            # localServerName removed - now uses deviceName
        },
        "audio": {
            "output": {
                # Migrate SNAPCLIENT_SOUNDCARD to audio.output.device
                "device": os.getenv("SNAPCLIENT_SOUNDCARD", "hw:Headphones"),
                "device_type": "BUILTIN_HEADPHONES",  # Will be updated when device is selected via GUI
                "fallback_device": "hw:Headphones"
            },
            "input": {
                "devices": []  # Future: user-enabled input devices
            }
        }
    }

    # Create backup of existing settings if they exist
    if os.path.exists(SETTINGS_FILE):
        backup_file = f"{SETTINGS_FILE}.backup"
        try:
            with open(backup_file, 'w') as f:
                json.dump(existing_settings, f, indent=2)
            print(f"\n✓ Created backup at {backup_file}")
        except Exception as e:
            print(f"\n✗ Warning: Could not create backup: {e}")

    # Write new settings
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)

        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)

        # Set ownership to snapcast user (UID 1000, GID 1000)
        try:
            os.chown(SETTINGS_FILE, 1000, 1000)
            os.chmod(SETTINGS_FILE, 0o644)
        except Exception as e:
            print(f"\n✗ Warning: Could not set file ownership: {e}")

        print(f"\n✓ Successfully wrote settings to {SETTINGS_FILE}")
        print("\nMigrated settings:")
        print(json.dumps(settings, indent=2))
        print("\n" + "=" * 60)
        print("Migration Complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Review the settings in the web UI (Settings → Integrations)")
        print("2. Adjust device names and preferences as needed")
        print("3. Restart container to apply changes")
        print("\nNote: You can now remove integration-related environment")
        print("      variables from your .env file. Keep only:")
        print("      - PLEXAMP_* (Plexamp config stays in env)")
        print("      - SNAPCLIENT_ENABLED (audio device now configured via GUI)")
        print("      - Network/infrastructure settings")
        print()

    except Exception as e:
        print(f"\n✗ Error writing settings: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
