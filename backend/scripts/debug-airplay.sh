#!/bin/bash
echo "=== Checking AirPlay Service Advertisement ==="
echo "1. Avahi daemon status:"
ps aux | grep avahi

echo -e "\n2. Shairport-sync status:"
ps aux | grep shairport

echo -e "\n3. Published services:"
avahi-browse -at | grep -E "AirTunes|raop" || echo "No AirPlay services found"

echo -e "\n4. Port 5000 listener:"
netstat -tlnp | grep 5000 || ss -tlnp | grep 5000

echo -e "\n5. Shairport-sync test:"
/usr/local/bin/shairport-sync -V

echo -e "\n6. Manual test - try advertising:"
/usr/local/bin/shairport-sync --configfile=/app/config/shairport-sync.conf -v -d