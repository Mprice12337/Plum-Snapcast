#!/usr/bin/env python3
"""
Debug: Shows the actual JSON being sent in notifications
"""

import sys
import json

# Read the last notification from the control script log
with open('/tmp/airplay-control-script.log', 'r') as f:
    lines = f.readlines()

print("=" * 70)
print("RECENT CONTROL SCRIPT ACTIVITY")
print("=" * 70)
print()

# Show last 30 lines
for line in lines[-30:]:
    print(line.rstrip())

print()
print("=" * 70)
print("NOTE: Notifications are sent to snapserver via stdout")
print("Check snapserver logs to see if it's receiving them:")
print("  tail -50 /var/log/supervisord/snapserver.log")
print("=" * 70)
