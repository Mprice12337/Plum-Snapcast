#!/usr/bin/env python3
"""
Initialize Services from Settings

Reads /app/data/settings.json and starts supervisord services
for integrations that are enabled.

This runs once at container startup (via supervisord) to ensure
services match the persisted settings state.
"""

import json
import logging
import subprocess
import sys
import time

SETTINGS_FILE = "/app/data/settings.json"
SUPERVISORCTL_CONF = "/app/supervisord/supervisord.conf"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [init-services] %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def run_supervisorctl(*args):
    """Run supervisorctl command"""
    try:
        cmd = ["supervisorctl", "-c", SUPERVISORCTL_CONF] + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        logger.info(f"supervisorctl {' '.join(args)}: {result.stdout.strip()}")
        return result.returncode == 0
    except Exception as e:
        logger.error(f"supervisorctl error: {e}")
        return False


def load_settings():
    """Load settings from JSON file"""
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Settings file not found: {SETTINGS_FILE}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in settings file: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
        return {}


def init_services():
    """Initialize services based on settings"""
    logger.info("=== Initializing services from settings ===")

    # Wait a bit for supervisord to fully start
    time.sleep(2)

    settings = load_settings()
    integrations = settings.get("integrations", {})

    # Spotify
    spotify = integrations.get("spotify", {})
    if spotify.get("enabled", False):
        logger.info("Spotify enabled in settings - starting services")
        run_supervisorctl("start", "spotifyd")
        run_supervisorctl("start", "spotify-stream-lifecycle-manager")
        run_supervisorctl("start", "spotify-fifo-keeper")
    else:
        logger.info("Spotify disabled in settings")

    # Bluetooth
    bluetooth = integrations.get("bluetooth", {})
    if bluetooth.get("enabled", False):
        logger.info("Bluetooth enabled in settings - starting services")
        run_supervisorctl("start", "bluetooth")
        run_supervisorctl("start", "bluetooth-monitor")
        run_supervisorctl("start", "bluetooth-stream-lifecycle-manager")
        run_supervisorctl("start", "bluetooth-fifo-keeper")
    else:
        logger.info("Bluetooth disabled in settings")

    # DLNA
    dlna = integrations.get("dlna", {})
    if dlna.get("enabled", False):
        logger.info("DLNA enabled in settings - starting services")
        run_supervisorctl("start", "gmrender")
        run_supervisorctl("start", "gmrender-metadata-bridge")
        run_supervisorctl("start", "dlna-stream-lifecycle-manager")
        run_supervisorctl("start", "dlna-fifo-keeper")
    else:
        logger.info("DLNA disabled in settings")

    # Plexamp
    plexamp = integrations.get("plexamp", {})
    if plexamp.get("enabled", False) and plexamp.get("available", False):
        logger.info("Plexamp enabled in settings - starting lifecycle manager")
        run_supervisorctl("start", "plexamp-stream-lifecycle-manager")
    else:
        logger.info("Plexamp disabled or not available")

    logger.info("=== Service initialization complete ===")


if __name__ == "__main__":
    init_services()
