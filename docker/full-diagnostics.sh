#!/bin/bash
echo "=== Docker Container Health ==="
docker inspect plum-snapcast-server | grep -A 5 "Health"

echo -e "\n=== Test Snapserver HTTP ==="
docker exec plum-snapcast-server curl -f http://localhost:1780/jsonrpc 2>&1 | head -n 5

echo -e "\n=== Listening Ports ==="
docker exec plum-snapcast-server netstat -tlnp 2>/dev/null || docker exec plum-snapcast-server ss -tlnp 2>/dev/null || echo "No netstat/ss available"

echo -e "\n=== FIFO Pipe Status ==="
docker exec plum-snapcast-server ls -la /tmp/snapfifo
docker exec plum-snapcast-server file /tmp/snapfifo 2>/dev/null || echo "file command not available"

echo -e "\n=== Avahi Services (5 second timeout) ==="
timeout 5 docker exec plum-snapcast-server avahi-browse -at 2>&1 || echo "Avahi browse failed or timed out"

echo -e "\n=== Running Processes ==="
docker exec plum-snapcast-server ps aux | grep -E 'dbus|avahi|snap|shairport' | grep -v grep

echo -e "\n=== Shairport-Sync Logs (last 30 lines) ==="
docker exec plum-snapcast-server tail -n 30 /var/log/supervisord/shairport.log 2>/dev/null || echo "No shairport log"

echo -e "\n=== Shairport-Sync Error Logs ==="
docker exec plum-snapcast-server tail -n 20 /var/log/supervisord/shairport_err.log 2>/dev/null || echo "No error log"

echo -e "\n=== Snapserver Config (sources) ==="
docker exec plum-snapcast-server cat /app/config/snapserver.conf | grep -A 3 "^\[" || echo "Can't read config"

echo -e "\n=== Network Mode ==="
docker inspect plum-snapcast-server | grep NetworkMode

echo -e "\n=== Supervisord Status ==="
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status