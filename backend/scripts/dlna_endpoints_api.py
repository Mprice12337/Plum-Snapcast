#!/usr/bin/env python3
"""
DLNA/UPnP Endpoints API
Provides CRUD operations for managing multiple DLNA/UPnP endpoints
"""

import json
import logging
import os
import subprocess
import threading
import uuid as uuid_lib
from typing import Dict, List, Any
from settings_api import SettingsManager

logger = logging.getLogger(__name__)


class DLNAEndpointsManager:
    """Manages multiple DLNA/UPnP endpoints via settings"""

    def __init__(self, settings_manager: SettingsManager = None):
        self.settings_manager = settings_manager or SettingsManager()
        self.supervisorctl_cmd = [
            'sudo',
            'supervisorctl',
            '-c',
            '/app/supervisord/supervisord.conf'
        ]
        self._setup_lock = threading.Lock()

    def _apply_endpoint_changes(self, affected_endpoint_ids: List[str] = None) -> Dict[str, Any]:
        """Apply endpoint changes by running setup script and restarting services"""
        import time

        with self._setup_lock:
            try:
                # Run setup script to create FIFOs, wrapper scripts, etc.
                logger.info("Running setup-dlna-multi-instance.sh to apply endpoint changes")
                result = subprocess.run(
                    ['sudo', 'bash', '/app/scripts/setup-dlna-multi-instance.sh'],
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
                            f'gmrender-{endpoint_id}',
                            f'dlna-{endpoint_id}-fifo-keeper',
                            f'dlna-{endpoint_id}-lifecycle-manager',
                            f'dlna-{endpoint_id}-metadata-bridge'
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

    def _get_next_port(self, endpoints: List[Dict]) -> int:
        """Get next available port"""
        # Port allocation: 49494, 49495, 49496, ...
        # ID 1: Port 49494
        # ID 2: Port 49495
        # Pattern: Port = 49494 + (id-1)

        if not endpoints:
            return 49494

        # Find highest port in use
        used_ports = [ep.get("port", 49494) for ep in endpoints]
        max_port = max(used_ports)

        # Increment by 1
        return max_port + 1

    def _generate_uuid(self) -> str:
        """Generate a unique UUID for DLNA/UPnP device"""
        return str(uuid_lib.uuid4())

    def list_endpoints(self) -> Dict[str, Any]:
        """List all DLNA endpoints"""
        try:
            settings = self.settings_manager.get_settings()
            dlna = settings.get("integrations", {}).get("dlna", {})

            # Handle both old and new format
            if "endpoints" in dlna:
                endpoints = dlna["endpoints"]
            elif "deviceName" in dlna or "enabled" in dlna:
                # Old format - convert to array
                endpoints = [{
                    "id": "1",
                    "enabled": dlna.get("enabled", False),
                    "deviceName": dlna.get("deviceName", "Plum Audio"),
                    "port": 49494,
                    "uuid": dlna.get("uuid", self._generate_uuid())
                }]
            else:
                endpoints = []

            return {
                "success": True,
                "endpoints": endpoints
            }

        except Exception as e:
            logger.error(f"Error listing DLNA endpoints: {e}")
            return {
                "success": False,
                "message": str(e),
                "endpoints": []
            }

    def add_endpoint(self, device_name: str, enabled: bool = True) -> Dict[str, Any]:
        """Add a new DLNA endpoint"""
        try:
            settings = self.settings_manager.get_settings()

            # Ensure integrations.dlna.endpoints exists
            if "integrations" not in settings:
                settings["integrations"] = {}
            if "dlna" not in settings["integrations"]:
                settings["integrations"]["dlna"] = {}
            if "endpoints" not in settings["integrations"]["dlna"]:
                settings["integrations"]["dlna"]["endpoints"] = []

            endpoints = settings["integrations"]["dlna"]["endpoints"]

            # Validate max endpoints (10 max)
            if len(endpoints) >= 10:
                return {
                    "success": False,
                    "message": "Maximum number of DLNA endpoints (10) reached"
                }

            # Generate new endpoint configuration
            new_id = self._get_next_endpoint_id(endpoints)
            new_port = self._get_next_port(endpoints)
            new_uuid = self._generate_uuid()

            new_endpoint = {
                "id": new_id,
                "enabled": enabled,
                "deviceName": device_name,
                "port": new_port,
                "uuid": new_uuid
            }

            # Add to settings
            endpoints.append(new_endpoint)
            self.settings_manager.update_settings({
                "integrations": {
                    "dlna": {
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Added DLNA endpoint: {device_name} (ID: {new_id}, Port: {new_port})")

            # Apply changes (create resources, restart services)
            apply_result = self._apply_endpoint_changes([new_id])

            return {
                "success": True,
                "message": "DLNA endpoint added successfully",
                "endpoint": new_endpoint,
                "apply_result": apply_result
            }

        except Exception as e:
            logger.error(f"Error adding DLNA endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }

    def update_endpoint(self, endpoint_id: str, device_name: str = None, enabled: bool = None) -> Dict[str, Any]:
        """Update an existing DLNA endpoint"""
        try:
            settings = self.settings_manager.get_settings()
            endpoints = settings.get("integrations", {}).get("dlna", {}).get("endpoints", [])

            # Find endpoint
            endpoint = None
            endpoint_index = None
            for i, ep in enumerate(endpoints):
                if ep.get("id") == endpoint_id:
                    endpoint = ep
                    endpoint_index = i
                    break

            if not endpoint:
                return {
                    "success": False,
                    "message": f"DLNA endpoint with ID {endpoint_id} not found"
                }

            # Update fields
            if device_name is not None:
                endpoint["deviceName"] = device_name
            if enabled is not None:
                endpoint["enabled"] = enabled

            # Save settings
            endpoints[endpoint_index] = endpoint
            self.settings_manager.update_settings({
                "integrations": {
                    "dlna": {
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Updated DLNA endpoint {endpoint_id}: {endpoint.get('deviceName')}")

            # Apply changes
            apply_result = self._apply_endpoint_changes([endpoint_id])

            return {
                "success": True,
                "message": "DLNA endpoint updated successfully",
                "endpoint": endpoint,
                "apply_result": apply_result
            }

        except Exception as e:
            logger.error(f"Error updating DLNA endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }

    def remove_endpoint(self, endpoint_id: str) -> Dict[str, Any]:
        """Remove a DLNA endpoint"""
        try:
            settings = self.settings_manager.get_settings()
            endpoints = settings.get("integrations", {}).get("dlna", {}).get("endpoints", [])

            # Find and remove endpoint
            endpoint_to_remove = None
            for i, ep in enumerate(endpoints):
                if ep.get("id") == endpoint_id:
                    endpoint_to_remove = endpoints.pop(i)
                    break

            if not endpoint_to_remove:
                return {
                    "success": False,
                    "message": f"DLNA endpoint with ID {endpoint_id} not found"
                }

            # Save settings
            self.settings_manager.update_settings({
                "integrations": {
                    "dlna": {
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Removed DLNA endpoint {endpoint_id}: {endpoint_to_remove.get('deviceName')}")

            # Apply changes (cleanup resources, stop services)
            apply_result = self._apply_endpoint_changes([])  # Empty list triggers cleanup

            return {
                "success": True,
                "message": "DLNA endpoint removed successfully",
                "apply_result": apply_result
            }

        except Exception as e:
            logger.error(f"Error removing DLNA endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }
