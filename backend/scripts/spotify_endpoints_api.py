#!/usr/bin/env python3
"""
Spotify Endpoints API
Provides CRUD operations for managing multiple Spotify Connect endpoints
"""

import json
import logging
import os
import subprocess
import threading
from typing import Dict, List, Any
from settings_api import SettingsManager

logger = logging.getLogger(__name__)


class SpotifyEndpointsManager:
    """Manages multiple Spotify Connect endpoints via settings"""

    def __init__(self, settings_manager: SettingsManager = None):
        self.settings_manager = settings_manager or SettingsManager()
        self.setup_script = '/app/scripts/setup-spotify-multi-instance.sh'
        self.supervisorctl_cmd = [
            'sudo',
            'supervisorctl',
            '-c',
            '/app/supervisord/supervisord.conf'
        ]
        self._setup_lock = threading.Lock()  # Prevent concurrent API operations

    def _apply_endpoint_changes(self, affected_endpoint_ids: List[str] = None) -> Dict[str, Any]:
        """Apply endpoint changes by running setup script and restarting services"""
        import time

        with self._setup_lock:  # Prevent race conditions from concurrent API calls
            try:
                # Run setup script to create configs, FIFOs, etc.
                logger.info("Running setup-spotify-multi-instance.sh to apply endpoint changes")
                result = subprocess.run(
                    ['sudo', 'bash', '/app/scripts/setup-spotify-multi-instance.sh'],
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                # Log setup script output for debugging
                if result.stdout:
                    logger.info(f"Setup script output: {result.stdout}")
                if result.stderr:
                    logger.warning(f"Setup script stderr: {result.stderr}")

                if result.returncode != 0:
                    logger.error(f"Setup script failed with exit code {result.returncode}")
                    return {
                        "success": False,
                        "message": f"Failed to apply endpoint configuration: {result.stderr}"
                    }

                # Reload supervisord config to pick up any changes
                logger.info("Reloading supervisord configuration")
                reread_result = subprocess.run(
                    self.supervisorctl_cmd + ['reread'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if reread_result.returncode != 0:
                    logger.warning(f"supervisorctl reread warning: {reread_result.stderr}")

                update_result = subprocess.run(
                    self.supervisorctl_cmd + ['update'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if update_result.returncode != 0:
                    logger.warning(f"supervisorctl update warning: {update_result.stderr}")

                # Give supervisord time to process changes
                time.sleep(2)

                # Start or restart affected endpoint services
                service_errors = []
                if affected_endpoint_ids:
                    for endpoint_id in affected_endpoint_ids:
                        services = [
                            f'spotifyd-{endpoint_id}',
                            f'spotify-{endpoint_id}-fifo-keeper',
                            f'spotify-{endpoint_id}-lifecycle-manager'
                        ]

                        for service in services:
                            try:
                                # Check if service is running to decide between start vs restart
                                status_result = subprocess.run(
                                    self.supervisorctl_cmd + ['status', service],
                                    capture_output=True,
                                    text=True,
                                    timeout=10
                                )

                                # If service exists and is not FATAL, restart it. Otherwise start it.
                                if status_result.returncode == 0 and 'FATAL' not in status_result.stdout:
                                    logger.info(f"Restarting service: {service}")
                                    restart_result = subprocess.run(
                                        self.supervisorctl_cmd + ['restart', service],
                                        capture_output=True,
                                        text=True,
                                        timeout=15
                                    )
                                    if restart_result.returncode != 0:
                                        logger.warning(f"Service {service} restart had issues: {restart_result.stderr}")
                                        service_errors.append(f"{service}: {restart_result.stderr}")
                                else:
                                    logger.info(f"Starting service: {service}")
                                    start_result = subprocess.run(
                                        self.supervisorctl_cmd + ['start', service],
                                        capture_output=True,
                                        text=True,
                                        timeout=15
                                    )
                                    if start_result.returncode != 0:
                                        logger.warning(f"Service {service} start had issues: {start_result.stderr}")
                                        service_errors.append(f"{service}: {start_result.stderr}")
                            except subprocess.TimeoutExpired:
                                logger.warning(f"Timeout while managing service: {service}")
                                service_errors.append(f"{service}: timeout")
                            except Exception as e:
                                logger.warning(f"Error managing service {service}: {e}")
                                service_errors.append(f"{service}: {str(e)}")

                        # Small delay between endpoint service groups
                        time.sleep(1)

                # Return success even if some services had warnings (they may auto-restart)
                message = "Endpoint changes applied successfully"
                if service_errors:
                    message += f" (some services had warnings: {', '.join(service_errors[:3])})"
                    logger.warning(f"Service warnings during apply: {service_errors}")

                return {
                    "success": True,
                    "message": message,
                    "warnings": service_errors if service_errors else None
                }

            except subprocess.TimeoutExpired:
                logger.error("Timeout while applying endpoint changes")
                return {
                    "success": False,
                    "message": "Timeout while applying changes"
                }
            except Exception as e:
                logger.error(f"Failed to apply endpoint changes: {e}")
                return {
                    "success": False,
                    "message": f"Failed to apply changes: {str(e)}"
                }

    def _get_next_endpoint_id(self, endpoints: List[Dict]) -> str:
        """Generate next available endpoint ID"""
        if not endpoints:
            return "1"

        # Get highest existing ID and increment
        max_id = max([int(ep["id"]) for ep in endpoints if ep.get("id", "").isdigit()])
        return str(max_id + 1)

    def _get_next_zeroconf_port(self, endpoints: List[Dict]) -> int:
        """Get next available zeroconf port"""
        # Port allocation:
        # ID 1: Port 5354
        # ID 2: Port 5355
        # ID 3: Port 5356
        # Pattern: Port = 5354 + (id-1)

        if not endpoints:
            return 5354

        # Find highest port in use
        used_ports = [ep.get("zeroconfPort", 5354) for ep in endpoints]
        max_port = max(used_ports)

        # Increment by 1
        return max_port + 1

    def list_endpoints(self) -> Dict[str, Any]:
        """List all Spotify Connect endpoints"""
        try:
            settings = self.settings_manager.get_settings()
            spotify = settings.get("integrations", {}).get("spotify", {})

            # Handle both old and new format
            if "endpoints" in spotify:
                endpoints = spotify["endpoints"]
            elif "deviceName" in spotify or "enabled" in spotify:
                # Old format - convert to array
                endpoints = [{
                    "id": "1",
                    "enabled": spotify.get("enabled", False),
                    "deviceName": spotify.get("deviceName", "Plum Audio"),
                    "zeroconfPort": 5354
                }]
            else:
                # No endpoints
                endpoints = []

            return {
                "success": True,
                "endpoints": endpoints
            }

        except Exception as e:
            logger.error(f"Failed to list endpoints: {e}")
            return {
                "success": False,
                "message": str(e),
                "endpoints": []
            }

    def add_endpoint(self, device_name: str, enabled: bool = True) -> Dict[str, Any]:
        """Add a new Spotify Connect endpoint"""
        try:
            # Validate device name
            if not device_name or len(device_name) > 50:
                return {
                    "success": False,
                    "message": "Invalid device name (must be 1-50 characters)"
                }

            # Get current endpoints
            settings = self.settings_manager.get_settings()
            spotify = settings.get("integrations", {}).get("spotify", {})

            if "endpoints" in spotify:
                endpoints = spotify["endpoints"]
            else:
                endpoints = []

            # Check endpoint limit (max 10)
            if len(endpoints) >= 10:
                return {
                    "success": False,
                    "message": "Maximum of 10 Spotify Connect endpoints allowed"
                }

            # Generate new endpoint config
            new_id = self._get_next_endpoint_id(endpoints)
            zeroconf_port = self._get_next_zeroconf_port(endpoints)

            new_endpoint = {
                "id": new_id,
                "enabled": enabled,
                "deviceName": device_name,
                "zeroconfPort": zeroconf_port
            }

            # Add to endpoints
            endpoints.append(new_endpoint)

            # Get bitrate from settings (shared setting)
            bitrate = spotify.get("bitrate", 320)

            # Update settings
            self.settings_manager.update_settings({
                "integrations": {
                    "spotify": {
                        "bitrate": bitrate,
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Added Spotify Connect endpoint: {new_endpoint}")

            # Apply changes immediately (run setup script and restart services)
            apply_result = self._apply_endpoint_changes([new_id])
            if not apply_result["success"]:
                return {
                    "success": False,
                    "message": f"Endpoint added to settings but failed to apply: {apply_result['message']}",
                    "endpoint": new_endpoint
                }

            return {
                "success": True,
                "message": f"Added endpoint '{device_name}' and applied changes",
                "endpoint": new_endpoint
            }

        except Exception as e:
            logger.error(f"Failed to add endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }

    def update_endpoint(self, endpoint_id: str, device_name: str = None, enabled: bool = None) -> Dict[str, Any]:
        """Update an existing Spotify Connect endpoint"""
        try:
            # Get current endpoints
            settings = self.settings_manager.get_settings()
            spotify = settings.get("integrations", {}).get("spotify", {})

            if "endpoints" not in spotify:
                return {
                    "success": False,
                    "message": "No endpoints configured"
                }

            endpoints = spotify["endpoints"]

            # Find endpoint
            endpoint_index = None
            for i, ep in enumerate(endpoints):
                if ep.get("id") == endpoint_id:
                    endpoint_index = i
                    break

            if endpoint_index is None:
                return {
                    "success": False,
                    "message": f"Endpoint '{endpoint_id}' not found"
                }

            # Update endpoint
            if device_name is not None:
                if not device_name or len(device_name) > 50:
                    return {
                        "success": False,
                        "message": "Invalid device name (must be 1-50 characters)"
                    }
                endpoints[endpoint_index]["deviceName"] = device_name

            if enabled is not None:
                endpoints[endpoint_index]["enabled"] = enabled

            # Get bitrate from settings (shared setting)
            bitrate = spotify.get("bitrate", 320)

            # Update settings
            self.settings_manager.update_settings({
                "integrations": {
                    "spotify": {
                        "bitrate": bitrate,
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Updated Spotify Connect endpoint {endpoint_id}: {endpoints[endpoint_index]}")

            # Apply changes immediately (run setup script and restart services)
            apply_result = self._apply_endpoint_changes([endpoint_id])
            if not apply_result["success"]:
                return {
                    "success": False,
                    "message": f"Endpoint updated in settings but failed to apply: {apply_result['message']}",
                    "endpoint": endpoints[endpoint_index]
                }

            return {
                "success": True,
                "message": f"Updated endpoint '{endpoint_id}' and applied changes",
                "endpoint": endpoints[endpoint_index]
            }

        except Exception as e:
            logger.error(f"Failed to update endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }

    def remove_endpoint(self, endpoint_id: str) -> Dict[str, Any]:
        """Remove a Spotify Connect endpoint"""
        try:
            # Get current endpoints
            settings = self.settings_manager.get_settings()
            spotify = settings.get("integrations", {}).get("spotify", {})

            if "endpoints" not in spotify:
                return {
                    "success": False,
                    "message": "No endpoints configured"
                }

            endpoints = spotify["endpoints"]

            # Allow removing last endpoint (unlike AirPlay, Spotify can have zero endpoints)
            # Find and remove endpoint
            endpoint_index = None
            for i, ep in enumerate(endpoints):
                if ep.get("id") == endpoint_id:
                    endpoint_index = i
                    break

            if endpoint_index is None:
                return {
                    "success": False,
                    "message": f"Endpoint '{endpoint_id}' not found"
                }

            removed_endpoint = endpoints.pop(endpoint_index)
            removed_id = removed_endpoint["id"]

            # Get bitrate from settings (shared setting)
            bitrate = spotify.get("bitrate", 320)

            # Update settings
            self.settings_manager.update_settings({
                "integrations": {
                    "spotify": {
                        "bitrate": bitrate,
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Removed Spotify Connect endpoint: {removed_endpoint}")

            # Apply changes immediately (run setup script to disable removed endpoint)
            # Pass None to apply changes to all endpoints (this will disable the removed one)
            apply_result = self._apply_endpoint_changes(None)
            if not apply_result["success"]:
                return {
                    "success": False,
                    "message": f"Endpoint removed from settings but failed to apply: {apply_result['message']}"
                }

            # Stop services for removed endpoint
            try:
                services = [
                    f'spotifyd-{removed_id}',
                    f'spotify-{removed_id}-fifo-keeper',
                    f'spotify-{removed_id}-lifecycle-manager'
                ]
                for service in services:
                    subprocess.run(
                        self.supervisorctl_cmd + ['stop', service],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
            except Exception as e:
                logger.warning(f"Failed to stop services for removed endpoint: {e}")

            return {
                "success": True,
                "message": f"Removed endpoint '{removed_endpoint['deviceName']}' and applied changes"
            }

        except Exception as e:
            logger.error(f"Failed to remove endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }

    def update_bitrate(self, bitrate: int) -> Dict[str, Any]:
        """Update Spotify bitrate (shared across all endpoints)

        WARNING: This will restart ALL spotifyd instances and interrupt active playback.

        Args:
            bitrate: Bitrate value (96, 160, or 320)

        Returns:
            Dict with success status and message
        """
        try:
            # Validate bitrate
            if bitrate not in [96, 160, 320]:
                return {
                    "success": False,
                    "message": "Bitrate must be 96, 160, or 320"
                }

            settings = self.settings_manager.get_settings()
            spotify = settings.get("integrations", {}).get("spotify", {})
            endpoints = spotify.get("endpoints", [])

            # Update settings with new bitrate
            self.settings_manager.update_settings({
                "integrations": {
                    "spotify": {
                        "bitrate": bitrate,
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Updated Spotify bitrate to {bitrate}")

            # Apply changes to all endpoints (regenerate configs with new bitrate)
            with self._setup_lock:
                try:
                    # Run setup script to regenerate all configs with new bitrate
                    result = subprocess.run(
                        ['sudo', 'bash', self.setup_script],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )

                    if result.returncode != 0:
                        logger.error(f"Setup script failed: {result.stderr}")
                        return {
                            "success": False,
                            "message": f"Failed to regenerate configs: {result.stderr}"
                        }

                    # Reload supervisord to pick up any config changes
                    subprocess.run(
                        self.supervisorctl_cmd + ['reread'],
                        capture_output=True,
                        timeout=10
                    )
                    subprocess.run(
                        self.supervisorctl_cmd + ['update'],
                        capture_output=True,
                        timeout=10
                    )

                    # Restart ALL spotifyd instances to apply new bitrate
                    # This WILL interrupt any active playback
                    for endpoint in endpoints:
                        endpoint_id = endpoint["id"]
                        service_name = f'spotifyd-{endpoint_id}'
                        try:
                            subprocess.run(
                                self.supervisorctl_cmd + ['restart', service_name],
                                capture_output=True,
                                text=True,
                                timeout=15
                            )
                        except Exception as e:
                            logger.warning(f"Failed to restart {service_name}: {e}")

                    return {
                        "success": True,
                        "message": f"Updated bitrate to {bitrate}. All Spotify endpoints restarted.",
                        "warning": "Active playback was interrupted to apply bitrate change."
                    }

                except subprocess.TimeoutExpired:
                    logger.error("Timeout while updating bitrate")
                    return {
                        "success": False,
                        "message": "Timeout while applying bitrate change"
                    }
                except Exception as e:
                    logger.error(f"Failed to update bitrate: {e}")
                    return {
                        "success": False,
                        "message": f"Failed to apply bitrate change: {str(e)}"
                    }

        except Exception as e:
            logger.error(f"Failed to update bitrate: {e}")
            return {
                "success": False,
                "message": str(e)
            }
