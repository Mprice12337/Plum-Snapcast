#!/usr/bin/env python3
"""
AirPlay Endpoints API
Provides CRUD operations for managing multiple AirPlay endpoints
"""

import json
import logging
import os
import subprocess
from typing import Dict, List, Any
from settings_api import SettingsManager

logger = logging.getLogger(__name__)


class AirPlayEndpointsManager:
    """Manages multiple AirPlay endpoints via settings"""

    def __init__(self, settings_manager: SettingsManager = None):
        self.settings_manager = settings_manager or SettingsManager()

    def _get_next_endpoint_id(self, endpoints: List[Dict]) -> str:
        """Generate next available endpoint ID"""
        if not endpoints:
            return "1"

        # Get highest existing ID and increment
        max_id = max([int(ep["id"]) for ep in endpoints if ep.get("id", "").isdigit()])
        return str(max_id + 1)

    def _get_next_port_config(self, endpoints: List[Dict]) -> tuple:
        """Get next available port and UDP base port"""
        # Port allocation:
        # ID 1: Port 5000, UDP 6001
        # ID 2: Port 7000, UDP 6011
        # ID 3: Port 8000, UDP 6021
        # Pattern: Port = 5000 + (id-1)*2000, UDP = 6001 + (id-1)*10

        if not endpoints:
            return (5000, 6001)

        # Find highest port in use
        used_ports = [ep.get("port", 5000) for ep in endpoints]
        max_port = max(used_ports)

        # Increment by 2000
        next_port = max_port + 2000

        # Calculate UDP base (pattern: 6001, 6011, 6021, ...)
        port_index = (next_port - 5000) // 2000
        next_udp = 6001 + (port_index * 10)

        return (next_port, next_udp)

    def list_endpoints(self) -> Dict[str, Any]:
        """List all AirPlay endpoints"""
        try:
            settings = self.settings_manager.get_settings()
            airplay = settings.get("integrations", {}).get("airplay", {})

            # Handle both old and new format
            if "endpoints" in airplay:
                endpoints = airplay["endpoints"]
            elif "deviceName" in airplay or "enabled" in airplay:
                # Old format - convert to array
                endpoints = [{
                    "id": "1",
                    "enabled": airplay.get("enabled", True),
                    "deviceName": airplay.get("deviceName", "Plum Audio"),
                    "port": 5000,
                    "udpPortBase": 6001
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
        """Add a new AirPlay endpoint"""
        try:
            # Validate device name
            if not device_name or len(device_name) > 50:
                return {
                    "success": False,
                    "message": "Invalid device name (must be 1-50 characters)"
                }

            # Get current endpoints
            settings = self.settings_manager.get_settings()
            airplay = settings.get("integrations", {}).get("airplay", {})

            if "endpoints" in airplay:
                endpoints = airplay["endpoints"]
            else:
                endpoints = []

            # Check endpoint limit (max 10)
            if len(endpoints) >= 10:
                return {
                    "success": False,
                    "message": "Maximum of 10 AirPlay endpoints allowed"
                }

            # Generate new endpoint config
            new_id = self._get_next_endpoint_id(endpoints)
            port, udp_base = self._get_next_port_config(endpoints)

            new_endpoint = {
                "id": new_id,
                "enabled": enabled,
                "deviceName": device_name,
                "port": port,
                "udpPortBase": udp_base
            }

            # Add to endpoints
            endpoints.append(new_endpoint)

            # Update settings
            self.settings_manager.update_settings({
                "integrations": {
                    "airplay": {
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Added AirPlay endpoint: {new_endpoint}")

            return {
                "success": True,
                "message": f"Added endpoint '{device_name}'",
                "endpoint": new_endpoint,
                "restart_required": True  # Frontend should prompt for container restart
            }

        except Exception as e:
            logger.error(f"Failed to add endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }

    def update_endpoint(self, endpoint_id: str, device_name: str = None, enabled: bool = None) -> Dict[str, Any]:
        """Update an existing AirPlay endpoint"""
        try:
            # Get current endpoints
            settings = self.settings_manager.get_settings()
            airplay = settings.get("integrations", {}).get("airplay", {})

            if "endpoints" not in airplay:
                return {
                    "success": False,
                    "message": "No endpoints configured"
                }

            endpoints = airplay["endpoints"]

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

            # Update settings
            self.settings_manager.update_settings({
                "integrations": {
                    "airplay": {
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Updated AirPlay endpoint {endpoint_id}: {endpoints[endpoint_index]}")

            return {
                "success": True,
                "message": f"Updated endpoint '{endpoint_id}'",
                "endpoint": endpoints[endpoint_index],
                "restart_required": True  # Frontend should prompt for container restart
            }

        except Exception as e:
            logger.error(f"Failed to update endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }

    def remove_endpoint(self, endpoint_id: str) -> Dict[str, Any]:
        """Remove an AirPlay endpoint"""
        try:
            # Get current endpoints
            settings = self.settings_manager.get_settings()
            airplay = settings.get("integrations", {}).get("airplay", {})

            if "endpoints" not in airplay:
                return {
                    "success": False,
                    "message": "No endpoints configured"
                }

            endpoints = airplay["endpoints"]

            # Prevent removing last endpoint
            if len(endpoints) <= 1:
                return {
                    "success": False,
                    "message": "Cannot remove the last AirPlay endpoint"
                }

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

            # Update settings
            self.settings_manager.update_settings({
                "integrations": {
                    "airplay": {
                        "endpoints": endpoints
                    }
                }
            })

            logger.info(f"Removed AirPlay endpoint: {removed_endpoint}")

            return {
                "success": True,
                "message": f"Removed endpoint '{removed_endpoint['deviceName']}'",
                "restart_required": True  # Frontend should prompt for container restart
            }

        except Exception as e:
            logger.error(f"Failed to remove endpoint: {e}")
            return {
                "success": False,
                "message": str(e)
            }
