#!/usr/bin/env python3
"""
Generate supervisord configuration for DLNA/UPnP multi-instance endpoints
Reads from settings.json and creates supervisord program sections for each endpoint
"""

import json
import os
import sys

SETTINGS_FILE = "/app/data/settings.json"
OUTPUT_FILE = "/app/supervisord/dlna-multi-instance.ini"

PROGRAM_TEMPLATE = """
# ============================================================================
# DLNA/UPnP INSTANCE {instance_id} ({description})
# ============================================================================

[program:gmrender-{instance_id}]
command=/bin/sh -c 'UUID_ARG=""; if [ -n "{uuid}" ]; then UUID_ARG="--uuid {uuid}"; fi; sleep 5 && /usr/local/bin/gmediarender --friendly-name "{device_name}" $UUID_ARG --port {port} --gstout-audiopipe "audioresample ! audio/x-raw,rate=44100,format=S16LE,channels=2 ! filesink location=/tmp/dlna-{instance_id}-fifo" --gstout-audiodevice "" --logfile stdout'
user=snapcast
directory=/app
environment=HOME="/app",GST_DEBUG="2",DISPLAY=":0"
priority={priority}
autostart={autostart}
autorestart=true
startsecs=10
startretries=3
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/supervisord/gmrender-{instance_id}.log
stdout_logfile_maxbytes=50MB
stderr_logfile=/var/log/supervisord/gmrender-{instance_id}_err.log
stderr_logfile_maxbytes=10MB

[program:dlna-{instance_id}-fifo-keeper]
command=/bin/bash /app/scripts/dlna-fifo-keeper.sh {instance_id}
user=snapcast
directory=/app
priority=20
autostart={autostart}
autorestart=true
startsecs=5
startretries=999
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/supervisord/dlna-{instance_id}-fifo-keeper.log
stderr_logfile=/var/log/supervisord/dlna-{instance_id}-fifo-keeper_err.log

[program:dlna-{instance_id}-lifecycle-manager]
command=/usr/bin/python3 /app/scripts/dlna-stream-lifecycle-manager.py --instance-id {instance_id}
user=snapcast
directory=/app
priority=35
autostart={autostart}
autorestart=true
startsecs=5
startretries=3
stdout_logfile=/var/log/supervisord/dlna-{instance_id}-lifecycle.log
stdout_logfile_maxbytes=10MB
stderr_logfile=/var/log/supervisord/dlna-{instance_id}-lifecycle_err.log
stderr_logfile_maxbytes=10MB
environment=PYTHONUNBUFFERED="1"

[program:dlna-{instance_id}-metadata-bridge]
command=/usr/bin/python3 /app/scripts/gmrender-metadata-bridge.py --instance-id {instance_id}
user=snapcast
directory=/app
priority=50
autostart={autostart}
autorestart=true
startsecs=5
startretries=3
stdout_logfile=/var/log/supervisord/dlna-{instance_id}-metadata-bridge.log
stdout_logfile_maxbytes=10MB
stderr_logfile=/var/log/supervisord/dlna-{instance_id}-metadata-bridge_err.log
stderr_logfile_maxbytes=10MB
environment=PYTHONUNBUFFERED="1"
"""

def main():
    try:
        # Load settings
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)

        endpoints = settings.get("integrations", {}).get("dlna", {}).get("endpoints", [])

        if not endpoints:
            print("No DLNA endpoints configured, creating empty config", file=sys.stderr)
            with open(OUTPUT_FILE, 'w') as f:
                f.write("# Multi-Instance DLNA/UPnP Configuration\n")
                f.write("# No endpoints configured\n")
            return 0

        # Generate config
        config_lines = ["# Multi-Instance DLNA/UPnP Configuration"]
        config_lines.append(f"# Generated from settings.json with {len(endpoints)} endpoint(s)")
        config_lines.append("# Each endpoint can be used simultaneously by different DLNA/UPnP clients\n")

        for endpoint in endpoints:
            instance_id = endpoint.get("id")
            device_name = endpoint.get("deviceName", f"Plum Audio {instance_id}")
            enabled = endpoint.get("enabled", True)
            port = endpoint.get("port", 49494)
            uuid = endpoint.get("uuid", "")

            # Determine description
            description = f"{device_name} - UPnP port {port}"
            autostart = "true" if enabled else "false"

            # Priority to ensure gmrender starts before bridges
            priority = 50 + (int(instance_id) - 1) * 10

            # Add program section
            section = PROGRAM_TEMPLATE.format(
                instance_id=instance_id,
                description=description,
                device_name=device_name,
                port=port,
                uuid=uuid,
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
