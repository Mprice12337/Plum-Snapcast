#!/usr/bin/env python3
"""
Cross-Server Routing Logic
Handles routing clients to streams across different Snapcast servers
"""

import asyncio
import logging
import re
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
            logger.debug(f"Parsed client: server={client_server_id}, local={client_local_id}")
            logger.debug(f"Parsed stream: server={stream_server_id}, local={stream_local_id}")

            # Get connections
            client_conn = self.ws_manager.get_connection(client_server_id)
            if not client_conn or not client_conn.connected:
                return {
                    "success": False,
                    "message": f"Client server not connected: {client_server_id}"
                }

            # Find the client in server status with timeout
            try:
                client_status = await asyncio.wait_for(client_conn.get_status(), timeout=3.0)
            except asyncio.TimeoutError:
                return {
                    "success": False,
                    "message": f"Timeout getting status from client server {client_server_id}"
                }

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

            # Check if routing to none stream first
            # Check if stream_local_id contains "none-" to detect none streams in federation mode
            is_none_stream = not stream_local_id or "none-" in stream_local_id

            if is_none_stream:
                # Route to none (deactivate only this specific client)
                # Don't deactivate all endpoints - only deactivate the client being switched
                logger.info(f"Routing to none: {client_server_id}/{client_local_id}")

                # Route the local client to none on its server
                await self._route_to_none(client_server_id, client_local_id)

                # ALSO: Route ALL other remote snapclients ON this client's server to none
                # This handles the case where remote clients are playing through this server
                logger.debug(f"Looking for remote snapclients on {client_server_id} to deactivate")

                client_conn = self.ws_manager.get_connection(client_server_id)
                if client_conn and client_conn.connected:
                    try:
                        client_status = await asyncio.wait_for(client_conn.get_status(), timeout=2.0)
                        for group in client_status.get("server", {}).get("groups", []):
                            stream_id = group.get("stream_id", "")
                            # Skip if already on none
                            if "none-" in stream_id:
                                continue

                            for client in group.get("clients", []):
                                remote_id = client.get("id", "")
                                # Check if this is a remote snapclient
                                if remote_id.startswith("remote-server-"):
                                    logger.debug(f"Found remote snapclient {remote_id} on {client_server_id}, routing to none")
                                    await self._route_to_none(client_server_id, remote_id)
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout checking for remote snapclients on {client_server_id}")

                # Also find and deactivate any remote snapclient playing for this client
                # Remote snapclient would have ID like "remote-{client_server_id}" on another server
                remote_client_id = f"remote-{client_server_id}"
                remote_server_id = None
                logger.debug(f"Looking for remote snapclient: {remote_client_id}")

                # Check all other servers for this remote snapclient
                for conn in self.ws_manager.get_all_connections():
                    if conn.server_id == client_server_id:
                        # Skip the client's own server
                        continue

                    if not conn.connected:
                        continue

                    try:
                        # Check if this server has our remote snapclient
                        status = await asyncio.wait_for(conn.get_status(), timeout=2.0)

                        # Look for the remote snapclient in this server's clients
                        found_remote = False
                        for group in status.get("server", {}).get("groups", []):
                            for client in group.get("clients", []):
                                if client.get("id") == remote_client_id or client.get("host", {}).get("name") == remote_client_id:
                                    found_remote = True
                                    remote_server_id = conn.server_id
                                    logger.debug(f"Found remote snapclient {remote_client_id} on {conn.server_id}, routing to none")
                                    await self._route_to_none(conn.server_id, remote_client_id)
                                    break
                            if found_remote:
                                break
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout checking for remote snapclient on {conn.server_id}")
                        continue

                # Brief delay to let Snapcast process the routing
                await asyncio.sleep(0.3)

                # Clear active endpoint since we're deactivating
                self.active_endpoint = None

                return {
                    "success": True,
                    "message": "Client routed to none (deactivated)"
                }

            # Deactivate endpoints on OTHER streams (preserves clients already on target stream)
            # This ensures endpoint lockout while allowing multiple clients to listen to the same stream
            await self._deactivate_all_endpoints(except_stream_id=stream_local_id)


            # Step 2: Activate new endpoint
            if stream_id:
                # Verify stream exists
                stream_conn = self.ws_manager.get_connection(stream_server_id)
                if not stream_conn or not stream_conn.connected:
                    return {
                        "success": False,
                        "message": f"Stream server not connected: {stream_server_id}"
                    }

                try:
                    stream_status = await asyncio.wait_for(stream_conn.get_status(), timeout=3.0)
                except asyncio.TimeoutError:
                    return {
                        "success": False,
                        "message": f"Timeout getting status from stream server {stream_server_id}"
                    }
                actual_stream = None
                available_streams = [s.get("id") for s in stream_status.get("server", {}).get("streams", [])]

                for stream in stream_status.get("server", {}).get("streams", []):
                    if stream.get("id") == stream_local_id:
                        actual_stream = stream
                        break

                if not actual_stream:
                    logger.error(f"Stream {stream_local_id} not found. Available: {available_streams}")
                    return {
                        "success": False,
                        "message": f"Stream not found: {stream_local_id}"
                    }

                # Check if this is cross-server routing (client and stream on different servers)
                if client_server_id != stream_server_id:
                    logger.debug(f"Cross-server routing: {client_server_id} -> {stream_server_id}")

                    # Determine if client is local or remote
                    client_is_local = (client_server_id == self.local_server_id)
                    stream_is_local = (stream_server_id == self.local_server_id)

                    if client_is_local and not stream_is_local:
                        # Case 1: Local client, remote stream
                        # Route our local client to none, then use our remote snapclient

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
                        # It will have ID like "remote-{client_server_id}" and appears on our local server
                        expected_remote_client_id = f"remote-{client_server_id}"

                        # Get our local server status to find this remote snapclient
                        try:
                            local_status = await asyncio.wait_for(stream_conn.get_status(), timeout=3.0)
                        except asyncio.TimeoutError:
                            return {
                                "success": False,
                                "message": f"Timeout getting local server status"
                            }
                        remote_client_group_id = None

                        for group in local_status.get("server", {}).get("groups", []):
                            for client in group.get("clients", []):
                                # Check both client ID and hostname (snapclient uses hostID as hostname)
                                if (client.get("id") == expected_remote_client_id or
                                    client.get("host", {}).get("name") == expected_remote_client_id):
                                    remote_client_group_id = group.get("id")
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

                        # Update active endpoint tracking (use federated stream ID format)
                        self.active_endpoint = (client_server_id, client_local_id, f"{self.local_server_id}-{stream_local_id}")
                        logger.info(f"Routed remote client to local stream: {stream_local_id}")

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

                    # Find the remote client's group on the stream server
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

                    # Route the remote client to the desired stream
                    await self._route_simple(stream_conn, remote_group_id, stream_local_id)

                    # Update active endpoint tracking (use federated stream ID format)
                    self.active_endpoint = (client_server_id, client_local_id, f"{stream_server_id}-{stream_local_id}")
                    logger.info(f"Routed local client to remote stream: {stream_local_id}")
                else:
                    # Same-server routing: route directly
                    await self._route_simple(client_conn, client_group_id, stream_local_id)

                    # Update active endpoint tracking (use federated stream ID format for consistency)
                    self.active_endpoint = (client_server_id, client_local_id, f"{client_server_id}-{stream_local_id}")
                    logger.info(f"Routed to stream: {stream_local_id}")

                return {
                    "success": True,
                    "message": f"Client routed to stream with lockout"
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
        try:
            await asyncio.wait_for(conn.get_status(), timeout=2.0)
        except asyncio.TimeoutError:
            pass  # Timeout refreshing status, continue anyway

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
                # Get server status with timeout to prevent hanging
                status = await asyncio.wait_for(conn.get_status(), timeout=2.0)

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

            except asyncio.TimeoutError:
                logger.warning(f"Timeout querying {conn.server_id} for active endpoint, skipping")
                continue
            except Exception as e:
                logger.error(f"Error finding active endpoint on {conn.server_id}: {e}")
                continue

        # No active endpoint found
        return {"active": False}

    async def _deactivate_all_endpoints(self, except_stream_id: Optional[str] = None):
        """
        Deactivate active endpoints across servers in the federation.

        This queries all servers to find output clients NOT on none streams
        and routes them to none. Ensures endpoint lockout across federation.

        Args:
            except_stream_id: Optional local stream ID to exclude from deactivation.
                              Clients already on this stream will NOT be deactivated.
                              This allows multiple clients to listen to the same stream.
        """
        if except_stream_id:
            logger.debug(f"Deactivating endpoints EXCEPT those on stream: {except_stream_id}")
        else:
            logger.debug("Deactivating all active endpoints")

        # Get all connected servers
        all_servers = self.ws_manager.get_all_connections()

        for conn in all_servers:
            if not conn.connected:
                continue

            try:
                # Get server status with timeout to prevent hanging
                status = await asyncio.wait_for(conn.get_status(), timeout=2.0)

                # Find all output clients NOT on none streams
                for group in status.get("server", {}).get("groups", []):
                    group_stream_id = group.get("stream_id", "")

                    # Skip if group is already on a none stream
                    if "none-" in group_stream_id:
                        continue

                    # Skip if group is on the target stream (don't deactivate clients already listening)
                    if except_stream_id and group_stream_id == except_stream_id:
                        logger.debug(f"Keeping clients on target stream {group_stream_id} active")
                        continue

                    # Check each client in this group
                    for client in group.get("clients", []):
                        client_id = client.get("id")

                        # Check if this is an output client (MAC address or remote snapclient)
                        is_output = (self._is_mac_address(client_id) or
                                   client_id.startswith("remote-"))

                        if is_output:
                            await self._route_to_none(conn.server_id, client_id)

            except asyncio.TimeoutError:
                logger.warning(f"Timeout querying {conn.server_id} for deactivation, skipping")
                continue
            except Exception as e:
                logger.error(f"Error deactivating endpoints on {conn.server_id}: {e}")
                continue

        # Clear local active endpoint tracking
        self.active_endpoint = None

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

        try:
            # Get server status to find client's group with timeout
            status = await asyncio.wait_for(conn.get_status(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout getting status from {server_id} for route to none")
            return

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

        # Refresh status after routing (important for servers that don't send events)
        try:
            await asyncio.wait_for(conn.get_status(), timeout=2.0)
        except asyncio.TimeoutError:
            pass  # Timeout refreshing status, continue anyway

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
                hostname = client.get("host", {}).get("name", "")

                # Check if this is a MAC address (output client)
                if self._is_mac_address(client_id):
                    # Exclude remote snapclients (they have hostnames like "remote-server-...")
                    if not hostname.startswith("remote-"):
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
            try:
                await asyncio.wait_for(conn.get_status(), timeout=2.0)
            except asyncio.TimeoutError:
                pass  # Timeout refreshing status, continue anyway

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
            try:
                await asyncio.wait_for(conn.get_status(), timeout=2.0)
            except asyncio.TimeoutError:
                pass  # Timeout refreshing status, continue anyway

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

    async def set_stream_volume(self, stream_id: str, volume: int) -> Dict:
        """Set source volume for a stream (controls the integration like AirPlay/Spotify)"""
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

            # Clamp volume to valid range
            clamped_volume = max(0, min(100, volume))

            # Send setVolume command with volume in params
            await conn.send_request("Stream.Control", {
                "id": local_stream_id,
                "command": "setVolume",
                "params": {"volume": clamped_volume}
            })

            # Refresh status after volume change
            try:
                await asyncio.wait_for(conn.get_status(), timeout=2.0)
            except asyncio.TimeoutError:
                pass  # Timeout refreshing status, continue anyway

            return {
                "success": True,
                "message": f"Stream volume set to {clamped_volume}%"
            }

        except Exception as e:
            logger.error(f"Set stream volume failed: {e}")
            return {
                "success": False,
                "message": f"Stream volume error: {str(e)}"
            }
