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
    Manages cross-server client routing

    When a client needs to connect to a stream on a different server:
    1. Identify target server for the stream
    2. Reconfigure snapclient to connect to target server
    3. Wait for client to appear on target server
    4. Assign client to requested stream
    """

    def __init__(self, ws_manager, local_server_id: str):
        self.ws_manager = ws_manager
        self.local_server_id = local_server_id

    def parse_federated_id(self, federated_id: str) -> Tuple[str, str]:
        """
        Parse federated ID into server_id and local_id
        Format: "server-id-stream-name" or "server-id-client-name"
        Example: "server-192-168-7-122-airplay1" -> ("server-192-168-7-122", "airplay1")
        """
        parts = federated_id.split("-", 3)  # Split into at most 4 parts
        if len(parts) >= 4:
            server_part = "-".join(parts[:4])  # "server-192-168-7-122"
            local_part = parts[4] if len(parts) > 4 else ""  # Everything after
            return server_part, local_part
        return federated_id, ""

    async def route_client(self, client_id: str, stream_id: str) -> Dict:
        """
        Route a client to a stream

        Args:
            client_id: Federated client ID (e.g., "server-192-168-7-122-living-room")
            stream_id: Federated stream ID (e.g., "server-192-168-7-226-ma-stream")

        Returns:
            Dict with success status and message
        """
        try:
            # Parse IDs
            client_server_id, client_local_id = self.parse_federated_id(client_id)
            stream_server_id, stream_local_id = self.parse_federated_id(stream_id)

            # Get connections
            client_conn = self.ws_manager.get_connection(client_server_id)
            stream_conn = self.ws_manager.get_connection(stream_server_id)

            if not client_conn or not client_conn.connected:
                return {
                    "success": False,
                    "message": f"Client server not connected: {client_server_id}"
                }

            if not stream_conn or not stream_conn.connected:
                return {
                    "success": False,
                    "message": f"Stream server not connected: {stream_server_id}"
                }

            # Find the client and stream in server status
            client_status = await client_conn.get_status()
            stream_status = await stream_conn.get_status()

            # Find the actual client
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

            # Find the actual stream
            actual_stream = None
            for stream in stream_status.get("server", {}).get("streams", []):
                if stream.get("id") == stream_local_id:
                    actual_stream = stream
                    break

            if not actual_stream:
                return {
                    "success": False,
                    "message": f"Stream not found: {stream_local_id}"
                }

            # Check if cross-server routing is needed
            if client_server_id == stream_server_id:
                # Same server - simple group stream change
                await self._route_same_server(
                    client_conn,
                    client_group_id,
                    stream_local_id
                )
                return {
                    "success": True,
                    "message": f"Client routed to stream on same server"
                }
            else:
                # Cross-server routing - reconfigure snapclient
                result = await self._route_cross_server(
                    client_server_id,
                    client_local_id,
                    stream_server_id,
                    stream_local_id,
                    stream_conn
                )
                return result

        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return {
                "success": False,
                "message": f"Routing error: {str(e)}"
            }

    async def _route_same_server(self, conn, group_id: str, stream_id: str):
        """Route client to stream on the same server"""
        await conn.send_request("Group.SetStream", {
            "id": group_id,
            "stream_id": stream_id
        })
        logger.info(f"Routed group {group_id} to stream {stream_id}")

    async def _route_cross_server(
        self,
        client_server_id: str,
        client_id: str,
        stream_server_id: str,
        stream_id: str,
        stream_conn
    ) -> Dict:
        """
        Route client to stream on a different server

        This requires reconfiguring the snapclient to connect to the target server.
        Currently only supports local snapclient (running in same container).
        """
        # Check if this is the local server's snapclient
        if client_server_id != self.local_server_id:
            return {
                "success": False,
                "message": "Cross-server routing only supported for local snapclient"
            }

        try:
            # Get target server connection info
            target_host = stream_conn.host
            target_port = 1704  # Snapclient connection port

            logger.info(f"Reconfiguring local snapclient to connect to {target_host}:{target_port}")

            # Update snapclient configuration
            # This requires modifying supervisord config and restarting snapclient
            # For now, we'll use environment variable and restart via supervisord

            # Set environment variable for snapclient host
            os.environ["SNAPCLIENT_HOST"] = target_host

            # Restart snapclient via supervisord
            result = subprocess.run(
                ["supervisorctl", "-c", "/app/supervisord/supervisord.conf", "restart", "snapclient"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                logger.error(f"Failed to restart snapclient: {result.stderr}")
                return {
                    "success": False,
                    "message": f"Failed to restart snapclient: {result.stderr}"
                }

            logger.info("Snapclient restarted successfully")

            # Wait a moment for client to reconnect
            import asyncio
            await asyncio.sleep(2)

            # Now route to the stream on the new server
            # Get updated status to find the group the client is in
            target_status = await stream_conn.get_status()

            # Find the group containing our client
            target_group_id = None
            for group in target_status.get("server", {}).get("groups", []):
                for client in group.get("clients", []):
                    # Match by MAC address or hostname
                    if client.get("id") == client_id or client.get("host", {}).get("name") == client_id:
                        target_group_id = group.get("id")
                        break
                if target_group_id:
                    break

            if target_group_id:
                # Route to the requested stream
                await stream_conn.send_request("Group.SetStream", {
                    "id": target_group_id,
                    "stream_id": stream_id
                })

                return {
                    "success": True,
                    "message": f"Client routed to {stream_id} on {stream_conn.name}"
                }
            else:
                return {
                    "success": False,
                    "message": "Client not found on target server after reconnection"
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "Snapclient restart timed out"
            }
        except Exception as e:
            logger.error(f"Cross-server routing failed: {e}")
            return {
                "success": False,
                "message": f"Cross-server routing error: {str(e)}"
            }

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
