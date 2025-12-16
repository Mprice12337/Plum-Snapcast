#!/usr/bin/env python3
"""
Input Stream Manager
Dynamically manages Snapcast input streams based on enabled audio input devices
Uses Snapcast JSON-RPC API to add/remove ALSA input streams
"""

import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from typing import Dict, List, Any, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
SETTINGS_FILE = "/app/data/settings.json"
SNAPCAST_HOST = "127.0.0.1"
SNAPCAST_PORT = 1780
SNAPCAST_JSONRPC_URL = f"http://{SNAPCAST_HOST}:{SNAPCAST_PORT}/jsonrpc"

# Input stream ID prefix to identify managed streams
INPUT_STREAM_PREFIX = "input-"


class SnapcastClient:
    """Simple JSON-RPC client for Snapcast API"""

    def __init__(self, url: str):
        self.url = url
        self.request_id = 1

    def _make_request(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a JSON-RPC request to Snapcast server"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self.request_id,
            "params": params or {}
        }
        self.request_id += 1

        try:
            req = urllib.request.Request(
                self.url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                if "error" in result:
                    logger.error(f"Snapcast API error: {result['error']}")
                    return None
                return result.get("result")
        except Exception as e:
            logger.error(f"Failed to communicate with Snapcast server: {e}")
            return None

    def get_status(self) -> Optional[Dict]:
        """Get Snapcast server status"""
        return self._make_request("Server.GetStatus")

    def add_stream(self, stream_uri: str) -> Optional[Dict]:
        """Add a new stream"""
        return self._make_request("Server.Stream.AddStream", {"streamUri": stream_uri})

    def remove_stream(self, stream_id: str) -> Optional[Dict]:
        """Remove a stream"""
        return self._make_request("Server.Stream.RemoveStream", {"id": stream_id})


class InputStreamManager:
    """Manages dynamic input streams for audio input devices"""

    def __init__(self, settings_file: str = SETTINGS_FILE):
        self.settings_file = settings_file
        self.snapcast = SnapcastClient(SNAPCAST_JSONRPC_URL)

    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from JSON file"""
        try:
            if not os.path.exists(self.settings_file):
                logger.warning(f"Settings file not found: {self.settings_file}")
                return {}

            with open(self.settings_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            return {}

    def _get_enabled_input_devices(self) -> List[Dict[str, Any]]:
        """Get list of enabled input devices from settings"""
        settings = self._load_settings()
        audio_settings = settings.get("audio", {})
        input_settings = audio_settings.get("input", {})
        devices = input_settings.get("devices", [])

        enabled = [d for d in devices if d.get("enabled", False)]
        logger.info(f"Found {len(enabled)} enabled input device(s)")

        return enabled

    def _get_current_streams(self) -> List[Dict[str, Any]]:
        """Get current streams from Snapcast server"""
        status = self.snapcast.get_status()
        if not status:
            logger.error("Failed to get Snapcast server status")
            return []

        server = status.get("server", {})
        streams = server.get("streams", [])
        return streams

    def _get_input_stream_id(self, hw_id: str) -> str:
        """Generate stream ID from hardware ID"""
        # Convert hw:0,0 to input-hw-0-0
        safe_id = hw_id.replace(":", "-").replace(",", "-")
        return f"{INPUT_STREAM_PREFIX}{safe_id}"

    def _create_stream_uri(self, device: Dict[str, Any]) -> str:
        """
        Create ALSA stream URI for input device

        Format: alsa://<device>?name=<name>&sampleformat=<rate>:<bits>:<channels>

        Args:
            device: Device configuration with hw_id and custom_name

        Returns:
            Stream URI string
        """
        hw_id = device.get("hw_id")
        custom_name = device.get("custom_name", hw_id)
        stream_id = self._get_input_stream_id(hw_id)

        # ALSA input parameters
        # Most input devices support 48kHz, 16-bit, stereo
        sample_rate = 48000
        bit_depth = 16
        channels = 2

        # Build stream URI
        # alsa://hw:0,0?name=Microphone&sampleformat=48000:16:2
        params = {
            "name": stream_id,  # Use stream_id as the stream identifier
            "sampleformat": f"{sample_rate}:{bit_depth}:{channels}"
        }

        query_string = urllib.parse.urlencode(params)
        stream_uri = f"alsa://{hw_id}?{query_string}"

        logger.debug(f"Created stream URI: {stream_uri}")
        return stream_uri

    def _should_add_stream(self, device: Dict[str, Any], current_streams: List[Dict]) -> bool:
        """Check if stream should be added"""
        stream_id = self._get_input_stream_id(device.get("hw_id"))

        # Check if stream already exists
        for stream in current_streams:
            if stream.get("id") == stream_id:
                logger.info(f"Stream already exists: {stream_id}")
                return False

        return True

    def _should_remove_stream(self, stream: Dict[str, Any], enabled_devices: List[Dict]) -> bool:
        """Check if stream should be removed"""
        stream_id = stream.get("id", "")

        # Only manage streams with our prefix
        if not stream_id.startswith(INPUT_STREAM_PREFIX):
            return False

        # Check if this stream corresponds to an enabled device
        for device in enabled_devices:
            device_stream_id = self._get_input_stream_id(device.get("hw_id"))
            if stream_id == device_stream_id:
                return False

        # Stream exists but device is not enabled - remove it
        return True

    def sync_streams(self):
        """
        Synchronize input streams with enabled devices

        - Adds streams for enabled devices that don't have streams
        - Removes streams for disabled devices
        """
        logger.info("Starting input stream synchronization...")

        # Get enabled devices and current streams
        enabled_devices = self._get_enabled_input_devices()
        current_streams = self._get_current_streams()

        # Add streams for enabled devices
        for device in enabled_devices:
            if self._should_add_stream(device, current_streams):
                hw_id = device.get("hw_id")
                custom_name = device.get("custom_name", hw_id)
                logger.info(f"Adding input stream for: {custom_name} ({hw_id})")

                stream_uri = self._create_stream_uri(device)
                result = self.snapcast.add_stream(stream_uri)

                if result:
                    logger.info(f"Successfully added stream: {custom_name}")
                else:
                    logger.error(f"Failed to add stream: {custom_name}")

        # Remove streams for disabled devices
        for stream in current_streams:
            if self._should_remove_stream(stream, enabled_devices):
                stream_id = stream.get("id")
                logger.info(f"Removing disabled input stream: {stream_id}")

                result = self.snapcast.remove_stream(stream_id)

                if result:
                    logger.info(f"Successfully removed stream: {stream_id}")
                else:
                    logger.error(f"Failed to remove stream: {stream_id}")

        logger.info("Input stream synchronization complete")


def main():
    """Main entry point"""
    try:
        manager = InputStreamManager()
        manager.sync_streams()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Stream manager failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
