#!/usr/bin/env python3
"""
Bluetooth Connection Monitor
Monitors Bluetooth device connections and resets discoverable mode when devices disconnect.
This ensures the adapter stays discoverable for new devices when "Always discoverable" is enabled.
"""

import json
import logging
import subprocess
import time
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("bt-monitor")

SETTINGS_FILE = Path("/app/data/settings.json")


def get_discoverable_setting():
    """Read the discoverable setting from settings.json"""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                return settings.get('integrations', {}).get('bluetooth', {}).get('discoverable', True)
    except Exception as e:
        logger.error(f"Failed to read discoverable setting: {e}")

    return True  # Default to discoverable


def get_connected_devices():
    """Get list of currently connected Bluetooth devices"""
    try:
        result = subprocess.run(
            ["bluetoothctl", "devices", "Connected"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            # Parse output - format is "Device XX:XX:XX:XX:XX:XX DeviceName"
            devices = []
            for line in result.stdout.strip().split('\n'):
                if line.startswith('Device '):
                    parts = line.split(maxsplit=2)
                    if len(parts) >= 2:
                        mac = parts[1]
                        name = parts[2] if len(parts) > 2 else "Unknown"
                        devices.append((mac, name))
            return devices

    except Exception as e:
        logger.error(f"Failed to get connected devices: {e}")

    return []


def set_discoverable():
    """Set the Bluetooth adapter to discoverable mode"""
    try:
        commands = "power on\ndiscoverable-timeout 0\ndiscoverable on\n"
        result = subprocess.run(
            ["bluetoothctl"],
            input=commands,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            logger.info("Adapter set to discoverable")
            return True
        else:
            logger.error(f"Failed to set discoverable: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Failed to set discoverable: {e}")
        return False


def main():
    """Main monitoring loop"""
    logger.info("Bluetooth connection monitor starting")
    logger.info("Monitoring for device disconnections to reset discoverable mode")

    previous_devices = set()

    while True:
        try:
            # Check if discoverable mode is enabled in settings
            should_be_discoverable = get_discoverable_setting()

            if not should_be_discoverable:
                # User disabled always-discoverable, just monitor
                time.sleep(5)
                continue

            # Get currently connected devices
            current_devices = set(mac for mac, _ in get_connected_devices())

            # Check for disconnections
            disconnected = previous_devices - current_devices
            if disconnected:
                logger.info(f"Detected device disconnection: {disconnected}")
                logger.info("Resetting adapter to discoverable mode")

                # Wait a moment for the connection to fully close
                time.sleep(2)

                # Reset to discoverable
                set_discoverable()

            # Check for new connections
            newly_connected = current_devices - previous_devices
            if newly_connected:
                logger.info(f"Detected device connection: {newly_connected}")

            previous_devices = current_devices

            # Check every 3 seconds
            time.sleep(3)

        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
