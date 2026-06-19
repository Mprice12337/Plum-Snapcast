#!/usr/bin/env python3
"""
REST API for Federation Service
Exposes unified API for controlling multiple Snapcast servers
"""

import asyncio
import json
import logging
import os
import re
import sys
import requests
from typing import Dict, List, Optional, Tuple
from flask import Flask, jsonify, request
from flask_cors import CORS

# Subprocess for D-Bus commands (avoids session bus connection issues in containers)
import subprocess

# Add parent directory to path to import settings_api, integrations_api, audio_api, and playback_api
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings_api import create_settings_blueprint, SettingsManager
from integrations_api import create_integrations_blueprint, IntegrationController
from audio_api import create_audio_blueprint, AudioConfigController
from playback_api import create_playback_blueprint, playback_store
from testtone_api import create_testtone_blueprint

logger = logging.getLogger(__name__)


def _get_raw_client_id(client: dict) -> str:
    """Extract the raw (un-prefixed) Snapcast client ID from a federation client entry."""
    server_id = client.get("serverId", "")
    prefix = server_id + "-"
    cid = client.get("id", "")
    return cid[len(prefix):] if cid.startswith(prefix) else cid


def _is_remote_snapclient(client: dict) -> bool:
    """Return True for infrastructure remote snapclient entries.

    RemoteSnapclientManager spawns snapclients with --hostID remote-<server-id>.
    These appear on remote servers as clients named "remote-server-X-Y-Z-W" and
    are infrastructure-only — they must not appear as user-visible devices.
    """
    return _get_raw_client_id(client).startswith("remote-")


def _dedup_clients_by_raw_id(clients: list) -> list:
    """De-duplicate federation client list by raw snapclient ID.

    When a snapclient moves from its local server to a remote master (slave mode),
    it appears twice: once disconnected on the local server, and once connected on
    the master. Keep the connected version (correct serverId for volume routing),
    but add localServerId from the local (home) server entry so the frontend can
    still identify which physical device the client belongs to for display purposes.
    """
    seen: dict = {}  # raw_id → index in result
    result = []
    for client in clients:
        raw_id = _get_raw_client_id(client)

        if raw_id not in seen:
            seen[raw_id] = len(result)
            result.append(client)
        else:
            existing_idx = seen[raw_id]
            # Prefer connected over disconnected
            if client.get("connected") and not result[existing_idx].get("connected"):
                # Keep the connected version for correct volume routing (its serverId
                # points to where the snapclient is actually connected). Add localServerId
                # from the disconnected local entry so the frontend knows which server
                # this client physically lives on (for stream display and myClient detection).
                merged = dict(client)
                merged["localServerId"] = result[existing_idx].get("serverId")
                result[existing_idx] = merged
    return result


class MPRISVolumeController:
    """
    Direct D-Bus/MPRIS volume control for integration sources.
    Uses subprocess approach to avoid D-Bus session bus connection issues in containers.
    Bypasses Snapcast's Stream.Control which doesn't support setVolume.

    Special handling for Plexamp: Uses HTTP API instead of MPRIS since Plexamp
    runs in a separate container (no shared D-Bus).
    """

    # Map integration keywords to MPRIS service name patterns
    # Uses flexible keyword matching to support custom stream names
    INTEGRATION_MPRIS_MAP = {
        # AirPlay: org.mpris.MediaPlayer2.ShairportSync or ShairportSync.i*
        'airplay': r'org\.mpris\.MediaPlayer2\.ShairportSync(\.i\d+)?$',
        # Spotify: org.mpris.MediaPlayer2.spotifyd or spotifyd.instance*
        'spotify': r'org\.mpris\.MediaPlayer2\.spotifyd(\.instance\d+)?$',
        # DLNA: org.mpris.MediaPlayer2.GMediaRender or gmediarender*
        'dlna': r'org\.mpris\.MediaPlayer2\.GMediaRender',
        # Note: Plexamp uses HTTP API, not MPRIS (separate container)
        # Note: Bluetooth is NOT included - volume is controlled at the source device
    }

    # Plexamp HTTP API settings
    PLEXAMP_HOST = '127.0.0.1'
    PLEXAMP_PORT = 32500

    def __init__(self):
        pass

    def _set_plexamp_volume(self, volume: int) -> Tuple[bool, str]:
        """Set Plexamp volume via HTTP API (separate container, no MPRIS access)"""
        try:
            # Plexamp uses 0-100 scale same as our API
            url = f"http://{self.PLEXAMP_HOST}:{self.PLEXAMP_PORT}/player/playback/setParameters?volume={volume}"
            result = subprocess.run(
                ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
                 '--connect-timeout', '2', url],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0 and result.stdout.strip() == '200':
                logger.info(f"Set Plexamp volume to {volume}% via HTTP API")
                return True, f"Volume set to {volume}%"
            else:
                logger.error(f"Failed to set Plexamp volume: HTTP {result.stdout}")
                return False, f"Failed to set Plexamp volume: HTTP {result.stdout}"

        except subprocess.TimeoutExpired:
            return False, "Timeout setting Plexamp volume"
        except Exception as e:
            logger.error(f"Error setting Plexamp volume: {e}")
            return False, f"Error: {str(e)}"

    def _get_plexamp_volume(self) -> Tuple[bool, int, str]:
        """Get Plexamp volume via HTTP timeline API"""
        try:
            url = f"http://{self.PLEXAMP_HOST}:{self.PLEXAMP_PORT}/player/timeline/poll?wait=0"
            result = subprocess.run(
                ['curl', '-s', '--connect-timeout', '2', url],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return False, 0, "Failed to query Plexamp timeline"

            # Parse XML response for volume attribute
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(result.stdout)
                for timeline in root.findall('.//Timeline[@type="music"]'):
                    volume = timeline.get('volume')
                    if volume is not None:
                        return True, int(volume), f"Volume: {volume}%"
            except ET.ParseError:
                pass

            return False, 0, "Could not parse Plexamp volume"

        except Exception as e:
            return False, 0, f"Error: {str(e)}"

    def _find_mpris_service(self, stream_id: str) -> Optional[str]:
        """
        Find the MPRIS service name for a given stream ID using subprocess.

        Args:
            stream_id: Snapcast stream ID (e.g., "airplay1", "spotify2")

        Returns:
            MPRIS service name or None if not found
        """
        try:
            # List all D-Bus services using dbus-send (system bus)
            result = subprocess.run(
                ['dbus-send', '--system', '--dest=org.freedesktop.DBus',
                 '--type=method_call', '--print-reply',
                 '/org/freedesktop/DBus', 'org.freedesktop.DBus.ListNames'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"Failed to list D-Bus services: {result.stderr}")
                return None

            # Parse output for MPRIS services
            mpris_services = []
            for line in result.stdout.split('\n'):
                if 'org.mpris.MediaPlayer2.' in line:
                    # Extract service name from dbus-send output
                    # Format: string "org.mpris.MediaPlayer2.ShairportSync"
                    match = re.search(r'"(org\.mpris\.MediaPlayer2\.[^"]+)"', line)
                    if match:
                        mpris_services.append(match.group(1))

            logger.debug(f"Found MPRIS services: {mpris_services}")

            # Match stream ID to service using flexible keyword matching
            stream_id_lower = stream_id.lower()

            for keyword, mpris_pattern in self.INTEGRATION_MPRIS_MAP.items():
                if keyword in stream_id_lower:
                    logger.debug(f"Stream '{stream_id}' contains keyword '{keyword}', looking for MPRIS pattern: {mpris_pattern}")
                    for service in mpris_services:
                        if re.match(mpris_pattern, service):
                            logger.info(f"Found MPRIS service {service} for stream {stream_id}")
                            return service
                    # Keyword found but no matching service
                    logger.warning(f"Keyword '{keyword}' found in stream ID but no matching MPRIS service")

            logger.warning(f"No MPRIS service found for stream {stream_id}")
            return None

        except subprocess.TimeoutExpired:
            logger.error("Timeout listing D-Bus services")
            return None
        except Exception as e:
            logger.error(f"Error finding MPRIS service: {e}")
            return None

    def _find_bluetooth_transport(self) -> Optional[str]:
        """Find active Bluetooth MediaTransport1 object path for volume control"""
        try:
            # Use dbus-send to get all BlueZ managed objects
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 '--dest=org.bluez', '/',
                 'org.freedesktop.DBus.ObjectManager.GetManagedObjects'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.debug(f"Failed to get BlueZ managed objects: {result.stderr}")
                return None

            # Parse the output to find MediaTransport1 paths
            # Format: object path "/org/bluez/.../fdN" followed by interface lines
            # When we see MediaTransport1, the preceding object path is the transport
            lines = result.stdout.split('\n')
            current_path = None

            for line in lines:
                # Look for object path lines - format: object path "/org/bluez/hci0/dev_.../fd0"
                path_match = re.search(r'object path "(/org/bluez/[^"]+)"', line)
                if path_match:
                    current_path = path_match.group(1)

                # Check if this object has MediaTransport1 interface
                # Format: string "org.bluez.MediaTransport1"
                if current_path and 'org.bluez.MediaTransport1' in line:
                    logger.info(f"Found Bluetooth transport: {current_path}")
                    return current_path

            logger.warning("No active Bluetooth MediaTransport1 found")
            return None

        except subprocess.TimeoutExpired:
            logger.error("Timeout finding Bluetooth transport")
            return None
        except Exception as e:
            logger.error(f"Error finding Bluetooth transport: {e}")
            return None

    def _set_bluetooth_volume(self, volume: int) -> Tuple[bool, str]:
        """Set Bluetooth volume via MediaTransport1 (AVRCP Absolute Volume)"""
        transport_path = self._find_bluetooth_transport()
        if not transport_path:
            return False, "No active Bluetooth audio connection found"

        try:
            # Convert 0-100 to 0-127 for AVRCP
            raw_volume = int(round(volume * 1.27))
            raw_volume = max(0, min(127, raw_volume))

            # Set volume using dbus-send on system bus
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 '--dest=org.bluez',
                 transport_path,
                 'org.freedesktop.DBus.Properties.Set',
                 'string:org.bluez.MediaTransport1',
                 'string:Volume',
                 f'variant:uint16:{raw_volume}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                # Check if it's because Absolute Volume isn't supported
                if 'not supported' in result.stderr.lower() or 'permission' in result.stderr.lower():
                    return False, "Device does not support AVRCP Absolute Volume control"
                logger.error(f"Failed to set Bluetooth volume: {result.stderr}")
                return False, f"Failed to set Bluetooth volume: {result.stderr}"

            logger.info(f"Set Bluetooth volume to {volume}% (raw: {raw_volume}/127)")
            return True, f"Volume set to {volume}%"

        except subprocess.TimeoutExpired:
            return False, "Timeout setting Bluetooth volume"
        except Exception as e:
            logger.error(f"Error setting Bluetooth volume: {e}")
            return False, f"Error: {str(e)}"

    def _get_bluetooth_volume(self) -> Tuple[bool, int, str]:
        """Get Bluetooth volume via MediaTransport1"""
        transport_path = self._find_bluetooth_transport()
        if not transport_path:
            return False, 0, "No active Bluetooth audio connection found"

        try:
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 '--dest=org.bluez',
                 transport_path,
                 'org.freedesktop.DBus.Properties.Get',
                 'string:org.bluez.MediaTransport1',
                 'string:Volume'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return False, 0, f"Failed to get Bluetooth volume: {result.stderr}"

            # Parse volume from output - format: variant uint16 XX
            match = re.search(r'uint16\s+(\d+)', result.stdout)
            if match:
                raw_volume = int(match.group(1))
                volume_percent = int(round(raw_volume / 1.27))
                return True, volume_percent, f"Volume: {volume_percent}%"

            return False, 0, "Could not parse Bluetooth volume"

        except Exception as e:
            return False, 0, f"Error: {str(e)}"

    def set_volume(self, stream_id: str, volume: int) -> Tuple[bool, str]:
        """
        Set volume for a stream via D-Bus or HTTP API.

        Args:
            stream_id: Snapcast stream ID
            volume: Volume level 0-100

        Returns:
            Tuple of (success, message)
        """
        # Check if this is a Plexamp stream - use HTTP API (separate container)
        if 'plexamp' in stream_id.lower():
            return self._set_plexamp_volume(volume)

        # Check if this is a Bluetooth stream - use MediaTransport1 for AVRCP volume
        if 'bluetooth' in stream_id.lower():
            return self._set_bluetooth_volume(volume)

        # Find MPRIS service for this stream (AirPlay, Spotify, etc.)
        service = self._find_mpris_service(stream_id)
        if not service:
            return False, f"No MPRIS service found for stream {stream_id}"

        try:
            # Convert 0-100 to 0.0-1.0 for MPRIS
            mpris_volume = max(0.0, min(1.0, volume / 100.0))

            # Try standard MPRIS Properties.Set first (works for spotifyd and most players)
            # This sets the Volume property on org.mpris.MediaPlayer2.Player interface
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 f'--dest={service}',
                 '/org/mpris/MediaPlayer2',
                 'org.freedesktop.DBus.Properties.Set',
                 'string:org.mpris.MediaPlayer2.Player',
                 'string:Volume',
                 f'variant:double:{mpris_volume}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                logger.info(f"Set volume for {stream_id} ({service}) to {volume}% via Properties.Set")
                return True, f"Volume set to {volume}%"

            # If Properties.Set fails, try ShairportSync's custom SetVolume method
            logger.debug(f"Properties.Set failed, trying SetVolume method: {result.stderr}")
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 f'--dest={service}',
                 '/org/mpris/MediaPlayer2',
                 'org.mpris.MediaPlayer2.Player.SetVolume',
                 f'double:{mpris_volume}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"Both volume methods failed: {result.stderr}")
                return False, f"Failed to set volume: {result.stderr}"

            logger.info(f"Set volume for {stream_id} ({service}) to {volume}% via SetVolume method")
            return True, f"Volume set to {volume}%"

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout setting volume for {stream_id}")
            return False, "Timeout setting volume"
        except Exception as e:
            logger.error(f"Failed to set volume for {stream_id}: {e}")
            return False, f"Error setting volume: {str(e)}"

    def get_volume(self, stream_id: str) -> Tuple[bool, int, str]:
        """
        Get current volume for a stream via D-Bus or HTTP API.

        Args:
            stream_id: Snapcast stream ID

        Returns:
            Tuple of (success, volume 0-100, message)
        """
        # Check if this is a Plexamp stream - use HTTP API (separate container)
        if 'plexamp' in stream_id.lower():
            return self._get_plexamp_volume()

        # Check if this is a Bluetooth stream - use MediaTransport1
        if 'bluetooth' in stream_id.lower():
            return self._get_bluetooth_volume()

        # Find MPRIS service for this stream
        service = self._find_mpris_service(stream_id)
        if not service:
            return False, 0, f"No MPRIS service found for stream {stream_id}"

        try:
            # Get volume using dbus-send (system bus)
            result = subprocess.run(
                ['dbus-send', '--system', '--print-reply',
                 f'--dest={service}',
                 '/org/mpris/MediaPlayer2',
                 'org.freedesktop.DBus.Properties.Get',
                 'string:org.mpris.MediaPlayer2.Player',
                 'string:Volume'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"dbus-send Get Volume failed: {result.stderr}")
                return False, 0, f"Failed to get volume: {result.stderr}"

            # Parse output to get volume value
            # Format: "variant       double 0.5"
            match = re.search(r'double\s+([\d.]+)', result.stdout)
            if not match:
                logger.error(f"Could not parse volume from dbus-send output: {result.stdout}")
                return False, 0, "Failed to parse volume"

            mpris_volume = float(match.group(1))
            volume = int(mpris_volume * 100)

            logger.debug(f"Got volume for {stream_id}: {volume}% (MPRIS: {mpris_volume:.2f})")
            return True, volume, f"Volume: {volume}%"

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout getting volume for {stream_id}")
            return False, 0, "Timeout getting volume"
        except Exception as e:
            logger.error(f"Failed to get volume for {stream_id}: {e}")
            return False, 0, f"Error getting volume: {str(e)}"


# Global MPRIS volume controller instance
mpris_volume_controller = MPRISVolumeController()


class FederationAPI:
    """REST API server for federation control"""

    def __init__(self, data_aggregator, router, loop, port: int = 5000, service=None):
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for frontend access
        self.data_aggregator = data_aggregator
        self.router = router
        self.loop = loop  # Reference to the async event loop
        self.service = service  # Reference to FederationService for health checks
        self.port = port
        self._setup_routes()
        self._setup_settings_api()
        self._setup_integrations_api()
        self._setup_audio_api()
        self._setup_playback_api()
        self._setup_testtone_api()

    def _check_loop_health(self) -> bool:
        """Check if the async event loop is healthy"""
        # Use service's health check if available (more comprehensive)
        if self.service and hasattr(self.service, 'is_loop_healthy'):
            return self.service.is_loop_healthy()
        # Fallback to basic check
        return self.loop is not None and not self.loop.is_closed()

    def _setup_routes(self):
        """Setup all API routes"""

        @self.app.route("/api/health", methods=["GET"])
        def health():
            """Health check endpoint with loop status"""
            loop_healthy = self._check_loop_health()
            status = "healthy" if loop_healthy else "degraded"
            return jsonify({
                "status": status,
                "service": "federation",
                "loop_healthy": loop_healthy
            }), 200 if loop_healthy else 503

        @self.app.route("/api/federation/info", methods=["GET"])
        def get_info():
            """Get local server information"""
            try:
                info = {
                    "id": self.data_aggregator.local_server_id,
                    "name": self.data_aggregator.local_server_name
                }
                return jsonify(info)
            except Exception as e:
                logger.error(f"Get info failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/servers", methods=["GET"])
        def get_servers():
            """Get all discovered servers"""
            try:
                servers = self.data_aggregator.get_servers()
                return jsonify({"servers": servers})
            except Exception as e:
                logger.error(f"Get servers failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/streams", methods=["GET"])
        def get_streams():
            """Get all streams from all servers"""
            try:
                streams = self.data_aggregator.get_streams()
                return jsonify({"streams": streams})
            except Exception as e:
                logger.error(f"Get streams failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/clients", methods=["GET"])
        def get_clients():
            """Get all clients from all servers"""
            try:
                clients = self.data_aggregator.get_clients()
                return jsonify({"clients": clients})
            except Exception as e:
                logger.error(f"Get clients failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/snapshot", methods=["GET"])
        def get_snapshot():
            """
            Get atomic snapshot of all federation data (servers, streams, clients).

            This endpoint returns all three data types from a single consistent view
            of the connection state, preventing race conditions where streams reference
            servers that don't exist yet, or clients disappear temporarily.
            """
            try:
                snapshot = self.data_aggregator.get_snapshot()
                return jsonify(snapshot)
            except Exception as e:
                logger.error(f"Get snapshot failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/active-endpoint", methods=["GET"])
        def get_active_endpoint():
            """
            Get the currently active endpoint (server/client/stream).

            Always queries all servers dynamically to find output clients NOT on none streams.
            This ensures consistent results across all federation servers.
            """
            try:
                # Always compute active endpoint dynamically from server states
                # Do NOT use cached self.router.active_endpoint as it's not synchronized across servers
                result = asyncio.run(self.router._find_active_endpoint())
                return jsonify(result)
            except Exception as e:
                logger.error(f"Get active endpoint failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/route", methods=["POST"])
        def route_client():
            """Route a client to a stream"""
            try:
                data = request.get_json()
                client_id = data.get("clientId")
                stream_id = data.get("streamId")

                logger.info(f"Route request: clientId={client_id}, streamId={stream_id}")

                if not client_id or not stream_id:
                    return jsonify({"error": "clientId and streamId required"}), 400

                # Check if event loop is healthy
                if not self._check_loop_health():
                    logger.error("Event loop is not healthy, cannot route client")
                    return jsonify({"error": "Service not ready - async loop unavailable"}), 503

                # Schedule coroutine on the background event loop
                future = asyncio.run_coroutine_threadsafe(
                    self.router.route_client(client_id, stream_id),
                    self.loop
                )
                result = future.result(timeout=30)

                if result.get("success"):
                    return jsonify(result)
                else:
                    return jsonify(result), 400

            except Exception as e:
                logger.error(f"Route failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/client/volume", methods=["POST"])
        def set_volume():
            """Set client volume"""
            try:
                data = request.get_json()
                client_id = data.get("clientId")
                volume = data.get("volume")
                muted = data.get("muted", False)

                if not client_id or volume is None:
                    return jsonify({"error": "clientId and volume required"}), 400

                if not self._check_loop_health():
                    return jsonify({"error": "Service not ready - async loop unavailable"}), 503

                # Schedule coroutine on the background event loop
                future = asyncio.run_coroutine_threadsafe(
                    self.router.set_client_volume(client_id, volume, muted),
                    self.loop
                )
                result = future.result(timeout=30)

                if result.get("success"):
                    return jsonify(result)
                else:
                    return jsonify(result), 400

            except Exception as e:
                logger.error(f"Set volume failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/stream/control", methods=["POST"])
        def control_stream():
            """Control stream playback"""
            try:
                data = request.get_json()
                stream_id = data.get("streamId")
                command = data.get("command")

                if not stream_id or not command:
                    return jsonify({"error": "streamId and command required"}), 400

                if not self._check_loop_health():
                    return jsonify({"error": "Service not ready - async loop unavailable"}), 503

                # Schedule coroutine on the background event loop
                future = asyncio.run_coroutine_threadsafe(
                    self.router.control_stream(stream_id, command),
                    self.loop
                )
                result = future.result(timeout=30)

                if result.get("success"):
                    return jsonify(result)
                else:
                    return jsonify(result), 400

            except Exception as e:
                logger.error(f"Stream control failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/stream/volume", methods=["POST"])
        def set_stream_volume():
            """Set source volume for a stream (controls AirPlay/Spotify/etc volume via D-Bus MPRIS)"""
            try:
                data = request.get_json()
                stream_id = data.get("streamId")
                volume = data.get("volume")

                if not stream_id or volume is None:
                    return jsonify({"error": "streamId and volume required"}), 400

                if not isinstance(volume, (int, float)):
                    return jsonify({"error": "volume must be a number"}), 400

                # Parse federated ID to extract server ID and local stream ID
                # Format: "server-192-168-7-122-airplay1" -> server_id="server-192-168-7-122", local_stream_id="airplay1"
                server_id = None
                local_stream_id = stream_id
                if stream_id.startswith("server-"):
                    parts = stream_id.split("-")
                    if len(parts) >= 6:
                        server_id = "-".join(parts[:5])  # "server-192-168-7-122"
                        local_stream_id = "-".join(parts[5:])  # "airplay1"

                # Check if this is a remote server
                is_remote = server_id and server_id != self.data_aggregator.local_server_id

                if is_remote:
                    # Forward request to remote server's audio API
                    logger.info(f"Forwarding volume request to remote server {server_id} for stream {local_stream_id}")

                    # Find the connection to get the host
                    conn = self.data_aggregator.ws_manager.get_connection(server_id)
                    if not conn or not conn.connected:
                        return jsonify({"success": False, "message": f"Remote server not connected: {server_id}"}), 400

                    # Forward to remote server's audio API (part of federation service on port 5001)
                    try:
                        remote_url = f"http://{conn.host}:5001/api/audio/source-volume"
                        remote_response = requests.post(
                            remote_url,
                            json={"streamId": local_stream_id, "volume": int(volume)},
                            timeout=5
                        )

                        if remote_response.status_code == 200:
                            remote_data = remote_response.json()
                            return jsonify({"success": True, "message": remote_data.get("message", f"Volume set to {volume}%")})
                        else:
                            error_data = remote_response.json()
                            return jsonify({"success": False, "message": error_data.get("message", error_data.get("error", "Remote server error"))}), 400
                    except requests.exceptions.Timeout:
                        return jsonify({"success": False, "message": f"Timeout connecting to remote server {conn.host}"}), 504
                    except requests.exceptions.RequestException as e:
                        logger.error(f"Failed to forward volume request to {conn.host}: {e}")
                        return jsonify({"success": False, "message": f"Failed to connect to remote server: {str(e)}"}), 502
                else:
                    # Local server - use direct D-Bus MPRIS control
                    success, message = mpris_volume_controller.set_volume(local_stream_id, int(volume))

                    if success:
                        return jsonify({"success": True, "message": message})
                    else:
                        return jsonify({"success": False, "message": message}), 400

            except Exception as e:
                logger.error(f"Set stream volume failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/server/add", methods=["POST"])
        def add_server():
            """Manually add a server"""
            try:
                data = request.get_json()
                host = data.get("host")
                port = data.get("port", 1780)
                name = data.get("name")

                if not host or not name:
                    return jsonify({"error": "host and name required"}), 400

                if not self._check_loop_health():
                    return jsonify({"error": "Service not ready - async loop unavailable"}), 503

                # Schedule coroutine on the background event loop
                future = asyncio.run_coroutine_threadsafe(
                    self.data_aggregator.add_manual_server(host, port, name),
                    self.loop
                )
                result = future.result(timeout=30)

                return jsonify({"success": True, "server": result})

            except Exception as e:
                logger.error(f"Add server failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/server/edit", methods=["POST"])
        def edit_server():
            """Edit a server"""
            try:
                data = request.get_json()
                server_id = data.get("serverId")
                host = data.get("host")
                port = data.get("port", 1780)
                name = data.get("name")

                if not server_id or not host or not name:
                    return jsonify({"error": "serverId, host, and name required"}), 400

                if not self._check_loop_health():
                    return jsonify({"error": "Service not ready - async loop unavailable"}), 503

                # Schedule coroutine on the background event loop
                future = asyncio.run_coroutine_threadsafe(
                    self.data_aggregator.edit_server(server_id, host, port, name),
                    self.loop
                )
                result = future.result(timeout=30)

                return jsonify({"success": True, "server": result})

            except Exception as e:
                logger.error(f"Edit server failed: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/federation/server/remove", methods=["POST"])
        def remove_server():
            """Remove a server"""
            try:
                data = request.get_json()
                server_id = data.get("serverId")

                if not server_id:
                    return jsonify({"error": "serverId required"}), 400

                # Check if event loop is healthy
                if not self._check_loop_health():
                    logger.error("Event loop is not healthy, cannot remove server")
                    return jsonify({"error": "Service not ready - async loop unavailable"}), 503

                # Schedule coroutine on the background event loop
                future = asyncio.run_coroutine_threadsafe(
                    self.data_aggregator.remove_server(server_id),
                    self.loop
                )
                future.result(timeout=30)

                return jsonify({"success": True})

            except Exception as e:
                logger.error(f"Remove server failed: {e}")
                return jsonify({"error": str(e)}), 500

    def _setup_settings_api(self):
        """Register settings API routes"""
        settings_manager = SettingsManager()
        settings_bp = create_settings_blueprint(settings_manager)
        self.app.register_blueprint(settings_bp)
        logger.info("Settings API registered")

    def _setup_integrations_api(self):
        """Register integrations actions API routes"""
        integration_controller = IntegrationController()
        integrations_bp = create_integrations_blueprint(integration_controller)
        self.app.register_blueprint(integrations_bp)
        logger.info("Integrations API registered")

    def _setup_audio_api(self):
        """Register audio configuration API routes"""
        settings_manager = SettingsManager()
        audio_controller = AudioConfigController(settings_manager)
        audio_bp = create_audio_blueprint(audio_controller)
        self.app.register_blueprint(audio_bp)
        logger.info("Audio API registered")

    def _setup_playback_api(self):
        """Register playback position API routes (for real-time position tracking)"""
        playback_bp = create_playback_blueprint()
        self.app.register_blueprint(playback_bp)
        logger.info("Playback API registered")

    def _setup_testtone_api(self):
        """Register test tone API routes (for volume calibration)"""
        testtone_bp = create_testtone_blueprint()
        self.app.register_blueprint(testtone_bp)
        logger.info("Test Tone API registered")

    def run(self, debug: bool = False):
        """Run the Flask server"""
        logger.info(f"Starting Federation API on port {self.port}")
        self.app.run(host="0.0.0.0", port=self.port, debug=debug, threaded=True)


class DataAggregator:
    """
    Aggregates data from multiple Snapcast servers
    Provides unified view of all streams, clients, and servers
    """

    def __init__(self, ws_manager, discovery, local_server_id: str, local_server_name: str, loop=None):
        self.ws_manager = ws_manager
        self.discovery = discovery
        self.local_server_id = local_server_id
        self.local_server_name = local_server_name
        self.loop = loop

    async def _refresh_all_statuses(self):
        """Refresh status from all connected servers"""
        connections = list(self.ws_manager.get_all_connections())
        connected_servers = [conn.name for conn in connections if conn.connected]

        logger.debug(f"Refreshing status from {len(connected_servers)} servers: {connected_servers}")

        tasks = []
        for conn in connections:
            if conn.connected:
                tasks.append(conn.get_status())

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any failures
            for i, (conn, result) in enumerate(zip([c for c in connections if c.connected], results)):
                if isinstance(result, Exception):
                    logger.error(f"Failed to refresh status from {conn.name}: {result}")
                else:
                    logger.debug(f"Successfully refreshed status from {conn.name}")

    def get_servers(self) -> List[Dict]:
        """Get list of all servers"""
        servers = []

        # Add connected servers
        for conn in self.ws_manager.get_all_connections():
            servers.append({
                "id": conn.server_id,
                "name": conn.name,
                "host": conn.host,
                "port": conn.port,
                "connected": conn.connected,
                "isLocal": conn.server_id == self.local_server_id
            })

        # Add discovered but not connected servers
        for server_info in self.discovery.get_servers():
            if server_info.id not in [s["id"] for s in servers]:
                servers.append({
                    "id": server_info.id,
                    "name": server_info.name,
                    "host": server_info.host,
                    "port": server_info.port,
                    "connected": False,
                    "isLocal": server_info.id == self.local_server_id
                })

        return servers

    def _fetch_remote_playback(self, host: str, port: int, stream_id: str) -> Dict:
        """Fetch playback data from a remote server's playback API"""
        try:
            # Use HTTP port 5001 for the federation/playback API
            url = f"http://{host}:5001/api/playback/{stream_id}"
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"Failed to fetch playback from {host} for {stream_id}: {e}")
        return {}

    def get_streams(self) -> List[Dict]:
        """Get all streams from all servers"""
        streams = []

        # Get local playback position data
        local_playback = playback_store.get_all()

        # Cache for remote server playback data (fetched once per server)
        remote_playback_cache = {}

        for conn in self.ws_manager.get_all_connections():
            if not conn.connected or not conn.last_status:
                continue

            # Determine if this is a local or remote server
            is_local = conn.server_id == self.local_server_id

            # Fetch playback data from remote server if needed (once per server)
            if not is_local and conn.server_id not in remote_playback_cache:
                # Fetch all playback data from remote server
                try:
                    url = f"http://{conn.host}:5001/api/playback"
                    response = requests.get(url, timeout=2)
                    if response.status_code == 200:
                        data = response.json()
                        remote_playback_cache[conn.server_id] = data.get("streams", {})
                    else:
                        remote_playback_cache[conn.server_id] = {}
                except Exception as e:
                    logger.debug(f"Failed to fetch playback from {conn.host}: {e}")
                    remote_playback_cache[conn.server_id] = {}

            server_streams = conn.last_status.get("server", {}).get("streams", [])

            for stream in server_streams:
                # Extract the actual stream ID from Snapcast
                # The stream dict has: {"id": "airplay1", "uri": {...}, "properties": {...}}
                stream_id = stream.get("id", "")

                # Debug logging to see what we're getting
                logger.debug(f"Processing stream - id: '{stream_id}', keys: {list(stream.keys())}")

                # Skip idle streams from remote servers — only expose them when actively playing.
                # This prevents stale or always-present remote AirPlay/Spotify/etc. streams from
                # cluttering the stream selector when nothing is actually streaming on that unit.
                stream_status = stream.get("status", "idle")
                if not is_local and stream_status.lower() != "playing":
                    continue

                federated_id = f"{conn.server_id}-{stream_id}"

                # Extract metadata and properties
                properties = stream.get("properties", {})
                metadata = properties.get("metadata", {})

                # Extract playback status from stream status field
                # Snapcast stream status is "playing", "idle", or "unknown"
                playback_status = "playing" if stream_status.lower() == "playing" else "idle"

                # Build enhanced properties with playbackStatus and position
                enhanced_properties = {
                    **properties,  # Include all original properties
                    "playbackStatus": playback_status,
                    # Position is already in properties.position (in milliseconds)
                    # Duration is already in properties.metadata.duration (in milliseconds)
                }

                # Get playback position data for this stream
                # Use local store for local server, remote cache for remote servers
                if is_local:
                    playback_data = local_playback.get(stream_id, {})
                else:
                    playback_data = remote_playback_cache.get(conn.server_id, {}).get(stream_id, {})

                # Prefer out-of-band metadata + volume from the playback API when fresh; the
                # Snapcast `properties` copy arrives via partial Properties pushes that clobber
                # each other (caused the GUI flap / volume lag). Single consistent source — see
                # fd95db0 / docs/ARCHITECTURE.md. Mirrors _build_streams_from_connections.
                playback_fresh = bool(playback_data) and not playback_data.get("is_stale", True)

                # Transform artUrl for remote servers to absolute URL (properties-fallback path)
                # This ensures the frontend fetches from the correct server
                art_url = metadata.get("artUrl", "")
                if not is_local and art_url:
                    if art_url.startswith("/coverart/"):
                        # Transform to absolute URL pointing to remote server's coverart proxy
                        filename = art_url.replace("/coverart/", "")
                        art_url = f"http://{conn.host}:5001/api/settings/proxy/coverart/{filename}"
                    elif art_url.startswith("/"):
                        # Other relative URLs - point to remote server's Snapcast HTTP
                        art_url = f"http://{conn.host}:1780{art_url}"

                if playback_fresh:
                    md_title = playback_data.get("title") or metadata.get("title", "")
                    md_artist = playback_data.get("artist") or metadata.get("artist", "")
                    md_album = playback_data.get("album") or metadata.get("album", "")
                    md_art = playback_data.get("artUrl") or art_url
                    pb_volume = playback_data.get("volume")
                    source_volume = pb_volume if pb_volume is not None else properties.get("volume")
                else:
                    md_title = metadata.get("title", "")
                    md_artist = metadata.get("artist", "")
                    md_album = metadata.get("album", "")
                    md_art = art_url
                    source_volume = properties.get("volume")

                # Extract stream display name from properties or URI
                stream_name = properties.get("name", "")
                if not stream_name:
                    # Try URI query name
                    uri = stream.get("uri", {})
                    if isinstance(uri, dict):
                        query = uri.get("query", {})
                        stream_name = query.get("name", stream_id)
                    else:
                        stream_name = stream_id

                streams.append({
                    "id": federated_id,
                    "serverId": conn.server_id,
                    "serverName": conn.name,
                    "name": stream_name,  # Fixed: use actual stream name, not status
                    "status": stream_status,
                    "metadata": {
                        "title": md_title,
                        "artist": md_artist,
                        "album": md_album,
                        "artUrl": md_art,
                        "duration": metadata.get("duration", 0)
                    },
                    "properties": enhanced_properties,
                    "playback": {
                        "position": playback_data.get("position", 0),
                        "duration": playback_data.get("duration", 0),
                        "interpolated_position": playback_data.get("interpolated_position", 0),
                        "playback_status": playback_data.get("playback_status", "unknown"),
                        "is_stale": playback_data.get("is_stale", True)
                    },
                    # Source volume at top level for frontend Stream interface
                    "volume": source_volume
                })

        return streams

    def get_clients(self) -> List[Dict]:
        """Get all clients from all servers"""
        import asyncio
        import time

        # Force fresh status from all servers to avoid stale data
        refresh_start = time.time()
        refresh_success = False
        try:
            # Get the event loop from the federation service
            if hasattr(self, 'loop') and self.loop:
                logger.debug("Starting status refresh from all servers...")
                future = asyncio.run_coroutine_threadsafe(
                    self._refresh_all_statuses(),
                    self.loop
                )
                # Wait up to 10 seconds for refresh (increased from 2s)
                future.result(timeout=10.0)
                refresh_success = True
                logger.debug(f"Status refresh completed in {time.time() - refresh_start:.2f}s")
            else:
                logger.warning("No event loop available for status refresh")
        except asyncio.TimeoutError:
            logger.error(f"Status refresh timed out after {time.time() - refresh_start:.2f}s")
        except Exception as e:
            logger.error(f"Failed to refresh statuses: {e}", exc_info=True)

        if not refresh_success:
            logger.warning("Building client list with potentially stale data")

        clients = []

        # Build IP → server name map so remote clients show their origin server's name
        generic_names = ["snapserver", "snapclient", "localhost", "127.0.0.1", "::1"]
        server_ip_to_name = {
            c.host: c.name
            for c in self.ws_manager.get_all_connections()
            if c.host
        }

        # First pass: Build initial client list
        for conn in self.ws_manager.get_all_connections():
            if not conn.connected or not conn.last_status:
                continue

            groups = conn.last_status.get("server", {}).get("groups", [])

            for group in groups:
                current_stream_id = group.get("stream_id", "")
                federated_stream_id = f"{conn.server_id}-{current_stream_id}" if current_stream_id else None

                for client in group.get("clients", []):
                    client_id = client.get("id", "")
                    federated_id = f"{conn.server_id}-{client_id}"

                    config = client.get("config", {})
                    volume = config.get("volume", {})
                    host_info = client.get("host", {})

                    # Get client name, with fallback to hostname
                    client_name = config.get("name") or host_info.get("name", client_id)

                    # If client name is generic (snapserver, snapclient, localhost, etc),
                    # use the origin server's name by matching the client's IP to known servers.
                    if client_name.lower() in generic_names or client_name == client_id:
                        # Normalize IPv4-mapped IPv6 ("::ffff:192.168.7.203" → "192.168.7.203")
                        client_ip = host_info.get("ip", "").replace("::ffff:", "")
                        if client_ip in ("127.0.0.1", "::1", ""):
                            display_name = conn.name  # local client — use this server's name
                        else:
                            display_name = server_ip_to_name.get(client_ip, conn.name)
                    else:
                        display_name = client_name

                    clients.append({
                        "id": federated_id,
                        "serverId": conn.server_id,
                        "serverName": conn.name,
                        "name": display_name,
                        "connected": client.get("connected", False),
                        "currentStreamId": federated_stream_id,
                        "volume": volume.get("percent", 100),
                        "muted": volume.get("muted", False)
                    })

        # Second pass: Fix stream assignments for clients playing via remote snapclients
        # Build a map of remote snapclients to their source servers
        # remote-server-X-Y-Z-W means a snapclient FROM server X-Y-Z-W
        remote_snapclient_map = {}  # {"remote-server-id": {"stream": "stream-id", "server": "server-id"}}

        for conn in self.ws_manager.get_all_connections():
            if not conn.connected or not conn.last_status:
                continue

            for group in conn.last_status.get("server", {}).get("groups", []):
                current_stream_id = group.get("stream_id", "")

                # Skip none streams
                if not current_stream_id or "none-" in current_stream_id:
                    continue

                for client in group.get("clients", []):
                    client_id = client.get("id", "")

                    # Check if this is a remote snapclient (ID starts with "remote-server-")
                    if client_id.startswith("remote-server-"):
                        # Extract the source server ID (everything after "remote-")
                        source_server_id = client_id.replace("remote-", "")
                        federated_stream_id = f"{conn.server_id}-{current_stream_id}"

                        logger.debug(f"Found remote snapclient: {client_id} on {conn.name}/{current_stream_id} -> mapping {source_server_id} to {federated_stream_id}")

                        remote_snapclient_map[source_server_id] = {
                            "stream": federated_stream_id,
                            "server": conn.server_id
                        }

        if remote_snapclient_map:
            logger.debug(f"Remote snapclient map: {remote_snapclient_map}")

        # Update client stream assignments based on remote snapclient activity
        # ONLY if they should be mapped (not if user explicitly switched to none)
        updates_made = 0
        for client in clients:
            # Skip if client is already on a non-none stream
            if client["currentStreamId"] and "none-" not in client["currentStreamId"]:
                continue

            # Check if this server has a remote snapclient playing elsewhere
            server_id = client["serverId"]
            if server_id in remote_snapclient_map:
                # Verify the remote snapclient is still active on a real stream
                # by re-checking the current server status
                remote_info = remote_snapclient_map[server_id]
                remote_server_id = remote_info["server"]
                remote_stream_id = remote_info["stream"]

                # Double-check: Look up the remote snapclient in the current status
                # to ensure it hasn't been switched back to none since the map was built
                remote_conn = self.ws_manager.get_connection(remote_server_id)
                if remote_conn and remote_conn.connected and remote_conn.last_status:
                    # Find the remote snapclient in the server's current groups
                    remote_client_id = f"remote-{server_id}"
                    remote_client_stream = None

                    for group in remote_conn.last_status.get("server", {}).get("groups", []):
                        for client_entry in group.get("clients", []):
                            if client_entry.get("id") == remote_client_id:
                                remote_client_stream = group.get("stream_id", "")
                                break
                        if remote_client_stream is not None:
                            break

                    # Only apply mapping if remote client is STILL on a non-none stream
                    if remote_client_stream and "none-" not in remote_client_stream:
                        # This server's remote snapclient is playing a stream
                        # Update ALL clients from this server to show they're on that stream
                        old_stream = client["currentStreamId"]
                        new_stream = remote_snapclient_map[server_id]["stream"]
                        client["currentStreamId"] = new_stream
                        logger.debug(f"Updated client {client['name']} ({server_id}) from {old_stream} to {new_stream}")
                        updates_made += 1
                    else:
                        logger.debug(f"Skipping mapping for {client['name']} - remote snapclient {remote_client_id} is on none stream ({remote_client_stream})")

        if updates_made > 0:
            logger.debug(f"Updated {updates_made} client stream assignments based on remote snapclient activity")

        # De-duplicate: when the same physical client (same raw MAC/ID) appears on multiple
        # servers (e.g. slave mode moved it from local to master), keep the connected version.
        clients = _dedup_clients_by_raw_id(clients)

        # Remove remote snapclient infrastructure entries — these are spawned by
        # RemoteSnapclientManager (--hostID remote-<server-id>) and must never appear
        # as user-visible devices regardless of their displayed name.
        clients = [c for c in clients if not _is_remote_snapclient(c)]

        return clients

    def get_snapshot(self) -> Dict:
        """
        Get atomic snapshot of all federation data (servers, streams, clients).

        This method captures a consistent view of all data from the same set of connections,
        preventing race conditions where streams reference servers that don't exist yet.

        Returns:
            Dict with keys: servers, streams, clients
        """
        logger.debug("Building atomic snapshot of federation data")

        # Capture connection list once to ensure consistency
        connections = list(self.ws_manager.get_all_connections())

        # Build all data from the same connection snapshot
        servers = self._build_servers_from_connections(connections)
        streams = self._build_streams_from_connections(connections)
        clients = self._build_clients_from_connections(connections)

        logger.debug(f"Snapshot: {len(servers)} servers, {len(streams)} streams, {len(clients)} clients")

        return {
            "servers": servers,
            "streams": streams,
            "clients": clients
        }

    def _build_servers_from_connections(self, connections: List) -> List[Dict]:
        """Build servers list from a snapshot of connections"""
        servers = []

        # Add connected servers from snapshot
        for conn in connections:
            servers.append({
                "id": conn.server_id,
                "name": conn.name,
                "host": conn.host,
                "port": conn.port,
                "connected": conn.connected,
                "isLocal": conn.server_id == self.local_server_id
            })

        # Add discovered but not connected servers
        for server_info in self.discovery.get_servers():
            if server_info.id not in [s["id"] for s in servers]:
                servers.append({
                    "id": server_info.id,
                    "name": server_info.name,
                    "host": server_info.host,
                    "port": server_info.port,
                    "connected": False,
                    "isLocal": server_info.id == self.local_server_id
                })

        return servers

    def _build_streams_from_connections(self, connections: List) -> List[Dict]:
        """Build streams list from a snapshot of connections (same logic as get_streams)"""
        streams = []

        # Get local playback position data
        local_playback = playback_store.get_all()

        # Cache for remote server playback data
        remote_playback_cache = {}

        for conn in connections:
            if not conn.connected or not conn.last_status:
                continue

            # Determine if this is a local or remote server
            is_local = conn.server_id == self.local_server_id

            # Fetch playback data from remote server if needed
            if not is_local and conn.server_id not in remote_playback_cache:
                try:
                    url = f"http://{conn.host}:5001/api/playback"
                    response = requests.get(url, timeout=2)
                    if response.status_code == 200:
                        data = response.json()
                        remote_playback_cache[conn.server_id] = data.get("streams", {})
                    else:
                        remote_playback_cache[conn.server_id] = {}
                except Exception as e:
                    logger.debug(f"Failed to fetch playback from {conn.host}: {e}")
                    remote_playback_cache[conn.server_id] = {}

            server_streams = conn.last_status.get("server", {}).get("streams", [])

            for stream in server_streams:
                stream_id = stream.get("id", "")

                # Skip idle streams from remote servers (same rule as get_streams).
                stream_status = stream.get("status", "idle")
                if not is_local and stream_status.lower() != "playing":
                    continue

                federated_id = f"{conn.server_id}-{stream_id}"

                properties = stream.get("properties", {})
                metadata = properties.get("metadata", {})

                playback_status = "playing" if stream_status.lower() == "playing" else "idle"

                enhanced_properties = {
                    **properties,
                    "playbackStatus": playback_status,
                }

                # Get playback position data
                if is_local:
                    playback_data = local_playback.get(stream_id, {})
                else:
                    playback_data = remote_playback_cache.get(conn.server_id, {}).get(stream_id, {})

                # Prefer out-of-band metadata + volume from the playback API when its record
                # is fresh. The Snapcast `properties` copy is delivered via partial
                # Plugin.Stream.Player.Properties pushes that clobber each other (state pushes
                # carry no metadata; metadata pushes carry no volume), which is what made the
                # GUI flap between previous/new and lag on volume. The playback API is a single
                # consistent source (see fd95db0 / docs/ARCHITECTURE.md). Fall back to
                # properties when the playback record is stale/absent (e.g. cold start).
                playback_fresh = bool(playback_data) and not playback_data.get("is_stale", True)

                # Transform artUrl for remote servers to absolute URL (properties-fallback path)
                art_url = metadata.get("artUrl", "")
                if not is_local and art_url:
                    if art_url.startswith("/coverart/"):
                        filename = art_url.replace("/coverart/", "")
                        art_url = f"http://{conn.host}:5001/api/settings/proxy/coverart/{filename}"
                    elif art_url.startswith("/"):
                        art_url = f"http://{conn.host}:1780{art_url}"

                if playback_fresh:
                    md_title = playback_data.get("title") or metadata.get("title", "")
                    md_artist = playback_data.get("artist") or metadata.get("artist", "")
                    md_album = playback_data.get("album") or metadata.get("album", "")
                    # Playback API artUrl is a self-contained data: URL — no proxy transform needed
                    md_art = playback_data.get("artUrl") or art_url
                    pb_volume = playback_data.get("volume")
                    source_volume = pb_volume if pb_volume is not None else properties.get("volume")
                else:
                    md_title = metadata.get("title", "")
                    md_artist = metadata.get("artist", "")
                    md_album = metadata.get("album", "")
                    md_art = art_url
                    source_volume = properties.get("volume")

                # Extract stream display name
                stream_name = properties.get("name", "")
                if not stream_name:
                    uri = stream.get("uri", {})
                    if isinstance(uri, dict):
                        query = uri.get("query", {})
                        stream_name = query.get("name", stream_id)
                    else:
                        stream_name = stream_id

                streams.append({
                    "id": federated_id,
                    "serverId": conn.server_id,
                    "serverName": conn.name,
                    "name": stream_name,
                    "status": stream_status,
                    "metadata": {
                        "title": md_title,
                        "artist": md_artist,
                        "album": md_album,
                        "artUrl": md_art,
                        "duration": metadata.get("duration", 0)
                    },
                    "properties": enhanced_properties,
                    "playback": {
                        "position": playback_data.get("position", 0),
                        "duration": playback_data.get("duration", 0),
                        "interpolated_position": playback_data.get("interpolated_position", 0),
                        "playback_status": playback_data.get("playback_status", "unknown"),
                        "is_stale": playback_data.get("is_stale", True)
                    },
                    "volume": source_volume
                })

        return streams

    def _build_clients_from_connections(self, connections: List) -> List[Dict]:
        """Build clients list from a snapshot of connections (simplified version without refresh)"""
        import asyncio
        import time

        # Force fresh status from all servers
        refresh_start = time.time()
        refresh_success = False
        try:
            if hasattr(self, 'loop') and self.loop:
                logger.debug("Starting status refresh from all servers...")
                future = asyncio.run_coroutine_threadsafe(
                    self._refresh_all_statuses(),
                    self.loop
                )
                future.result(timeout=10.0)
                refresh_success = True
                logger.debug(f"Status refresh completed in {time.time() - refresh_start:.2f}s")
            else:
                logger.warning("No event loop available for status refresh")
        except asyncio.TimeoutError:
            logger.error(f"Status refresh timed out after {time.time() - refresh_start:.2f}s")
        except Exception as e:
            logger.error(f"Failed to refresh statuses: {e}", exc_info=True)

        if not refresh_success:
            logger.warning("Building client list with potentially stale data")

        clients = []

        # Build IP → server name map so remote clients show their origin server's name
        generic_names = ["snapserver", "snapclient", "localhost", "127.0.0.1", "::1"]
        server_ip_to_name = {c.host: c.name for c in connections if c.host}

        # Build client list from connections snapshot
        for conn in connections:
            if not conn.connected or not conn.last_status:
                continue

            groups = conn.last_status.get("server", {}).get("groups", [])

            for group in groups:
                current_stream_id = group.get("stream_id", "")
                federated_stream_id = f"{conn.server_id}-{current_stream_id}" if current_stream_id else None

                for client in group.get("clients", []):
                    client_id = client.get("id", "")
                    federated_id = f"{conn.server_id}-{client_id}"

                    config = client.get("config", {})
                    volume = config.get("volume", {})
                    host_info = client.get("host", {})

                    client_name = config.get("name") or host_info.get("name", client_id)

                    # If client name is generic, use origin server name derived from client IP
                    if client_name.lower() in generic_names or client_name == client_id:
                        client_ip = host_info.get("ip", "").replace("::ffff:", "")
                        if client_ip in ("127.0.0.1", "::1", ""):
                            display_name = conn.name
                        else:
                            display_name = server_ip_to_name.get(client_ip, conn.name)
                    else:
                        display_name = client_name

                    clients.append({
                        "id": federated_id,
                        "serverId": conn.server_id,
                        "serverName": conn.name,
                        "name": display_name,
                        "connected": client.get("connected", False),
                        "currentStreamId": federated_stream_id,
                        "volume": volume.get("percent", 100),
                        "muted": volume.get("muted", False)
                    })

        # Fix stream assignments for remote snapclients
        remote_snapclient_map = {}

        for conn in connections:
            if not conn.connected or not conn.last_status:
                continue

            for group in conn.last_status.get("server", {}).get("groups", []):
                current_stream_id = group.get("stream_id", "")

                if not current_stream_id or "none-" in current_stream_id:
                    continue

                for client in group.get("clients", []):
                    client_id = client.get("id", "")

                    if client_id.startswith("remote-server-"):
                        source_server_id = client_id.replace("remote-", "")
                        federated_stream_id = f"{conn.server_id}-{current_stream_id}"

                        logger.debug(f"Found remote snapclient: {client_id} on {conn.name}/{current_stream_id}")

                        remote_snapclient_map[source_server_id] = {
                            "stream": federated_stream_id,
                            "server": conn.server_id
                        }

        if remote_snapclient_map:
            logger.debug(f"Remote snapclient map: {remote_snapclient_map}")

        # Update client stream assignments
        updates_made = 0
        for client in clients:
            if client["currentStreamId"] and "none-" not in client["currentStreamId"]:
                continue

            server_id = client["serverId"]
            if server_id in remote_snapclient_map:
                remote_client_id = f"remote-{server_id}"
                remote_client = next((c for c in clients if c["id"].endswith(remote_client_id)), None)

                if remote_client:
                    remote_client_stream = remote_client.get("currentStreamId", "")

                    if remote_client_stream and "none-" not in remote_client_stream:
                        old_stream = client["currentStreamId"]
                        new_stream = remote_snapclient_map[server_id]["stream"]
                        client["currentStreamId"] = new_stream
                        logger.debug(f"Updated client {client['name']} from {old_stream} to {new_stream}")
                        updates_made += 1
                    else:
                        logger.debug(f"Skipping mapping for {client['name']} - on none stream")

        if updates_made > 0:
            logger.debug(f"Updated {updates_made} client stream assignments")

        clients = _dedup_clients_by_raw_id(clients)

        # Remove remote snapclient infrastructure entries (same as in get_clients).
        clients = [c for c in clients if not _is_remote_snapclient(c)]

        return clients

    async def add_manual_server(self, host: str, port: int, name: str) -> Dict:
        """Manually add a server"""
        server_info = self.discovery.add_manual_server(host, port, name)

        # Connect to the server
        try:
            await self.ws_manager.add_server(
                server_id=server_info.id,
                host=host,
                port=port,
                name=name,
                use_https=False
            )

            # Wait briefly to ensure connection is fully established
            await asyncio.sleep(0.5)

            # Verify connection was successful
            conn = self.ws_manager.get_connection(server_info.id)
            if conn and conn.connected:
                logger.info(f"Server {name} successfully connected")
            else:
                logger.warning(f"Server {name} connection may not be fully established")

        except Exception as e:
            logger.error(f"Failed to connect to manually added server {name}: {e}")
            # Server stays in discovery but not connected
            raise

        return server_info.to_dict()

    async def edit_server(self, old_server_id: str, host: str, port: int, name: str) -> Dict:
        """Edit an existing manually added server"""
        logger.info(f"Editing server {old_server_id}: {host}:{port} ({name})")

        # Remove old connection
        await self.ws_manager.remove_server(old_server_id)
        await asyncio.sleep(0.1)  # Brief pause to ensure cleanup completes

        # Update discovery info
        server_info = self.discovery.edit_manual_server(old_server_id, host, port, name)

        # Connect to the server with new details
        try:
            await self.ws_manager.add_server(
                server_id=server_info.id,
                host=host,
                port=port,
                name=name,
                use_https=False
            )

            # Wait briefly to ensure connection is fully established
            await asyncio.sleep(0.5)

            # Verify connection was successful
            conn = self.ws_manager.get_connection(server_info.id)
            if conn and conn.connected:
                logger.info(f"Server {name} successfully reconnected after edit")
            else:
                logger.warning(f"Server {name} connection may not be fully established after edit")

        except Exception as e:
            logger.error(f"Failed to reconnect to edited server {name}: {e}")
            # Server stays in discovery but not connected
            raise

        return server_info.to_dict()

    async def remove_server(self, server_id: str):
        """Remove a server"""
        await self.ws_manager.remove_server(server_id)
        self.discovery.remove_manual_server(server_id)
