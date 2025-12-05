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
from typing import Dict, List
from flask import Flask, jsonify, request
from flask_cors import CORS

# Add parent directory to path to import settings_api and integrations_api
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings_api import create_settings_blueprint, SettingsManager
from integrations_api import create_integrations_blueprint, IntegrationController

logger = logging.getLogger(__name__)


class FederationAPI:
    """REST API server for federation control"""

    def __init__(self, data_aggregator, router, loop, port: int = 5000):
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for frontend access
        self.data_aggregator = data_aggregator
        self.router = router
        self.loop = loop  # Reference to the async event loop
        self.port = port
        self._setup_routes()
        self._setup_settings_api()
        self._setup_integrations_api()

    def _setup_routes(self):
        """Setup all API routes"""

        @self.app.route("/api/health", methods=["GET"])
        def health():
            """Health check endpoint"""
            return jsonify({"status": "healthy", "service": "federation"})

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

        @self.app.route("/api/federation/route", methods=["POST"])
        def route_client():
            """Route a client to a stream"""
            try:
                data = request.get_json()
                client_id = data.get("clientId")
                stream_id = data.get("streamId")

                if not client_id or not stream_id:
                    return jsonify({"error": "clientId and streamId required"}), 400

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

    def run(self, debug: bool = False):
        """Run the Flask server"""
        logger.info(f"Starting Federation API on port {self.port}")
        self.app.run(host="0.0.0.0", port=self.port, debug=debug, threaded=True)


class DataAggregator:
    """
    Aggregates data from multiple Snapcast servers
    Provides unified view of all streams, clients, and servers
    """

    def __init__(self, ws_manager, discovery, local_server_id: str, local_server_name: str):
        self.ws_manager = ws_manager
        self.discovery = discovery
        self.local_server_id = local_server_id
        self.local_server_name = local_server_name

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

    def get_streams(self) -> List[Dict]:
        """Get all streams from all servers"""
        streams = []

        for conn in self.ws_manager.get_all_connections():
            if not conn.connected or not conn.last_status:
                continue

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
                    "properties": enhanced_properties
                })

        return streams

    def get_clients(self) -> List[Dict]:
        """Get all clients from all servers"""
        clients = []

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

                    clients.append({
                        "id": federated_id,
                        "serverId": conn.server_id,
                        "serverName": conn.name,
                        "name": config.get("name") or host_info.get("name", client_id),
                        "connected": client.get("connected", False),
                        "currentStreamId": federated_stream_id,
                        "volume": volume.get("percent", 100),
                        "muted": volume.get("muted", False)
                    })

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
