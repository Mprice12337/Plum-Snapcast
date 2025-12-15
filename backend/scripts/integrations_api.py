#!/usr/bin/env python3
"""
Integrations Actions API
Provides endpoints for controlling integration services (start/stop, config updates)
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Dict, Any
from flask import Blueprint, jsonify, request

# Import SettingsManager to persist state changes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settings_api import SettingsManager

logger = logging.getLogger(__name__)

# Configuration file paths
SHAIRPORT_SYNC_CONF = "/app/config/shairport-sync.conf"
SPOTIFYD_CONF = "/app/config/spotifyd.conf"
DLNA_DEVICE_NAME_FILE = "/app/config/dlna-device-name.txt"
SUPERVISORCTL_CONF = "/app/supervisord/supervisord.conf"


class IntegrationController:
    """Controls integration services via supervisorctl"""

    def __init__(self):
        self.supervisorctl_cmd = [
            "supervisorctl",
            "-c",
            SUPERVISORCTL_CONF
        ]

    def _run_supervisorctl(self, *args) -> tuple[bool, str]:
        """Run supervisorctl command and return success status and output"""
        try:
            cmd = self.supervisorctl_cmd + list(args)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            success = result.returncode == 0
            output = result.stdout + result.stderr
            logger.info(f"supervisorctl {' '.join(args)}: {output.strip()}")
            return success, output
        except subprocess.TimeoutExpired:
            logger.error(f"supervisorctl timeout: {' '.join(args)}")
            return False, "Command timed out"
        except Exception as e:
            logger.error(f"supervisorctl error: {e}")
            return False, str(e)

    def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Get status of a supervisord service"""
        success, output = self._run_supervisorctl("status", service_name)

        if not success:
            return {"running": False, "status": "unknown", "error": output}

        # Parse supervisorctl status output
        # Format: "service_name    RUNNING   pid 123, uptime 1:23:45"
        parts = output.split()
        if len(parts) >= 2:
            status = parts[1]
            return {
                "running": status == "RUNNING",
                "status": status.lower(),
                "raw_output": output.strip()
            }

        return {"running": False, "status": "unknown", "raw_output": output}

    def start_service(self, service_name: str) -> tuple[bool, str]:
        """Start a supervisord service"""
        return self._run_supervisorctl("start", service_name)

    def stop_service(self, service_name: str) -> tuple[bool, str]:
        """Stop a supervisord service"""
        return self._run_supervisorctl("stop", service_name)

    def restart_service(self, service_name: str) -> tuple[bool, str]:
        """Restart a supervisord service"""
        return self._run_supervisorctl("restart", service_name)


class AirPlayController:
    """Controls AirPlay (shairport-sync) service"""

    def __init__(self, integration_controller: IntegrationController, settings_manager: SettingsManager = None):
        self.controller = integration_controller
        self.service_name = "shairport-sync"
        self.config_file = SHAIRPORT_SYNC_CONF
        self.settings_manager = settings_manager or SettingsManager()

    def enable(self) -> Dict[str, Any]:
        """Enable AirPlay service"""
        success, output = self.controller.start_service(self.service_name)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "airplay": {
                            "enabled": True
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist AirPlay enabled state: {e}")

        return {
            "success": success,
            "message": "AirPlay enabled" if success else "Failed to enable AirPlay",
            "details": output.strip()
        }

    def disable(self) -> Dict[str, Any]:
        """Disable AirPlay service"""
        success, output = self.controller.stop_service(self.service_name)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "airplay": {
                            "enabled": False
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist AirPlay disabled state: {e}")

        return {
            "success": success,
            "message": "AirPlay disabled" if success else "Failed to disable AirPlay",
            "details": output.strip()
        }

    def get_status(self) -> Dict[str, Any]:
        """Get AirPlay service status"""
        return self.controller.get_service_status(self.service_name)

    def update_device_name(self, device_name: str) -> Dict[str, Any]:
        """Update AirPlay device name in config and restart service"""
        try:
            # Validate device name
            if not device_name or len(device_name) > 50:
                return {
                    "success": False,
                    "message": "Invalid device name (must be 1-50 characters)"
                }

            # Escape special characters for sed
            device_name_escaped = device_name.replace('"', '\\"').replace('/', '\\/')

            # Use sed to update config (same approach as setup.sh)
            sed_pattern = f'/^general = {{/,/^}}/{{s/name = ".*";/name = "{device_name_escaped}";/}}'
            sed_cmd = ["sed", "-i", sed_pattern, self.config_file]

            result = subprocess.run(sed_cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                logger.error(f"sed command failed: {result.stderr}")
                return {
                    "success": False,
                    "message": "Failed to update config file",
                    "details": result.stderr.strip()
                }

            logger.info(f"Updated AirPlay device name to: {device_name}")

            # Restart service to apply changes
            success, output = self.controller.restart_service(self.service_name)

            if not success:
                logger.error(f"Failed to restart shairport-sync: {output}")

            # Update settings to persist device name and enabled state
            # Note: restarting the service enables it, so we set enabled=True
            if success:
                try:
                    self.settings_manager.update_settings({
                        "integrations": {
                            "airplay": {
                                "deviceName": device_name,
                                "enabled": True
                            }
                        }
                    })
                except Exception as e:
                    logger.error(f"Failed to persist AirPlay device name: {e}")

            return {
                "success": success,
                "message": f"Device name updated to '{device_name}'" if success else "Failed to restart AirPlay service",
                "device_name": device_name if success else None,
                "details": output.strip()
            }

        except Exception as e:
            logger.error(f"Failed to update device name: {e}")
            return {
                "success": False,
                "message": f"Error updating device name: {str(e)}"
            }


class BluetoothController:
    """Controls Bluetooth services"""

    def __init__(self, integration_controller: IntegrationController, settings_manager: SettingsManager = None):
        self.controller = integration_controller
        # Bluetooth requires multiple services including dynamic lifecycle management
        self.services = [
            "bluetoothd",
            "bluetooth-init",
            "bluealsa",
            "bluealsa-aplay",
            "bluetooth-monitor",
            "bluetooth-fifo-keeper",
            "bluetooth-stream-lifecycle-manager"
        ]
        self.adapter = "hci0"
        self.settings_manager = settings_manager or SettingsManager()

    def _set_adapter_discoverable(self, discoverable: bool, pairable: bool = True) -> tuple[bool, str]:
        """Set Bluetooth adapter discoverable and pairable state via bluetoothctl"""
        try:
            # Build bluetoothctl commands
            commands = [
                "power on",
                f"pairable {'on' if pairable else 'off'}",
                "discoverable-timeout 0",  # No timeout
                f"discoverable {'on' if discoverable else 'off'}"
            ]

            # Join commands with newlines for bluetoothctl stdin
            commands_str = "\n".join(commands) + "\n"

            # Run bluetoothctl with commands via stdin
            result = subprocess.run(
                ["bluetoothctl"],
                input=commands_str,
                capture_output=True,
                text=True,
                timeout=10
            )

            success = result.returncode == 0
            output = result.stdout + result.stderr

            if success:
                state = "discoverable and pairable" if discoverable and pairable else "not discoverable"
                logger.info(f"Bluetooth adapter set to {state}")
            else:
                logger.error(f"Failed to set adapter state: {output}")

            return success, output.strip()

        except subprocess.TimeoutExpired:
            logger.error("bluetoothctl command timed out")
            return False, "Command timed out"
        except Exception as e:
            logger.error(f"Failed to set adapter state: {e}")
            return False, str(e)

    def enable(self) -> Dict[str, Any]:
        """Enable Bluetooth services"""
        all_success = True
        outputs = []

        # Start services in order
        for service_name in self.services:
            success, output = self.controller.start_service(service_name)
            outputs.append(f"{service_name}: {output.strip()}")
            if not success:
                all_success = False
                logger.error(f"Failed to start {service_name}: {output}")

        # Wait for bluetoothd to initialize before setting adapter properties
        if all_success:
            time.sleep(2)  # Give bluetoothd time to start

            # Set adapter to discoverable and pairable
            adapter_success, adapter_output = self._set_adapter_discoverable(discoverable=True, pairable=True)
            outputs.append(f"adapter config: {adapter_output}")

            if not adapter_success:
                logger.warning(f"Services started but failed to set adapter discoverable: {adapter_output}")
                # Don't fail the entire operation if adapter config fails
                # The user can still use Bluetooth, just not discoverable

        # Update settings to persist state
        if all_success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "bluetooth": {
                            "enabled": True
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist Bluetooth enabled state: {e}")

        return {
            "success": all_success,
            "message": "Bluetooth enabled" if all_success else "Failed to enable some Bluetooth services",
            "details": "\n".join(outputs)
        }

    def disable(self) -> Dict[str, Any]:
        """Disable Bluetooth services"""
        all_success = True
        outputs = []

        # Set adapter to not discoverable before stopping services
        # This makes the device disappear from Bluetooth discovery immediately
        adapter_success, adapter_output = self._set_adapter_discoverable(discoverable=False, pairable=False)
        outputs.append(f"adapter config: {adapter_output}")

        if not adapter_success:
            logger.warning(f"Failed to set adapter not discoverable: {adapter_output}")
            # Continue with stopping services even if adapter config fails

        # Stop services in reverse order
        for service_name in reversed(self.services):
            success, output = self.controller.stop_service(service_name)
            outputs.append(f"{service_name}: {output.strip()}")
            if not success:
                all_success = False
                logger.error(f"Failed to stop {service_name}: {output}")

        # Update settings to persist state
        if all_success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "bluetooth": {
                            "enabled": False
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist Bluetooth disabled state: {e}")

        return {
            "success": all_success,
            "message": "Bluetooth disabled" if all_success else "Failed to disable some Bluetooth services",
            "details": "\n".join(outputs)
        }

    def get_status(self) -> Dict[str, Any]:
        """Get Bluetooth service status"""
        # Check first service (bluetoothd) as representative
        status = self.controller.get_service_status(self.services[0])

        # Check all services for detailed status
        all_running = True
        service_statuses = {}
        for service_name in self.services:
            svc_status = self.controller.get_service_status(service_name)
            service_statuses[service_name] = svc_status
            if not svc_status.get("running", False):
                all_running = False

        return {
            "running": all_running,
            "status": "running" if all_running else "partial" if status.get("running", False) else "stopped",
            "services": service_statuses
        }

    def update_device_name(self, device_name: str) -> Dict[str, Any]:
        """Update Bluetooth device name via D-Bus"""
        try:
            # Validate device name
            if not device_name or len(device_name) > 50:
                return {
                    "success": False,
                    "message": "Invalid device name (must be 1-50 characters)"
                }

            # Check if Bluetooth services are running
            status = self.get_status()
            services_running = status.get("running", False)

            # If services aren't running, persist the device name to settings FIRST
            # This ensures bluetooth-init.sh reads the new name when it starts
            if not services_running:
                logger.info("Bluetooth services not running, persisting device name before starting services")
                try:
                    self.settings_manager.update_settings({
                        "integrations": {
                            "bluetooth": {
                                "deviceName": device_name,
                                "enabled": True
                            }
                        }
                    })
                except Exception as e:
                    logger.error(f"Failed to persist Bluetooth device name: {e}")
                    return {
                        "success": False,
                        "message": f"Failed to persist device name: {str(e)}"
                    }

                # Now start services - bluetooth-init.sh will read the new name from settings
                logger.info("Starting Bluetooth services with new device name")
                for service_name in self.services:
                    success, output = self.controller.start_service(service_name)
                    if not success:
                        logger.error(f"Failed to start {service_name}: {output}")
                        return {
                            "success": False,
                            "message": f"Failed to start Bluetooth services: {output}",
                            "details": output
                        }

                # Wait for bluetoothd and bluetooth-init.sh to complete initialization
                # This ensures the init script finishes setting the old name before we override it
                time.sleep(5)

            # Escape device name for shell command
            device_name_escaped = device_name.replace("'", "'\\''")

            # Use gdbus to set Bluetooth adapter alias (same approach as bluetooth-init.sh)
            gdbus_cmd = [
                "gdbus", "call", "--system",
                "--dest", "org.bluez",
                "--object-path", f"/org/bluez/{self.adapter}",
                "--method", "org.freedesktop.DBus.Properties.Set",
                "org.bluez.Adapter1",
                "Alias",
                f"<'{device_name_escaped}'>"
            ]

            result = subprocess.run(gdbus_cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                logger.error(f"gdbus command failed: {result.stderr}")
                return {
                    "success": False,
                    "message": "Failed to update Bluetooth device name",
                    "details": result.stderr.strip()
                }

            logger.info(f"Updated Bluetooth device name to: {device_name}")

            # If we started the services, also set the adapter to discoverable
            if not services_running:
                adapter_success, adapter_output = self._set_adapter_discoverable(discoverable=True, pairable=True)
                if not adapter_success:
                    logger.warning(f"Device name updated but failed to set adapter discoverable: {adapter_output}")
            else:
                # Services were already running, so we only need to persist the device name
                # (enabled state doesn't change, settings were not updated before starting services)
                try:
                    self.settings_manager.update_settings({
                        "integrations": {
                            "bluetooth": {
                                "deviceName": device_name
                            }
                        }
                    })
                except Exception as e:
                    logger.error(f"Failed to persist Bluetooth device name: {e}")

            return {
                "success": True,
                "message": f"Device name updated to '{device_name}'",
                "device_name": device_name,
                "details": result.stdout.strip()
            }

        except Exception as e:
            logger.error(f"Failed to update Bluetooth device name: {e}")
            return {
                "success": False,
                "message": f"Error updating device name: {str(e)}"
            }

    def update_settings(self, auto_pair: bool = None, discoverable: bool = None) -> Dict[str, Any]:
        """Update Bluetooth settings (auto-pair and/or discoverable) and apply immediately"""
        try:
            # Check if Bluetooth services are running
            services_running = all(
                self.controller.get_service_status(service).get("running", False)
                for service in self.services
            )

            # Get current settings
            try:
                with open("/app/data/settings.json", "r") as f:
                    current_settings = json.load(f)
                    current_bluetooth = current_settings.get("integrations", {}).get("bluetooth", {})
                    current_auto_pair = current_bluetooth.get("autoPair", True)
                    current_discoverable = current_bluetooth.get("discoverable", True)
            except Exception:
                current_auto_pair = True
                current_discoverable = True

            # Determine what changed
            auto_pair_changed = auto_pair is not None and auto_pair != current_auto_pair
            discoverable_changed = discoverable is not None and discoverable != current_discoverable

            # Build settings update
            settings_update = {"integrations": {"bluetooth": {}}}
            if auto_pair is not None:
                settings_update["integrations"]["bluetooth"]["autoPair"] = auto_pair
            if discoverable is not None:
                settings_update["integrations"]["bluetooth"]["discoverable"] = discoverable

            # Persist settings first
            logger.info(f"Updating Bluetooth settings: autoPair={auto_pair}, discoverable={discoverable}")
            try:
                self.settings_manager.update_settings(settings_update)
            except Exception as e:
                logger.error(f"Failed to persist Bluetooth settings: {e}")
                return {
                    "success": False,
                    "message": f"Failed to persist settings: {str(e)}"
                }

            # If services aren't running, settings will be applied on next start
            if not services_running:
                return {
                    "success": True,
                    "message": "Settings saved (will apply when Bluetooth is enabled)",
                    "autoPair": auto_pair,
                    "discoverable": discoverable
                }

            # Apply changes immediately if services are running
            details = []

            # Apply discoverable change via bluetoothctl
            if discoverable_changed:
                logger.info(f"Applying discoverable change: {discoverable}")
                adapter_success, adapter_output = self._set_adapter_discoverable(
                    discoverable=discoverable,
                    pairable=True
                )
                if adapter_success:
                    details.append(f"Discoverable set to {'on' if discoverable else 'off'}")
                else:
                    logger.warning(f"Failed to set discoverable: {adapter_output}")
                    details.append(f"Warning: Failed to set discoverable: {adapter_output}")

            # If auto-pair changed, restart bluetooth-init service
            if auto_pair_changed:
                logger.info(f"Auto-pair changed, restarting bluetooth-init service")
                # Restart bluetooth-init to apply new auto-pair setting
                restart_success, restart_output = self.controller.restart_service("bluetooth-init")
                if restart_success:
                    details.append(f"Auto-pair agent {'enabled' if auto_pair else 'disabled'} (service restarted)")
                    # Wait for service to initialize
                    time.sleep(3)
                else:
                    logger.error(f"Failed to restart bluetooth-init: {restart_output}")
                    return {
                        "success": False,
                        "message": f"Settings saved but failed to restart service: {restart_output}",
                        "details": "\n".join(details)
                    }

            return {
                "success": True,
                "message": "Settings updated and applied",
                "autoPair": auto_pair if auto_pair is not None else current_auto_pair,
                "discoverable": discoverable if discoverable is not None else current_discoverable,
                "details": "\n".join(details) if details else "Settings applied"
            }

        except Exception as e:
            logger.error(f"Failed to update Bluetooth settings: {e}")
            return {
                "success": False,
                "message": f"Error updating settings: {str(e)}"
            }


class SpotifyController:
    """Controls Spotify Connect (spotifyd) service"""

    def __init__(self, integration_controller: IntegrationController, settings_manager: SettingsManager = None):
        self.controller = integration_controller
        self.service_name = "spotifyd"
        self.config_file = SPOTIFYD_CONF
        self.settings_manager = settings_manager or SettingsManager()

    def enable(self) -> Dict[str, Any]:
        """Enable Spotify service"""
        # Start spotifyd first
        success, output = self.controller.start_service(self.service_name)

        # Also start the lifecycle manager (it monitors spotifyd and creates/removes streams)
        lifecycle_success, lifecycle_output = self.controller.start_service("spotify-stream-lifecycle-manager")

        # Also start the fifo keeper
        fifo_success, fifo_output = self.controller.start_service("spotify-fifo-keeper")

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "spotify": {
                            "enabled": True
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist Spotify enabled state: {e}")

        return {
            "success": success and lifecycle_success,
            "message": "Spotify enabled" if (success and lifecycle_success) else "Failed to enable Spotify",
            "details": f"spotifyd: {output.strip()}\nlifecycle-manager: {lifecycle_output.strip()}\nfifo-keeper: {fifo_output.strip()}"
        }

    def disable(self) -> Dict[str, Any]:
        """Disable Spotify service"""
        # Stop the lifecycle manager first
        lifecycle_success, lifecycle_output = self.controller.stop_service("spotify-stream-lifecycle-manager")

        # Stop the fifo keeper
        fifo_success, fifo_output = self.controller.stop_service("spotify-fifo-keeper")

        # Stop spotifyd last
        success, output = self.controller.stop_service(self.service_name)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "spotify": {
                            "enabled": False
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist Spotify disabled state: {e}")

        return {
            "success": success,
            "message": "Spotify disabled" if success else "Failed to disable Spotify",
            "details": f"spotifyd: {output.strip()}\nlifecycle-manager: {lifecycle_output.strip()}\nfifo-keeper: {fifo_output.strip()}"
        }

    def get_status(self) -> Dict[str, Any]:
        """Get Spotify service status"""
        return self.controller.get_service_status(self.service_name)

    def update_device_name(self, device_name: str) -> Dict[str, Any]:
        """Update Spotify device name in config and restart service"""
        try:
            # Validate device name
            if not device_name or len(device_name) > 50:
                return {
                    "success": False,
                    "message": "Invalid device name (must be 1-50 characters)"
                }

            # Escape special characters for sed
            device_name_escaped = device_name.replace('"', '\\"').replace('/', '\\/')

            # Use sed to update config (same approach as AirPlay)
            # Format: device_name = "Plum Audio"
            sed_pattern = f's/^device_name = ".*"/device_name = "{device_name_escaped}"/'
            sed_cmd = ["sed", "-i", sed_pattern, self.config_file]

            result = subprocess.run(sed_cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                logger.error(f"sed command failed: {result.stderr}")
                return {
                    "success": False,
                    "message": "Failed to update config file",
                    "details": result.stderr.strip()
                }

            logger.info(f"Updated Spotify device name to: {device_name}")

            # Restart service to apply changes
            success, output = self.controller.restart_service(self.service_name)

            if not success:
                logger.error(f"Failed to restart spotifyd: {output}")

            # Update settings to persist device name and enabled state
            # Note: restarting the service enables it, so we set enabled=True
            if success:
                try:
                    self.settings_manager.update_settings({
                        "integrations": {
                            "spotify": {
                                "deviceName": device_name,
                                "enabled": True
                            }
                        }
                    })
                except Exception as e:
                    logger.error(f"Failed to persist Spotify device name: {e}")

            return {
                "success": success,
                "message": f"Device name updated to '{device_name}'" if success else "Failed to restart Spotify service",
                "device_name": device_name if success else None,
                "details": output.strip()
            }

        except Exception as e:
            logger.error(f"Failed to update device name: {e}")
            return {
                "success": False,
                "message": f"Error updating device name: {str(e)}"
            }


class PlexampController:
    """Controls Plexamp stream lifecycle manager"""

    def __init__(self, integration_controller: IntegrationController, settings_manager: SettingsManager = None):
        self.controller = integration_controller
        # Note: Plexamp itself runs in separate Debian container
        # This controller only manages the lifecycle manager service
        self.lifecycle_service = "plexamp-stream-lifecycle-manager"
        self.settings_manager = settings_manager or SettingsManager()

    def _is_available(self) -> bool:
        """Check if Plexamp is available (configured in docker-compose)"""
        # Availability is determined by PLEXAMP_ENABLED env var
        # Check environment variable directly to handle changes between container restarts
        plexamp_enabled = os.getenv("PLEXAMP_ENABLED", "0").strip() in ("1", "true", "True", "TRUE", "yes", "Yes", "YES")

        # Update settings to keep them in sync (for frontend access)
        try:
            settings = self.settings_manager.get_settings()
            current_available = settings.get("integrations", {}).get("plexamp", {}).get("available", False)
            if current_available != plexamp_enabled:
                logger.info(f"Updating Plexamp availability from {current_available} to {plexamp_enabled}")
                self.settings_manager.update_settings({
                    "integrations": {
                        "plexamp": {
                            "available": plexamp_enabled
                        }
                    }
                })
        except Exception as e:
            logger.error(f"Failed to update Plexamp availability in settings: {e}")

        return plexamp_enabled

    def enable(self) -> Dict[str, Any]:
        """Enable Plexamp stream lifecycle manager"""
        if not self._is_available():
            return {
                "success": False,
                "message": "Plexamp is not available. Please configure PLEXAMP_ENABLED in docker-compose."
            }

        success, output = self.controller.start_service(self.lifecycle_service)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "plexamp": {
                            "enabled": True
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist Plexamp enabled state: {e}")

        return {
            "success": success,
            "message": "Plexamp enabled" if success else "Failed to enable Plexamp",
            "details": output.strip()
        }

    def disable(self) -> Dict[str, Any]:
        """Disable Plexamp stream lifecycle manager"""
        success, output = self.controller.stop_service(self.lifecycle_service)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {
                        "plexamp": {
                            "enabled": False
                        }
                    }
                })
            except Exception as e:
                logger.error(f"Failed to persist Plexamp disabled state: {e}")

        return {
            "success": success,
            "message": "Plexamp disabled" if success else "Failed to disable Plexamp",
            "details": output.strip()
        }

    def get_status(self) -> Dict[str, Any]:
        """Get Plexamp lifecycle manager status"""
        status = self.controller.get_service_status(self.lifecycle_service)
        # Add availability info to status
        status["available"] = self._is_available()
        return status


class DLNAController:
    """Controls DLNA/UPnP (gmrender-resurrect) service"""

    def __init__(self, integration_controller: IntegrationController, settings_manager: SettingsManager = None):
        self.controller = integration_controller
        self.service_name = "gmrender"
        self.device_name_file = DLNA_DEVICE_NAME_FILE
        self.settings_manager = settings_manager or SettingsManager()

    def enable(self) -> Dict[str, Any]:
        """Enable DLNA service"""
        success, output = self.controller.start_service(self.service_name)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {"dlna": {"enabled": True}}
                })
            except Exception as e:
                logger.error(f"Failed to persist DLNA enabled state: {e}")

        return {
            "success": success,
            "message": "DLNA enabled" if success else "Failed to enable DLNA",
            "details": output.strip()
        }

    def disable(self) -> Dict[str, Any]:
        """Disable DLNA service"""
        success, output = self.controller.stop_service(self.service_name)

        # Update settings to persist state
        if success:
            try:
                self.settings_manager.update_settings({
                    "integrations": {"dlna": {"enabled": False}}
                })
            except Exception as e:
                logger.error(f"Failed to persist DLNA disabled state: {e}")

        return {
            "success": success,
            "message": "DLNA disabled" if success else "Failed to disable DLNA",
            "details": output.strip()
        }

    def get_status(self) -> Dict[str, Any]:
        """Get DLNA service status"""
        return self.controller.get_service_status(self.service_name)

    def update_device_name(self, device_name: str) -> Dict[str, Any]:
        """Update DLNA device name by writing to file and restarting service"""
        try:
            # Validate device name
            if not device_name or len(device_name) > 50:
                return {
                    "success": False,
                    "message": "Invalid device name (must be 1-50 characters)"
                }

            # Write device name to file
            try:
                with open(self.device_name_file, 'w') as f:
                    f.write(device_name)
                logger.info(f"Updated DLNA device name file to: {device_name}")
            except Exception as e:
                logger.error(f"Failed to write device name file: {e}")
                return {
                    "success": False,
                    "message": f"Failed to write device name file: {str(e)}"
                }

            # Restart service to apply changes
            success, output = self.controller.restart_service(self.service_name)

            if not success:
                logger.error(f"Failed to restart gmrender: {output}")

            # Update settings to persist device name and enabled state
            if success:
                try:
                    self.settings_manager.update_settings({
                        "integrations": {
                            "dlna": {
                                "deviceName": device_name,
                                "enabled": True
                            }
                        }
                    })
                except Exception as e:
                    logger.error(f"Failed to persist DLNA device name: {e}")

            return {
                "success": success,
                "message": f"Device name updated to '{device_name}'" if success else "Failed to restart DLNA service",
                "device_name": device_name if success else None,
                "details": output.strip()
            }

        except Exception as e:
            logger.error(f"Failed to update device name: {e}")
            return {
                "success": False,
                "message": f"Error updating device name: {str(e)}"
            }


def create_integrations_blueprint(
    integration_controller: IntegrationController = None
) -> Blueprint:
    """Create Flask blueprint for integrations actions API"""

    if integration_controller is None:
        integration_controller = IntegrationController()

    airplay_controller = AirPlayController(integration_controller)
    bluetooth_controller = BluetoothController(integration_controller)
    spotify_controller = SpotifyController(integration_controller)
    dlna_controller = DLNAController(integration_controller)
    plexamp_controller = PlexampController(integration_controller)

    bp = Blueprint('integrations', __name__)

    # AirPlay endpoints
    @bp.route("/api/integrations/airplay/enable", methods=["POST"])
    def airplay_enable():
        """Enable AirPlay service"""
        try:
            result = airplay_controller.enable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"AirPlay enable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/airplay/disable", methods=["POST"])
    def airplay_disable():
        """Disable AirPlay service"""
        try:
            result = airplay_controller.disable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"AirPlay disable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/airplay/status", methods=["GET"])
    def airplay_status():
        """Get AirPlay service status"""
        try:
            result = airplay_controller.get_status()
            return jsonify(result)
        except Exception as e:
            logger.error(f"AirPlay status check failed: {e}")
            return jsonify({"running": False, "status": "error", "error": str(e)}), 500

    @bp.route("/api/integrations/airplay/device-name", methods=["POST"])
    def airplay_update_device_name():
        """Update AirPlay device name"""
        try:
            data = request.get_json()
            if not data or "deviceName" not in data:
                return jsonify({"success": False, "message": "deviceName is required"}), 400

            device_name = data["deviceName"]
            result = airplay_controller.update_device_name(device_name)

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"AirPlay device name update failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    # Bluetooth endpoints
    @bp.route("/api/integrations/bluetooth/enable", methods=["POST"])
    def bluetooth_enable():
        """Enable Bluetooth services"""
        try:
            result = bluetooth_controller.enable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Bluetooth enable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/bluetooth/disable", methods=["POST"])
    def bluetooth_disable():
        """Disable Bluetooth services"""
        try:
            result = bluetooth_controller.disable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Bluetooth disable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/bluetooth/status", methods=["GET"])
    def bluetooth_status():
        """Get Bluetooth service status"""
        try:
            result = bluetooth_controller.get_status()
            return jsonify(result)
        except Exception as e:
            logger.error(f"Bluetooth status check failed: {e}")
            return jsonify({"running": False, "status": "error", "error": str(e)}), 500

    @bp.route("/api/integrations/bluetooth/device-name", methods=["POST"])
    def bluetooth_update_device_name():
        """Update Bluetooth device name"""
        try:
            data = request.get_json()
            if not data or "deviceName" not in data:
                return jsonify({"success": False, "message": "deviceName is required"}), 400

            device_name = data["deviceName"]
            result = bluetooth_controller.update_device_name(device_name)

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Bluetooth device name update failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/bluetooth/settings", methods=["POST"])
    def bluetooth_update_settings():
        """Update Bluetooth settings (auto-pair and/or discoverable)"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"success": False, "message": "Request body is required"}), 400

            auto_pair = data.get("autoPair")
            discoverable = data.get("discoverable")

            if auto_pair is None and discoverable is None:
                return jsonify({"success": False, "message": "At least one of autoPair or discoverable is required"}), 400

            result = bluetooth_controller.update_settings(
                auto_pair=auto_pair,
                discoverable=discoverable
            )

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Bluetooth settings update failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    # Spotify endpoints
    @bp.route("/api/integrations/spotify/enable", methods=["POST"])
    def spotify_enable():
        """Enable Spotify service"""
        try:
            result = spotify_controller.enable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Spotify enable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/spotify/disable", methods=["POST"])
    def spotify_disable():
        """Disable Spotify service"""
        try:
            result = spotify_controller.disable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Spotify disable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/spotify/status", methods=["GET"])
    def spotify_status():
        """Get Spotify service status"""
        try:
            result = spotify_controller.get_status()
            return jsonify(result)
        except Exception as e:
            logger.error(f"Spotify status check failed: {e}")
            return jsonify({"running": False, "status": "error", "error": str(e)}), 500

    @bp.route("/api/integrations/spotify/device-name", methods=["POST"])
    def spotify_update_device_name():
        """Update Spotify device name"""
        try:
            data = request.get_json()
            if not data or "deviceName" not in data:
                return jsonify({"success": False, "message": "deviceName is required"}), 400

            device_name = data["deviceName"]
            result = spotify_controller.update_device_name(device_name)

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Spotify device name update failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    # DLNA endpoints
    @bp.route("/api/integrations/dlna/enable", methods=["POST"])
    def dlna_enable():
        """Enable DLNA service"""
        try:
            result = dlna_controller.enable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"DLNA enable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/dlna/disable", methods=["POST"])
    def dlna_disable():
        """Disable DLNA service"""
        try:
            result = dlna_controller.disable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"DLNA disable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/dlna/status", methods=["GET"])
    def dlna_status():
        """Get DLNA service status"""
        try:
            result = dlna_controller.get_status()
            return jsonify(result)
        except Exception as e:
            logger.error(f"DLNA status check failed: {e}")
            return jsonify({"running": False, "status": "error", "error": str(e)}), 500

    @bp.route("/api/integrations/dlna/device-name", methods=["POST"])
    def dlna_update_device_name():
        """Update DLNA device name"""
        try:
            data = request.get_json()
            if not data or "deviceName" not in data:
                return jsonify({"success": False, "message": "deviceName is required"}), 400

            device_name = data["deviceName"]
            result = dlna_controller.update_device_name(device_name)

            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"DLNA device name update failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    # Plexamp endpoints
    @bp.route("/api/integrations/plexamp/enable", methods=["POST"])
    def plexamp_enable():
        """Enable Plexamp stream lifecycle manager"""
        try:
            result = plexamp_controller.enable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Plexamp enable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/plexamp/disable", methods=["POST"])
    def plexamp_disable():
        """Disable Plexamp stream lifecycle manager"""
        try:
            result = plexamp_controller.disable()
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        except Exception as e:
            logger.error(f"Plexamp disable failed: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/integrations/plexamp/status", methods=["GET"])
    def plexamp_status():
        """Get Plexamp lifecycle manager status"""
        try:
            result = plexamp_controller.get_status()
            return jsonify(result)
        except Exception as e:
            logger.error(f"Plexamp status check failed: {e}")
            return jsonify({"running": False, "status": "error", "available": False, "error": str(e)}), 500

    return bp


# For standalone testing
if __name__ == "__main__":
    from flask import Flask
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)

    controller = IntegrationController()
    bp = create_integrations_blueprint(controller)
    app.register_blueprint(bp)

    print("Integrations API running on http://localhost:5003")
    app.run(host="0.0.0.0", port=5003, debug=True)
