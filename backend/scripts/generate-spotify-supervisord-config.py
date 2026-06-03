#!/usr/bin/env python3
"""
Generate supervisord configuration for Spotify Connect multi-instance endpoints
Reads from settings.json and creates supervisord program sections for each endpoint
"""

import json
import os
import sys

SETTINGS_FILE = "/app/data/settings.json"
OUTPUT_FILE = "/app/supervisord/spotify-multi-instance.ini"

PROGRAM_TEMPLATE = """
# ============================================================================
# SPOTIFY CONNECT INSTANCE {instance_id} ({description})
# ============================================================================

[program:spotifyd-{instance_id}]
command=/bin/bash /app/scripts/start-spotifyd.sh {instance_id}
user=snapcast
directory=/app
priority={priority}
autostart={autostart}
autorestart=true
startsecs=10
startretries=3
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/supervisord/spotifyd-{instance_id}.log
stdout_logfile_maxbytes=50MB
stderr_logfile=/var/log/supervisord/spotifyd-{instance_id}_err.log
stderr_logfile_maxbytes=10MB

[program:spotify-{instance_id}-fifo-keeper]
command=/bin/bash /app/scripts/spotify-fifo-keeper.sh {instance_id}
user=snapcast
directory=/app
priority=20
autostart={autostart}
autorestart=true
startsecs=5
startretries=999
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/supervisord/spotify-{instance_id}-fifo-keeper.log
stderr_logfile=/var/log/supervisord/spotify-{instance_id}-fifo-keeper_err.log

[program:spotify-{instance_id}-lifecycle-manager]
command=/usr/bin/python3 /app/scripts/spotify-stream-lifecycle-manager.py --instance-id {instance_id}
user=snapcast
directory=/app
priority=35
autostart={autostart}
autorestart=true
startsecs=5
startretries=3
stdout_logfile=/var/log/supervisord/spotify-{instance_id}-lifecycle.log
stdout_logfile_maxbytes=10MB
stderr_logfile=/var/log/supervisord/spotify-{instance_id}-lifecycle_err.log
stderr_logfile_maxbytes=10MB
environment=PYTHONUNBUFFERED="1"
"""

def main():
    try:
        # Load settings
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)

        endpoints = settings.get("integrations", {}).get("spotify", {}).get("endpoints", [])

        if not endpoints:
            print("No Spotify Connect endpoints configured, creating empty config", file=sys.stderr)
            with open(OUTPUT_FILE, 'w') as f:
                f.write("# Multi-Instance Spotify Connect Configuration\n")
                f.write("# No endpoints configured\n")
            return 0

        # Generate config
        config_lines = ["# Multi-Instance Spotify Connect Configuration"]
        config_lines.append(f"# Generated from settings.json with {len(endpoints)} endpoint(s)")
        config_lines.append("# Each endpoint can be used simultaneously by different users/accounts\n")

        for endpoint in endpoints:
            instance_id = endpoint.get("id")
            device_name = endpoint.get("deviceName", f"Endpoint {instance_id}")
            enabled = endpoint.get("enabled", False)
            zeroconf_port = endpoint.get("zeroconfPort", 5354)

            # Determine description
            description = f"{device_name} - zeroconf port {zeroconf_port}, D-Bus/MPRIS"
            autostart = "true" if enabled else "false"

            # Sequential startup to prevent MPRIS name race condition
            # Instance 1 must start first to claim base MPRIS name
            # Large gap (30 points) ensures full D-Bus registration before next instance starts
            priority = 40 + (int(instance_id) - 1) * 30

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
