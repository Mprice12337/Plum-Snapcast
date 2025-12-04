#!/usr/bin/env python3
"""
Multi-Server WebSocket Manager
Manages concurrent WebSocket connections to multiple Snapcast servers
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable, Any
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class SnapcastConnection:
    """Represents a WebSocket connection to a single Snapcast server"""

    def __init__(self, server_id: str, host: str, port: int, name: str, use_https: bool = False):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.name = name
        self.use_https = use_https
        self.ws = None
        self.connected = False
        self.last_status = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 1  # Start with 1 second
        self.max_reconnect_delay = 60  # Max 60 seconds
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._event_callbacks: List[Callable] = []
        self._requests_sent = 0
        self._responses_received = 0
        self._connection_per_request = False  # Workaround for buggy servers

    @property
    def url(self) -> str:
        protocol = "wss" if self.use_https else "ws"
        return f"{protocol}://{self.host}:{self.port}/jsonrpc"

    def add_event_callback(self, callback: Callable):
        """Add callback for server events"""
        self._event_callbacks.append(callback)

    async def connect(self):
        """Establish WebSocket connection"""
        try:
            logger.info(f"Connecting to {self.name} at {self.url}")
            self.ws = await websockets.connect(
                self.url,
                ping_interval=20,
                ping_timeout=10
            )
            self.connected = True
            self.reconnect_attempts = 0
            self.reconnect_delay = 1
            logger.info(f"Connected to {self.name}")

            # Start listener task
            asyncio.create_task(self._message_listener())

            # Get initial status
            await self.get_status()

            # Enable one-shot mode immediately for Music Assistant servers (known bug)
            # MA responds to first request but stops responding to subsequent requests
            if "music" in self.name.lower() or "ma" in self.name.lower():
                logger.info(f"[{self.name}] Enabling one-shot mode (Music Assistant compatibility)")
                self._connection_per_request = True

        except Exception as e:
            logger.error(f"Failed to connect to {self.name}: {e}")
            self.connected = False
            raise

    async def disconnect(self):
        """Close WebSocket connection"""
        if self.ws:
            await self.ws.close()
            self.ws = None
        self.connected = False
        logger.info(f"Disconnected from {self.name}")

    async def reconnect(self):
        """Attempt to reconnect with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts reached for {self.name}")
            return False

        self.reconnect_attempts += 1
        delay = min(self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), self.max_reconnect_delay)

        logger.info(f"Reconnecting to {self.name} in {delay}s (attempt {self.reconnect_attempts})")
        await asyncio.sleep(delay)

        try:
            await self.connect()
            return True
        except Exception as e:
            logger.error(f"Reconnection failed for {self.name}: {e}")
            return False

    async def _message_listener(self):
        """Listen for messages from server"""
        logger.debug(f"Message listener started for {self.name}")
        try:
            logger.debug(f"[{self.name}] Starting message receive loop...")
            while True:
                try:
                    logger.debug(f"[{self.name}] Waiting for next message...")
                    message = await self.ws.recv()
                    logger.debug(f"[{self.name}] Received message!")

                    try:
                        logger.debug(f"Received message from {self.name}: {message[:200]}...")
                        data = json.loads(message)

                        # Handle JSON-RPC responses
                        if "id" in data:
                            request_id = data["id"]
                            logger.debug(f"Processing response for request ID {request_id} from {self.name}")
                            if request_id in self._pending_requests:
                                future = self._pending_requests.pop(request_id)
                                if "error" in data:
                                    logger.debug(f"Response has error: {data['error']}")
                                    future.set_exception(Exception(data["error"]))
                                else:
                                    logger.debug(f"Response successful, setting result")
                                    future.set_result(data.get("result"))
                            else:
                                logger.warning(f"Received response for unknown request ID {request_id} from {self.name}")

                        # Handle notifications (events)
                        elif "method" in data:
                            logger.debug(f"[{self.name}] Received notification: {data.get('method')}")
                            await self._handle_notification(data)

                        logger.debug(f"[{self.name}] Finished processing message, looping back...")

                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON from {self.name}: {e}")
                    except Exception as e:
                        logger.error(f"Error processing message from {self.name}: {e}", exc_info=True)

                except ConnectionClosed:
                    logger.warning(f"Connection closed to {self.name}")
                    self.connected = False
                    # Attempt reconnection
                    asyncio.create_task(self.reconnect())
                    break
                except Exception as e:
                    logger.error(f"Error receiving message from {self.name}: {e}", exc_info=True)
                    await asyncio.sleep(0.1)  # Brief pause before retry

        except Exception as e:
            logger.error(f"Message listener error for {self.name}: {e}", exc_info=True)
            self.connected = False

        logger.error(f"[{self.name}] Message listener has EXITED - this should not happen!")

    async def _handle_notification(self, data: Dict):
        """Handle server notification/event"""
        method = data.get("method")
        params = data.get("params", {})

        logger.debug(f"Event from {self.name}: {method}")

        # Update cached status on events
        if method in ["Client.OnVolumeChanged", "Client.OnConnect", "Client.OnDisconnect",
                      "Stream.OnUpdate", "Group.OnStreamChanged", "Server.OnUpdate"]:
            # Refresh status after event
            asyncio.create_task(self.get_status())

        # Notify callbacks
        for callback in self._event_callbacks:
            try:
                await callback(self.server_id, method, params)
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    async def _send_oneshot_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """Send a single request with its own connection (workaround for buggy servers)"""
        logger.debug(f"[{self.name}] Creating one-shot connection for {method}")

        ws = None
        try:
            # Create temporary connection
            ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=10)

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params or {}
            }

            # Send request
            await ws.send(json.dumps(request))
            logger.debug(f"[{self.name}] One-shot request sent, waiting for response...")

            # Wait for response
            response_str = await asyncio.wait_for(ws.recv(), timeout=10)
            response = json.loads(response_str)

            if "error" in response:
                raise Exception(response["error"])

            logger.debug(f"[{self.name}] One-shot request completed successfully")
            return response.get("result")

        finally:
            if ws:
                await ws.close()

    async def send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """Send JSON-RPC request and wait for response"""
        # Use one-shot mode if enabled (workaround for buggy servers)
        if self._connection_per_request:
            logger.info(f"[{self.name}] Using one-shot request mode (server bug workaround)")
            return await self._send_oneshot_request(method, params)

        if not self.connected or not self.ws:
            raise Exception(f"Not connected to {self.name}")

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        }

        # Create future for response
        future = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            logger.debug(f"Sending request ID {request_id} to {self.name}: {method}")
            await self.ws.send(json.dumps(request))
            self._requests_sent += 1
            logger.debug(f"Request ID {request_id} sent, waiting for response (timeout=30s)...")
            # Wait for response with timeout (30s for cross-network operations)
            result = await asyncio.wait_for(future, timeout=30)
            self._responses_received += 1
            logger.debug(f"Request ID {request_id} completed successfully")
            return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)

            # Detect buggy servers that stop responding after first request
            if self._requests_sent > 1 and self._responses_received == 1 and not self._connection_per_request:
                logger.warning(f"[{self.name}] Server stopped responding after first request - enabling one-shot mode")
                self._connection_per_request = True

            logger.error(f"Request ID {request_id} timed out after 30s to {self.name}: {method}")
            raise Exception(f"Request timeout to {self.name}: {method}")
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            raise

    async def get_status(self) -> Dict:
        """Get server status"""
        result = await self.send_request("Server.GetStatus")
        self.last_status = result
        return result


class WebSocketManager:
    """Manages connections to multiple Snapcast servers"""

    def __init__(self):
        self.connections: Dict[str, SnapcastConnection] = {}
        self._event_callbacks: List[Callable] = []

    def add_event_callback(self, callback: Callable):
        """Add global event callback"""
        self._event_callbacks.append(callback)

    async def add_server(self, server_id: str, host: str, port: int, name: str, use_https: bool = False):
        """Add and connect to a server"""
        if server_id in self.connections:
            logger.warning(f"Server {server_id} already exists")
            return

        conn = SnapcastConnection(server_id, host, port, name, use_https)

        # Add event callback
        conn.add_event_callback(self._on_server_event)

        try:
            await conn.connect()
            self.connections[server_id] = conn
            logger.info(f"Added server: {name} ({server_id})")
        except Exception as e:
            logger.error(f"Failed to add server {name}: {e}")
            raise

    async def remove_server(self, server_id: str):
        """Remove and disconnect from a server"""
        if server_id not in self.connections:
            return

        conn = self.connections.pop(server_id)
        await conn.disconnect()
        logger.info(f"Removed server: {conn.name} ({server_id})")

    async def _on_server_event(self, server_id: str, method: str, params: Dict):
        """Handle events from any server"""
        for callback in self._event_callbacks:
            try:
                await callback(server_id, method, params)
            except Exception as e:
                logger.error(f"Global event callback error: {e}")

    def get_connection(self, server_id: str) -> Optional[SnapcastConnection]:
        """Get connection by server ID"""
        return self.connections.get(server_id)

    def get_all_connections(self) -> List[SnapcastConnection]:
        """Get all connections"""
        return list(self.connections.values())

    def get_connected_servers(self) -> List[str]:
        """Get list of connected server IDs"""
        return [sid for sid, conn in self.connections.items() if conn.connected]

    async def send_request(self, server_id: str, method: str, params: Optional[Dict] = None) -> Any:
        """Send request to specific server"""
        conn = self.get_connection(server_id)
        if not conn:
            raise Exception(f"Server not found: {server_id}")

        return await conn.send_request(method, params)

    async def get_all_statuses(self) -> Dict[str, Dict]:
        """Get status from all connected servers"""
        statuses = {}

        for server_id, conn in self.connections.items():
            if conn.connected:
                try:
                    status = await conn.get_status()
                    statuses[server_id] = status
                except Exception as e:
                    logger.error(f"Failed to get status from {conn.name}: {e}")

        return statuses

    async def close_all(self):
        """Close all connections"""
        for conn in self.connections.values():
            await conn.disconnect()
        self.connections.clear()
        logger.info("All connections closed")


# For testing
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    async def test():
        manager = WebSocketManager()

        # Add local server (adjust host/port as needed)
        try:
            await manager.add_server(
                server_id="server-local",
                host="localhost",
                port=1780,
                name="Local Server",
                use_https=False
            )

            # Get status
            statuses = await manager.get_all_statuses()
            print(json.dumps(statuses, indent=2))

            # Wait for events
            await asyncio.sleep(10)

        except Exception as e:
            logger.error(f"Test failed: {e}")
        finally:
            await manager.close_all()

    asyncio.run(test())
