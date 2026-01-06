#!/usr/bin/env python3
"""
Main Federation Service
Orchestrates discovery, WebSocket connections, routing, and API server
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from typing import Dict, List

from .discovery import AvahiDiscovery, ServerInfo
from .websocket_manager import WebSocketManager
from .router import FederationRouter
from .api import FederationAPI, DataAggregator
from .remote_snapclient_manager import RemoteSnapclientManager

logger = logging.getLogger(__name__)


class FederationService:
    """
    Main Federation Service
    Coordinates all federation components
    """

    def __init__(self, config: Dict):
        self.config = config
        self.running = False

        # Get configuration
        self.local_server_name = config.get("local_name", "Plum Snapcast")
        self.auto_discover = config.get("auto_discover", True)
        self.manual_servers = config.get("manual_servers", [])
        self.api_port = config.get("api_port", 5000)
        self.local_server_id = self._generate_server_id(config.get("local_host", "localhost"))

        # Initialize components
        self.discovery = None
        self.ws_manager = None
        self.router = None
        self.data_aggregator = None
        self.api = None
        self.remote_snapclient_manager = None

        # Async loop
        self.loop = None

        # Settings monitoring
        self.settings_file = "/app/data/settings.json"
        self.settings_mtime = None
        self.settings_check_interval = 1  # Check every 1 second

    def _generate_server_id(self, host: str) -> str:
        """Generate server ID from host"""
        return f"server-{host.replace('.', '-')}"

    def _check_settings_changes(self):
        """Monitor settings.json for changes and apply them"""
        if not os.path.exists(self.settings_file):
            return

        try:
            # Check if file was modified
            current_mtime = os.path.getmtime(self.settings_file)
            if self.settings_mtime is None:
                self.settings_mtime = current_mtime
                return

            if current_mtime == self.settings_mtime:
                return  # No changes

            logger.info("Settings file changed, reloading configuration")
            self.settings_mtime = current_mtime

            # Load new settings
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                federation_settings = settings.get("federation", {})

            # Check if federation was disabled (requires restart to switch to minimal mode)
            new_enabled = federation_settings.get("enabled", False)
            if not new_enabled:
                logger.warning("Federation disabled via settings - restarting service in minimal mode")
                logger.warning("Service will restart automatically via supervisord")
                self.stop()
                sys.exit(0)

            # Check for auto-discover changes
            new_auto_discover = federation_settings.get("autoDiscover", True)
            if new_auto_discover != self.auto_discover:
                logger.info(f"Auto-discover changed: {self.auto_discover} -> {new_auto_discover}")
                self.auto_discover = new_auto_discover

                if self.auto_discover:
                    # Start discovery
                    if self.discovery and not hasattr(self.discovery, 'running'):
                        logger.info("Starting auto-discovery")
                        self.discovery.start()
                    elif self.discovery and not self.discovery.running:
                        logger.info("Starting auto-discovery")
                        self.discovery.start()
                else:
                    # Stop discovery
                    if self.discovery and hasattr(self.discovery, 'running') and self.discovery.running:
                        logger.info("Stopping auto-discovery")
                        self.discovery.stop()

            # Check for device name changes (used as local server name)
            new_local_name = settings.get("deviceName", "Plum Snapcast")
            if new_local_name != self.local_server_name:
                logger.info(f"Local server name changed: {self.local_server_name} -> {new_local_name}")
                self.local_server_name = new_local_name
                # Update the local server connection name
                if self.ws_manager:
                    conn = self.ws_manager.get_connection(self.local_server_id)
                    if conn:
                        conn.name = new_local_name
                        logger.info(f"Updated local server connection name to: {new_local_name}")

        except Exception as e:
            logger.error(f"Failed to check settings changes: {e}")

    def _settings_monitor_loop(self):
        """Background thread to monitor settings changes"""
        logger.info("Settings monitor started")
        while self.running:
            try:
                self._check_settings_changes()
            except Exception as e:
                logger.error(f"Settings monitor error: {e}")
            time.sleep(self.settings_check_interval)
        logger.info("Settings monitor stopped")

    async def _on_servers_discovered(self, servers: List[ServerInfo]):
        """Handle newly discovered servers"""
        logger.info(f"Discovered {len(servers)} servers")

        for server in servers:
            # Skip if already connected
            if self.ws_manager.get_connection(server.id):
                continue

            # Skip local server (we don't connect to ourselves)
            if server.id == self.local_server_id:
                logger.info(f"Skipping local server: {server.name}")
                continue

            # Get actual server name from federation API (not Avahi service name)
            actual_name = server.name
            try:
                import urllib.request
                import json

                # Run blocking urllib call in thread pool
                def fetch_name():
                    info_url = f"http://{server.host}:5001/api/federation/info"
                    with urllib.request.urlopen(info_url, timeout=2) as response:
                        if response.status == 200:
                            return json.loads(response.read().decode()).get("name")
                    return None

                fetched_name = await asyncio.to_thread(fetch_name)
                if fetched_name:
                    actual_name = fetched_name
                    logger.info(f"Got server name from API: {actual_name} (was: {server.name})")
            except Exception as e:
                logger.debug(f"Could not fetch server name from API, using Avahi name: {e}")

            # Connect to new server
            try:
                await self.ws_manager.add_server(
                    server_id=server.id,
                    host=server.host,
                    port=server.port,
                    name=actual_name,
                    use_https=False
                )
            except Exception as e:
                logger.error(f"Failed to connect to {actual_name}: {e}")

    def _on_server_added(self, server: ServerInfo):
        """Handle new server discovered (callback from discovery)"""
        # Skip local server (don't create snapclient to ourselves)
        if server.id == self.local_server_id:
            logger.info(f"Skipping local server for remote snapclient: {server.name}")
            return

        logger.info(f"Server added, spawning remote snapclient: {server.name} ({server.id})")

        # Spawn remote snapclient for this server
        if self.remote_snapclient_manager:
            try:
                self.remote_snapclient_manager.add_remote_server(
                    server_id=server.id,
                    host=server.host,
                    port=1705  # Snapclient port (same as local)
                )

                # Schedule async task to discover client ID
                if self.loop:
                    asyncio.run_coroutine_threadsafe(
                        self._discover_remote_client_id(server.id, server.host),
                        self.loop
                    )
            except Exception as e:
                logger.error(f"Failed to spawn remote snapclient for {server.id}: {e}")

    async def _discover_remote_client_id(self, server_id: str, host: str):
        """Discover the client ID of our remote snapclient on a server"""
        try:
            # Wait a bit for client to connect
            await asyncio.sleep(3)

            # Get connection to remote server
            conn = self.ws_manager.get_connection(server_id)
            if not conn or not conn.connected:
                logger.warning(f"Cannot discover client ID: server {server_id} not connected")
                return

            # Get server status
            status = await conn.get_status()

            # Find client with client ID matching our remote snapclient
            # We use --hostID which sets the client ID to "remote-<server-id>"
            expected_client_id = f"remote-{server_id}"
            remote_client_id = None

            for group in status.get("server", {}).get("groups", []):
                for client in group.get("clients", []):
                    client_id = client.get("id", "")

                    # Check if this client's ID matches our expected pattern
                    if client_id == expected_client_id:
                        remote_client_id = client_id
                        logger.info(f"Found remote client by client ID: {remote_client_id}")
                        break

                if remote_client_id:
                    break

            if remote_client_id:
                self.remote_snapclient_manager.set_client_id(server_id, remote_client_id)
                logger.info(f"Discovered remote client ID for {server_id}: {remote_client_id}")
            else:
                logger.warning(f"Could not find remote client ID for {server_id} with expected client ID {expected_client_id}")

        except Exception as e:
            logger.error(f"Failed to discover client ID for {server_id}: {e}")

    def _on_server_removed(self, server: ServerInfo):
        """Handle server removed (callback from discovery)"""
        # Skip local server
        if server.id == self.local_server_id:
            return

        logger.info(f"Server removed, terminating remote snapclient: {server.name} ({server.id})")

        # Remove remote snapclient for this server
        if self.remote_snapclient_manager:
            try:
                self.remote_snapclient_manager.remove_remote_server(server.id)
            except Exception as e:
                logger.error(f"Failed to remove remote snapclient for {server.id}: {e}")

    async def _on_server_event(self, server_id: str, method: str, params: Dict):
        """Handle events from servers"""
        logger.debug(f"Event from {server_id}: {method}")
        # Events automatically trigger status refresh in WebSocket manager

    async def start_async_components(self):
        """Start all async components"""
        logger.info("Starting Federation Service async components")

        # Initialize WebSocket manager
        self.ws_manager = WebSocketManager()
        self.ws_manager.add_event_callback(self._on_server_event)

        # Initialize remote snapclient manager (load audio settings)
        audio_device = self.config.get("audio_device", "hw:Headphones")
        latency = self.config.get("latency", 0)
        self.remote_snapclient_manager = RemoteSnapclientManager(
            local_server_id=self.local_server_id,
            audio_device=audio_device,
            latency=latency
        )

        # Initialize router (pass snapclient manager for endpoint lockout)
        self.router = FederationRouter(
            self.ws_manager,
            self.local_server_id,
            self.remote_snapclient_manager
        )

        # Initialize data aggregator
        self.data_aggregator = DataAggregator(
            self.ws_manager,
            self.discovery,
            self.local_server_id,
            self.local_server_name
        )

        # Add local server connection (localhost)
        try:
            logger.info("Connecting to local Snapcast server...")
            await self.ws_manager.add_server(
                server_id=self.local_server_id,
                host="localhost",
                port=1780,
                name=self.local_server_name,
                use_https=False
            )
        except Exception as e:
            logger.error(f"Failed to connect to local server: {e}")

        # Add manual servers
        for server_config in self.manual_servers:
            host = server_config.get("host")
            port = server_config.get("port", 1780)
            name = server_config.get("name", host)

            try:
                server_id = self._generate_server_id(host)
                await self.ws_manager.add_server(
                    server_id=server_id,
                    host=host,
                    port=port,
                    name=name,
                    use_https=False
                )
            except Exception as e:
                logger.error(f"Failed to connect to manual server {name}: {e}")

        logger.info("Federation Service async components started")

    def start(self):
        """Start the federation service"""
        if self.running:
            logger.warning("Service already running")
            return

        self.running = True
        logger.info("Starting Federation Service")

        # Initialize discovery (start it later based on settings)
        self.discovery = AvahiDiscovery(callback=lambda servers: asyncio.run_coroutine_threadsafe(
            self._on_servers_discovered(servers), self.loop
        ))

        # Register server lifecycle callbacks for remote snapclient management
        self.discovery.set_server_added_callback(self._on_server_added)
        self.discovery.set_server_removed_callback(self._on_server_removed)

        # Start discovery if enabled
        if self.auto_discover:
            logger.info("Starting Avahi discovery")
            self.discovery.start()
        else:
            logger.info("Auto-discovery disabled")

        # Start settings monitor thread
        settings_thread = threading.Thread(target=self._settings_monitor_loop, daemon=True)
        settings_thread.start()
        logger.info("Settings monitor thread started")

        # Start async event loop in background thread
        def run_async_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            # Start async components
            self.loop.run_until_complete(self.start_async_components())

            # Keep loop running
            try:
                self.loop.run_forever()
            except Exception as e:
                logger.error(f"Async loop error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                # Don't close the loop here - let stop() handle it
                # This prevents "Event loop is closed" errors if Flask is still running
                logger.info("Async loop exited")

        async_thread = threading.Thread(target=run_async_loop, daemon=True)
        async_thread.start()

        # Wait for async components to initialize
        import time
        time.sleep(2)

        # Start REST API (blocks in main thread)
        self.api = FederationAPI(self.data_aggregator, self.router, self.loop, port=self.api_port)
        logger.info(f"Starting REST API on port {self.api_port}")

        try:
            self.api.run(debug=False)
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            self.stop()

    def stop(self):
        """Stop the federation service"""
        if not self.running:
            return

        logger.info("Stopping Federation Service")
        self.running = False

        # Stop discovery
        if self.discovery:
            self.discovery.stop()

        # Cleanup remote snapclients
        if self.remote_snapclient_manager:
            logger.info("Cleaning up remote snapclients")
            self.remote_snapclient_manager.cleanup_all()

        # Close WebSocket connections
        if self.loop and self.ws_manager:
            asyncio.run_coroutine_threadsafe(self.ws_manager.close_all(), self.loop)

        # Stop async loop
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.loop.stop)
            # Give it time to stop gracefully
            import time
            time.sleep(0.5)
            # Now close the loop
            if not self.loop.is_closed():
                self.loop.close()

        logger.info("Federation Service stopped")


def get_local_ip() -> str:
    """Get local IP address"""
    try:
        # Create a socket to determine local IP (doesn't actually connect)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        # Fallback to localhost if we can't determine IP
        return "localhost"


def load_config() -> Dict:
    """Load configuration from environment variables and settings.json"""
    # Auto-detect local IP if not specified
    default_local_host = os.getenv("FEDERATION_LOCAL_HOST")
    if not default_local_host:
        default_local_host = get_local_ip()
        logger.info(f"Auto-detected local IP: {default_local_host}")

    # Start with env vars (for initial setup)
    config = {
        "enabled": os.getenv("FEDERATION_ENABLED", "0") == "1",
        "auto_discover": os.getenv("FEDERATION_AUTO_DISCOVER", "1") == "1",
        "local_name": os.getenv("DEVICE_NAME", "Plum Snapcast"),
        "local_host": default_local_host,
        "api_port": int(os.getenv("FEDERATION_API_PORT", "5000")),
        "manual_servers": []
    }

    # Override with settings.json if it exists (user preferences take precedence)
    # Import here to avoid circular dependencies
    settings_file = "/app/data/settings.json"
    try:
        # Use SettingsManager to ensure settings.json is created with defaults
        import sys
        sys.path.insert(0, '/app/scripts')
        from settings_api import SettingsManager

        logger.info("Loading settings using SettingsManager...")
        settings_manager = SettingsManager(settings_file)
        settings = settings_manager.get_settings()
        logger.info(f"Settings loaded successfully. DeviceName: {settings.get('deviceName', 'NOT FOUND')}")

        federation_settings = settings.get("federation", {})

        # Override enabled status
        if "enabled" in federation_settings:
            config["enabled"] = federation_settings["enabled"]

        # Override auto-discover
        if "autoDiscover" in federation_settings:
            config["auto_discover"] = federation_settings["autoDiscover"]
            logger.info(f"Auto-discover from settings.json: {config['auto_discover']}")

        # Use deviceName as local server name
        if "deviceName" in settings:
            config["local_name"] = settings["deviceName"]
            logger.info(f"Local server name from settings.json deviceName: {config['local_name']}")
        else:
            logger.warning(f"deviceName not found in settings! Using env var fallback: {config['local_name']}")

    except Exception as e:
        import traceback
        logger.error(f"Failed to load settings.json: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.warning(f"Falling back to env var for local_name: {config['local_name']}")

    # Parse manual servers from JSON env var
    manual_servers_json = os.getenv("FEDERATION_MANUAL_SERVERS", "")
    if manual_servers_json:
        try:
            config["manual_servers"] = json.loads(manual_servers_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse FEDERATION_MANUAL_SERVERS: {e}")

    return config


def main():
    """Main entry point"""
    # Setup logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler("/tmp/federation-service.log")
        ]
    )

    # Load configuration
    config = load_config()

    # Check if federation is enabled
    if not config["enabled"]:
        logger.info("Federation is disabled")
        logger.info("Starting API server for settings and integrations (without federation features)")

        # Import here to avoid circular imports
        from flask import Flask, jsonify
        from flask_cors import CORS
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from settings_api import create_settings_blueprint, SettingsManager
        from integrations_api import create_integrations_blueprint, IntegrationController
        from audio_api import create_audio_blueprint, AudioConfigController
        from playback_api import create_playback_blueprint

        # Create minimal Flask app with just settings and integrations APIs
        app = Flask(__name__)
        CORS(app)

        # Add health endpoint (returns different status than full federation mode)
        @app.route("/api/health", methods=["GET"])
        def health():
            """Health check endpoint - minimal mode"""
            return jsonify({"status": "healthy", "service": "minimal", "federation": False})

        # Register settings API
        settings_manager = SettingsManager()
        settings_bp = create_settings_blueprint(settings_manager)
        app.register_blueprint(settings_bp)
        logger.info("Settings API registered")

        # Register integrations API
        integration_controller = IntegrationController()
        integrations_bp = create_integrations_blueprint(integration_controller)
        app.register_blueprint(integrations_bp)
        logger.info("Integrations API registered")

        # Register audio API
        audio_controller = AudioConfigController(settings_manager)
        audio_bp = create_audio_blueprint(audio_controller)
        app.register_blueprint(audio_bp)
        logger.info("Audio API registered")

        # Register playback API (for real-time position tracking independent of Snapcast)
        playback_bp = create_playback_blueprint()
        app.register_blueprint(playback_bp)
        logger.info("Playback API registered")

        # Start settings monitor to watch for federation being enabled
        settings_file = "/app/data/settings.json"
        settings_mtime = None
        running = True

        def minimal_mode_settings_monitor():
            """Monitor for federation being enabled, restart if needed"""
            nonlocal settings_mtime, running
            logger.info("Minimal mode settings monitor started")
            while running:
                try:
                    if os.path.exists(settings_file):
                        current_mtime = os.path.getmtime(settings_file)
                        if settings_mtime is None:
                            settings_mtime = current_mtime
                        elif current_mtime != settings_mtime:
                            settings_mtime = current_mtime
                            with open(settings_file, 'r') as f:
                                settings = json.load(f)
                                federation_enabled = settings.get("federation", {}).get("enabled", False)
                                if federation_enabled:
                                    logger.warning("Federation enabled via settings - restarting service in full mode")
                                    logger.warning("Service will restart automatically via supervisord")
                                    running = False
                                    os._exit(0)  # Force exit to trigger supervisord restart
                except Exception as e:
                    logger.error(f"Minimal mode settings monitor error: {e}")
                time.sleep(1)  # Check every 1 second

        monitor_thread = threading.Thread(target=minimal_mode_settings_monitor, daemon=True)
        monitor_thread.start()
        logger.info("Minimal mode settings monitor thread started")

        # Start API server
        api_port = config.get("api_port", 5000)
        logger.info(f"Starting API server on port {api_port}")
        try:
            app.run(host="0.0.0.0", port=api_port, debug=False, threaded=True)
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            running = False
            sys.exit(0)
        return

    logger.info("Federation Service Configuration:")
    logger.info(f"  Enabled: {config['enabled']}")
    logger.info(f"  Auto-discover: {config['auto_discover']}")
    logger.info(f"  Local name: {config['local_name']}")
    logger.info(f"  API port: {config['api_port']}")
    logger.info(f"  Manual servers: {len(config['manual_servers'])}")

    # Create and start service
    service = FederationService(config)

    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start service (blocks)
    try:
        service.start()
    except Exception as e:
        logger.error(f"Service failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
