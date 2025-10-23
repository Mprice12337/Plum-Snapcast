#!/bin/bash
echo "=== Testing AirPlay Registration ==="

# First, check if shairport-sync can register with Avahi
echo "1. Testing Avahi registration directly..."
/usr/local/bin/shairport-sync -t -vv 2>&1 | head -20

echo -e "\n2. Current Avahi services..."
avahi-browse -at 2>&1 | timeout 3 grep -E "raop|AirTunes|Plum" || echo "No AirPlay services found"

echo -e "\n3. Checking Avahi daemon..."
if [ -S /var/run/avahi-daemon/socket ]; then
    echo "Avahi socket found at /var/run/avahi-daemon/socket"
else
    echo "No Avahi socket found!"
fi

echo -e "\n4. Testing manual service registration..."
timeout 5 avahi-publish-service "Test_Plum_Audio" _raop._tcp 5000 "tp=TCP,UDP" "sm=false" "ek=1" "et=0,1" "cn=0,1" "ch=2" "ss=16" "sr=44100" "vn=3" "txtvers=1" &
PID=$!
sleep 2
avahi-browse -r _raop._tcp 2>&1 | timeout 3 grep "Test_Plum" || echo "Manual registration failed"
kill $PID 2>/dev/null

echo -e "\n5. Shairport-sync config check..."
/usr/local/bin/shairport-sync -c /app/config/shairport-sync.conf -V