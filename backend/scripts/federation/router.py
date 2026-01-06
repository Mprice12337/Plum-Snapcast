#!/usr/bin/env python3
"""
Cross-Server Routing Logic
Handles routing clients to streams across different Snapcast servers
"""

import logging
import os
import subprocess
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class FederationRouter:
    """
    Manages cross-server client routing with endpoint lockout.

    New architecture:
    - Multiple snapclients run simultaneously (one local, one per remote server)
    - All output to the same audio device
    - Only ONE is "active" (routed to actual stream) at a time
    - Others are "inactive" (routed to 'none' stream - silence)

    This eliminates the need for snapclient reconnection and provides
    instant stream switching.
    """

    def __init__(self, ws_manager, local_server_id: str, snapclient_manager=None):
        self.ws_manager = ws_manager
        self.local_server_id = local_server_id
        self.snapclient_manager = snapclient_manager  # RemoteSnapclientManager

        # Track active endpoint (server_id, client_id, stream_id)
        # Only one endpoint can be active at a time
        self.active_endpoint: Optional[Tuple[str, str, str]] = None

    def parse_federated_id(self, federated_id: str) -> Tuple[str, str]:
        """
        Parse federated ID into server_id and local_id
        Format: "server-id-stream-name" or "server-id-client-name"
        Example: "server-192-168-7-122-airplay1" -> ("server-192-168-7-122", "airplay1")
        Example: "server-192-168-7-226-esparagus-201" -> ("server-192-168-7-226", "esparagus-201")
        """
        parts = federated_id.split("-")
        if len(parts) >= 5:
            # Server ID is always first 5 components: "server-A-B-C-D" (where A.B.C.D is IP)
            server_part = "-".join(parts[:5])  # "server-192-168-7-122"
            local_part = "-".join(parts[5:]) if len(parts) > 5 else ""  # Everything after
            return server_part, local_part
        return federated_id, ""

    async def route_client(self, client_id: str, stream_id: str) -> Dict:
        """
        Route a client to a stream with endpoint lockout.

        For output clients (local or remote snapclients outputting to audio):
        - Deactivate current active endpoint (route to 'none')
        - Activate new endpoint (route to desired stream)

        For non-output clients (browser clients, third-party clients):
        - Route normally without lockout logic

        Args:
            client_id: Federated client ID (e.g., "server-192-168-7-122-living-room")
            stream_id: Federated stream ID (e.g., "server-192-168-7-226-spotify1")
                       Can be None or "none" to deactivate

        Returns:
            Dict with success status and message
        """
        try:
            # Parse IDs
            client_server_id, client_local_id = self.parse_federated_id(client_id)
            stream_server_id, stream_local_id = self.parse_federated_id(stream_id) if stream_id else (None, None)

            logger.info(f"route_client called: client_id={client_id}, stream_id={stream_id}")
            logger.info(f"Parsed client: server={client_server_id}, local={client_local_id}")
            logger.info(f"Parsed stream: server={stream_server_id}, local={stream_local_id}")

            # Get connections
            client_conn = self.ws_manager.get_connection(client_server_id)
            if not client_conn or not client_conn.connected:
                return {
                    "success": False,
                    "message": f"Client server not connected: {client_server_id}"
                }

            # Find the client in server status
            client_status = await client_conn.get_status()

            # Find the actual client and its group
            actual_client = None
            client_group_id = None
            for group in client_status.get("server", {}).get("groups", []):
                for client in group.get("clients", []):
                    if client.get("id") == client_local_id or client.get("host", {}).get("name") == client_local_id:
                        actual_client = client
                        client_group_id = group.get("id")
                        break
                if actual_client:
                    break

            if not actual_client:
                return {
                    "success": False,
                    "message": f"Client not found: {client_local_id}"
                }

            # Determine if this is an output client (hardware snapclient)
            is_output_client = self._is_output_client(client_server_id, client_local_id)

            if not is_output_client:
                # Non-output client (browser, third-party) - route normally without lockout
                return await self._route_simple(
                    client_conn,
                    client_group_id,
                    stream_local_id if stream_local_id else "none"
                )

            # Output client - apply endpoint lockout logic

            # Step 1: ALWAYS deactivate ALL active endpoints across ALL servers
            # This ensures true lockout - only one output client active at a time across federation
            # Query all servers to find output clients NOT on none streams and route them all to none
            await self._deactivate_all_endpoints()

            # Step 2: Activate new endpoint (if not routing to none)
            # Check if stream_local_id contains "none-" to detect none streams in federation mode
            is_none_stream = not stream_local_id or "none-" in stream_local_id
            if stream_id and not is_none_stream:
                # Verify stream exists
                stream_conn = self.ws_manager.get_connection(stream_server_id)
                if not stream_conn or not stream_conn.connected:
                    return {
                        "success": False,
                        "message": f"Stream server not connected: {stream_server_id}"
                    }

                stream_status = await stream_conn.get_status()
                actual_stream = None
                available_streams = [s.get("id") for s in stream_status.get("server", {}).get("streams", [])]
                logger.info(f"Available streams on {stream_server_id}: {available_streams}")
                logger.info(f"Looking for stream: {repr(stream_local_id)}")

                for stream in stream_status.get("server", {}).get("streams", []):
                    stream_id_from_server = stream.get("id")
                    logger.info(f"Comparing {repr(stream_id_from_server)} == {repr(stream_local_id)}")
                    if stream_id_from_server == stream_local_id:
                        actual_stream = stream
                        break

                if not actual_stream:
                    logger.error(f"Stream {repr(stream_local_id)} not found in {available_streams}")
                    return {
                        "success": False,
                        "message": f"Stream not found: {stream_local_id}"
                    }

                # Check if this is cross-server routing (client and stream on different servers)
                if client_server_id != stream_server_id:
                    logger.info(f"Cross-server routing: {client_server_id} -> {stream_server_id}")

                    # Determine if client is local or remote
                    client_is_local = (client_server_id == self.local_server_id)
                    stream_is_local = (stream_server_id == self.local_server_id)

                    if client_is_local and not stream_is_local:
                        # Case 1: Local client, remote stream
                        # Route our local client to none, then use our remote snapclient
                        logger.info("Case 1: Routing local client to remote stream")

                        # Step 1: Route local client to 'none' on its server
                        await self._route_to_none(client_server_id, client_local_id)

                        # Step 2: Find our remote snapclient on the stream's server
                        if not self.snapclient_manager:
                            return {
                                "success": False,
                                "message": "Remote snapclient manager not available"
                            }

                        remote_client_id = self.snapclient_manager.get_client_id(stream_server_id)
                        if not remote_client_id:
                            return {
                                "success": False,
                                "message": f"No remote snapclient found for {stream_server_id}"
                            }
                    elif not client_is_local and stream_is_local:
                        # Case 2: Remote client, local stream
                        # Find the remote snapclient from their server that connects to us
                        # That remote snapclient appears on OUR (local) server
                        logger.info("Case 2: Routing remote client to local stream")

                        # Find the remote snapclient that belongs to the client's server
                        # It will have ID like "remote-{client_server_id}" and appears on our local server
                        expected_remote_client_id = f"remote-{client_server_id}"

                        # Get our local server status to find this remote snapclient
                        local_status = await stream_conn.get_status()
                        remote_client_group_id = None

                        for group in local_status.get("server", {}).get("groups", []):
                            for client in group.get("clients", []):
                                # Check both client ID and hostname (snapclient uses hostID as hostname)
                                if (client.get("id") == expected_remote_client_id or
                                    client.get("host", {}).get("name") == expected_remote_client_id):
                                    remote_client_group_id = group.get("id")
                                    logger.info(f"Found remote snapclient: {expected_remote_client_id} in group {remote_client_group_id}")
                                    break
                            if remote_client_group_id:
                                break

                        if not remote_client_group_id:
                            return {
                                "success": False,
                                "message": f"Remote snapclient {expected_remote_client_id} not found on local server"
                            }

                        # Route the remote snapclient (on our local server) to our local stream
                        await self._route_simple(stream_conn, remote_client_group_id, stream_local_id)

                        # ALSO route our LOCAL output client to the same stream
                        # This ensures the server hosting the stream also plays it locally
                        local_output_client = await self._find_local_output_client(local_status)
                        if local_output_client:
                            local_client_id = local_output_client.get("id")
                            local_group_id = local_output_client.get("group_id")
                            logger.info(f"Also routing local output client {local_client_id} to {stream_local_id}")
                            await self._route_simple(stream_conn, local_group_id, stream_local_id)
                        else:
                            logger.warning("No local output client found to route to stream")

                        # Update active endpoint tracking
                        self.active_endpoint = (stream_server_id, expected_remote_client_id, stream_local_id)
                        logger.info(f"Activated endpoint: {stream_server_id}/{expected_remote_client_id}/{stream_local_id}")

                        return {
                            "success": True,
                            "message": f"Remote client routed to local stream"
                        }
                    else:
                        # Case 3: Remote client, remote stream (not currently supported)
                        return {
                            "success": False,
                            "message": "Routing between two remote servers not supported"
                        }

                    logger.info(f"Routing remote snapclient {remote_client_id} on {stream_server_id} to stream {stream_local_id}")

                    # Step 3: Find the remote client's group on the stream server
                    remote_group_id = None
                    for group in stream_status.get("server", {}).get("groups", []):
                        for client in group.get("clients", []):
                            if client.get("id") == remote_client_id:
                                remote_group_id = group.get("id")
                                break
                        if remote_group_id:
                            break

                    if not remote_group_id:
                        return {
                            "success": False,
                            "message": f"Remote client {remote_client_id} group not found on {stream_server_id}"
                        }

                    # Step 4: Route the remote client to the desired stream
                    await self._route_simple(stream_conn, remote_group_id, stream_local_id)

                    # Update active endpoint tracking (track the REMOTE client as active)
                    self.active_endpoint = (stream_server_id, remote_client_id, stream_local_id)
                    logger.info(f"Activated endpoint: {stream_server_id}/{remote_client_id}/{stream_local_id}")
                else:
                    # Same-server routing: route directly
                    await self._route_simple(client_conn, client_group_id, stream_local_id)

                    # Update active endpoint tracking
                    self.active_endpoint = (client_server_id, client_local_id, stream_local_id)
                    logger.info(f"Activated endpoint: {client_server_id}/{client_local_id}/{stream_local_id}")

                return {
                    "success": True,
                    "message": f"Client routed to stream with lockout"
                }
            else:
                # Route to none (deactivate)
                # Also route the requesting client to none (in case it's not the active endpoint)
                await self._route_to_none(client_server_id, client_local_id)
                logger.info("All endpoints deactivated")

                return {
                    "success": True,
                    "message": "Client routed to none (deactivated)"
                }

        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return {
                "success": False,
                "message": f"Routing error: {str(e)}"
            }

    def _is_output_client(self, server_id: str, client_id: str) -> bool:
        """
        Check if client is an output client (hardware snapclient).

        Output clients are hardware snapclients that output to audio devices.
        Non-output clients are browser clients, third-party clients, etc.

        Args:
            server_id: Server ID
            client_id: Local client ID

        Returns:
            True if output client, False otherwise
        """
        # Output clients have MAC address format
        # Browser clients have UUID format
        # This is a simple heuristic - could be improved with server status check
        return self._is_mac_address(client_id)

    async def _route_simple(self, conn, group_id: str, stream_id: str) -> Dict:
        """
        Route client to stream (simple, no lockout logic).

        Args:
            conn: WebSocket connection to server
            group_id: Group ID
            stream_id: Stream ID

        Returns:
            Dict with success status
        """
        await conn.send_request("Group.SetStream", {
            "id": group_id,
            "stream_id": stream_id
        })
        # Refresh status after routing (important for servers that don't send events)
        await conn.get_status()
        logger.info(f"Routed group {group_id} to stream {stream_id}")

        return {
            "success": True,
            "message": f"Routed to stream {stream_id}"
        }

    async def _find_active_endpoint(self) -> Dict:
        """
        Find the currently active endpoint across ALL servers in the federation.

        Queries all servers to find output clients NOT on none streams.
        Returns the first active endpoint found.

        Returns:
            Dict with active/serverId/clientId/streamId or active=False
        """
        # Get all connected servers
        all_servers = self.ws_manager.get_all_connections()

        for conn in all_servers:
            if not conn.connected:
                continue

            try:
                # Get server status
                status = await conn.get_status()

                # Find all output clients NOT on none streams
                for group in status.get("server", {}).get("groups", []):
                    group_stream_id = group.get("stream_id", "")

                    # Skip if group is on a none stream
                    if "none-" in group_stream_id:
                        continue

                    # Check each client in this group
                    for client in group.get("clients", []):
                        client_id = client.get("id")

                        # Check if this is an output client (MAC address or remote snapclient)
                        is_output = (self._is_mac_address(client_id) or
                                   client_id.startswith("remote-"))

                        if is_output:
                            # Found an active output client!
                            logger.debug(f"Active endpoint found: {conn.server_id}/{client_id} on {group_stream_id}")
                            return {
                                "active": True,
                                "serverId": conn.server_id,
                                "clientId": client_id,
                                "streamId": group_stream_id
                            }

            except Exception as e:
                logger.error(f"Error finding active endpoint on {conn.server_id}: {e}")

        # No active endpoint found
        return {"active": False}

    async def _deactivate_all_endpoints(self):
        """
        Deactivate ALL active endpoints across ALL servers in the federation.

        This queries all servers to find output clients NOT on none streams
        and routes them all to none. Ensures true endpoint lockout across federation.
        """
        logger.info("Deactivating all active endpoints across all servers")

        # Get all connected servers
        all_servers = self.ws_manager.get_all_connections()

        for conn in all_servers:
            if not conn.connected:
                continue

            try:
                # Get server status
                status = await conn.get_status()

                # Find all output clients NOT on none streams
                for group in status.get("server", {}).get("groups", []):
                    group_stream_id = group.get("stream_id", "")

                    # Skip if group is already on a none stream
                    if "none-" in group_stream_id:
                        continue

                    # Check each client in this group
                    for client in group.get("clients", []):
                        client_id = client.get("id")

                        # Check if this is an output client (MAC address or remote snapclient)
                        is_output = (self._is_mac_address(client_id) or
                                   client_id.startswith("remote-"))

                        if is_output:
                            # Route this output client to none
                            logger.info(f"Deactivating output client: {conn.server_id}/{client_id} (was on {group_stream_id})")
                            await self._route_to_none(conn.server_id, client_id)

            except Exception as e:
                logger.error(f"Error deactivating endpoints on {conn.server_id}: {e}")

        # Clear local active endpoint tracking
        self.active_endpoint = None
        logger.info("All endpoints deactivated")

    async def _route_to_none(self, server_id: str, client_id: str):
        """
        Route client to 'none' stream (silence).

        Args:
            server_id: Server ID
            client_id: Local client ID
        """
        # Get connection
        conn = self.ws_manager.get_connection(server_id)
        if not conn or not conn.connected:
            logger.warning(f"Cannot route to none: server {server_id} not connected")
            return

        # Get server status to find client's group
        status = await conn.get_status()

        # Find client's group
        client_group_id = None
        for group in status.get("server", {}).get("groups", []):
            for client in group.get("clients", []):
                if client.get("id") == client_id:
                    client_group_id = group.get("id")
                    break
            if client_group_id:
                break

        if not client_group_id:
            logger.warning(f"Client {client_id} not found on server {server_id}")
            return

        # Find 'none' stream ID for this server
        none_stream_id = self._get_none_stream_id(status)

        if not none_stream_id:
            logger.warning(f"No 'none' stream found on server {server_id}")
            return

        # Route to none stream
        await conn.send_request("Group.SetStream", {
            "id": client_group_id,
            "stream_id": none_stream_id
        })

        logger.info(f"Routed {client_id} to none stream (silent)")

    async def _find_local_output_client(self, server_status: Dict) -> Optional[Dict]:
        """
        Find the local output client (hardware snapclient) on a server.

        This finds the client with MAC address format that is NOT a remote snapclient.

        Args:
            server_status: Server status dict

        Returns:
            Dict with client info (id, group_id) or None if not found
        """
        for group in server_status.get("server", {}).get("groups", []):
            for client in group.get("clients", []):
                client_id = client.get("id")

                # Check if this is a MAC address (output client)
                if self._is_mac_address(client_id):
                    # Exclude remote snapclients (they also have MAC addresses)
                    # Remote snapclients have hostnames like "remote-server-..."
                    hostname = client.get("host", {}).get("name", "")
                    if not hostname.startswith("remote-"):
                        # Found local output client!
                        return {
                            "id": client_id,
                            "group_id": group.get("id")
                        }

        return None

    def _get_none_stream_id(self, server_status: Dict) -> Optional[str]:
        """
        Find the 'none' stream ID on a server.

        Args:
            server_status: Server status dict

        Returns:
            None stream ID or None if not found
        """
        for stream in server_status.get("server", {}).get("streams", []):
            stream_id = stream.get("id", "")
            # None streams are named "none-*" (e.g., "none-hostname")
            if stream_id.startswith("none-"):
                return stream_id

        return None


    def _is_mac_address(self, client_id: str) -> bool:
        """Check if client_id is a MAC address format (hardware client)"""
        import re
        mac_pattern = r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$'
        return bool(re.match(mac_pattern, client_id))

    async def set_client_volume(self, client_id: str, volume: int, muted: bool = False) -> Dict:
        """Set volume for a client"""
        try:
            # Parse client ID
            server_id, local_client_id = self.parse_federated_id(client_id)

            # Get connection
            conn = self.ws_manager.get_connection(server_id)
            if not conn or not conn.connected:
                return {
                    "success": False,
                    "message": f"Server not connected: {server_id}"
                }

            # Set volume
            await conn.send_request("Client.SetVolume", {
                "id": local_client_id,
                "volume": {
                    "percent": volume,
                    "muted": muted
                }
            })

            # Refresh status after volume change (important for servers that don't send events)
            await conn.get_status()

            return {
                "success": True,
                "message": f"Volume set to {volume}%"
            }

        except Exception as e:
            logger.error(f"Set volume failed: {e}")
            return {
                "success": False,
                "message": f"Volume control error: {str(e)}"
            }

    async def control_stream(self, stream_id: str, command: str) -> Dict:
        """Send control command to a stream"""
        try:
            # Parse stream ID
            server_id, local_stream_id = self.parse_federated_id(stream_id)

            # Get connection
            conn = self.ws_manager.get_connection(server_id)
            if not conn or not conn.connected:
                return {
                    "success": False,
                    "message": f"Server not connected: {server_id}"
                }

            # Send control command
            await conn.send_request("Stream.Control", {
                "id": local_stream_id,
                "command": command
            })

            # Refresh status after control command (important for servers that don't send events)
            await conn.get_status()

            return {
                "success": True,
                "message": f"Stream control: {command}"
            }

        except Exception as e:
            logger.error(f"Stream control failed: {e}")
            return {
                "success": False,
                "message": f"Stream control error: {str(e)}"
            }
