#!/usr/bin/env python3
"""
Generate supervisord configuration for AirPlay multi-instance endpoints
Reads from settings.json and creates supervisord program sections for each endpoint
"""

import json
import os
import sys

SETTINGS_FILE = "/app/data/settings.json"
OUTPUT_FILE = "/app/supervisord/airplay-multi-instance.ini"

PROGRAM_TEMPLATE = """
# ============================================================================
# AIRPLAY INSTANCE {instance_id} ({description})
# ============================================================================

[program:shairport-sync-{instance_id}]
command=/usr/local/bin/shairport-sync --configfile=/app/config/shairport-sync-{instance_id}.conf
user=root
directory=/app
environment=HOME="/app"
priority={priority}
autostart={autostart}
autorestart=true
startsecs=5
startretries=3
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/supervisord/shairport-{instance_id}.log
stdout_logfile_maxbytes=50MB
stderr_logfile=/var/log/supervisord/shairport-{instance_id}_err.log
stderr_logfile_maxbytes=10MB

[program:airplay-{instance_id}-fifo-keeper]
command=/bin/bash /app/scripts/airplay-multi-fifo-keeper.sh {instance_id}
user=snapcast
directory=/app
priority=20
autostart={autostart}
autorestart=true
startsecs=5
startretries=999
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/supervisord/airplay-{instance_id}-fifo-keeper.log
stderr_logfile=/var/log/supervisord/airplay-{instance_id}-fifo-keeper_err.log

[program:airplay-{instance_id}-lifecycle-manager]
command=/usr/bin/python3 /app/scripts/stream-lifecycle-manager.py --instance-id {instance_id}
user=snapcast
directory=/app
priority=35
autostart={autostart}
autorestart=true
startsecs=5
startretries=3
stdout_logfile=/var/log/supervisord/airplay-{instance_id}-lifecycle.log
stdout_logfile_maxbytes=10MB
stderr_logfile=/var/log/supervisord/airplay-{instance_id}-lifecycle_err.log
stderr_logfile_maxbytes=10MB
environment=PYTHONUNBUFFERED="1"
"""

def main():
    try:
        # Load settings
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)

        endpoints = settings.get("integrations", {}).get("airplay", {}).get("endpoints", [])

        if not endpoints:
            print("No AirPlay endpoints configured, creating empty config", file=sys.stderr)
            with open(OUTPUT_FILE, 'w') as f:
                f.write("# Multi-Instance AirPlay Configuration\n")
                f.write("# No endpoints configured\n")
            return 0

        # Generate config
        config_lines = ["# Multi-Instance AirPlay Configuration"]
        config_lines.append(f"# Generated from settings.json with {len(endpoints)} endpoint(s)")
        config_lines.append("# Each endpoint can be used simultaneously by different devices/rooms\n")

        for endpoint in endpoints:
            instance_id = endpoint.get("id")
            device_name = endpoint.get("deviceName", f"Endpoint {instance_id}")
            enabled = endpoint.get("enabled", True)
            port = endpoint.get("port", 5050)

            # Determine description
            if instance_id == "1":
                dbus_note = "D-Bus enabled for control"
            else:
                dbus_note = "D-Bus disabled"

            description = f"{device_name} - port {port}, {dbus_note}"
            autostart = "true" if enabled else "false"

            # Calculate priority to ensure sequential startup (avoid MPRIS name race condition)
            # Instance 1 must start first to claim base MPRIS name before instance 2+ try
            priority = 40 + (int(instance_id) - 1) * 10

            # Add program section
            section = PROGRAM_TEMPLATE.format(
                instance_id=instance_id,
                description=description,
                autostart=autostart,
                priority=priority
            )
            config_lines.append(section)

        # Write config
        output_content = "\n".join(config_lines)
        with open(OUTPUT_FILE, 'w') as f:
            f.write(output_content)

        # Set ownership
        try:
            os.chown(OUTPUT_FILE, 1000, 1000)  # snapcast:snapcast
            os.chmod(OUTPUT_FILE, 0o644)
        except Exception as e:
            print(f"Warning: Could not set ownership: {e}", file=sys.stderr)

        print(f"Generated supervisord config with {len(endpoints)} endpoint(s)")
        return 0

    except Exception as e:
        print(f"Error generating supervisord config: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
