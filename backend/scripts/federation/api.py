#!/usr/bin/env python3
"""
REST API for Federation Service
Exposes unified API for controlling multiple Snapcast servers
"""

import asyncio
import json
import logging
import os
import sys
import requests
from typing import Dict, List
from flask import Flask, jsonify, request
from flask_cors import CORS

# Add parent directory to path to import settings_api, integrations_api, audio_api, and playback_api
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings_api import create_settings_blueprint, SettingsManager
from integrations_api import create_integrations_blueprint, IntegrationController
from audio_api import create_audio_blueprint, AudioConfigController
from playback_api import create_playback_blueprint, playback_store

logger = logging.getLogger(__name__)


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
                stream_id = stream.get("id", "")

                federated_id = f"{conn.server_id}-{stream_id}"

                # Extract metadata and properties
                properties = stream.get("properties", {})
                metadata = properties.get("metadata", {})

                # Extract playback status from stream status field
                # Snapcast stream status is "playing", "idle", or "unknown"
                stream_status = stream.get("status", "idle")
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

                streams.append({
                    "id": federated_id,
                    "serverId": conn.server_id,
                    "serverName": conn.name,
                    "name": stream.get("status"),
                    "status": stream_status,
                    "metadata": {
                        "title": metadata.get("title", ""),
                        "artist": metadata.get("artist", ""),
                        "album": metadata.get("album", ""),
                        "artUrl": metadata.get("artUrl", ""),
                        "duration": metadata.get("duration", 0)
                    },
                    "properties": enhanced_properties,
                    "playback": {
                        "position": playback_data.get("position", 0),
                        "duration": playback_data.get("duration", 0),
                        "interpolated_position": playback_data.get("interpolated_position", 0),
                        "playback_status": playback_data.get("playback_status", "unknown"),
                        "is_stale": playback_data.get("is_stale", True)
                    }
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

                    # If client name is generic (snapserver, snapclient, localhost, etc), use server name instead
                    generic_names = ["snapserver", "snapclient", "localhost", "127.0.0.1", "::1"]
                    if client_name.lower() in generic_names or client_name == client_id:
                        display_name = conn.name
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
