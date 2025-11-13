#!/bin/bash
# Snapcast Server Diagnostic Script
# Run this on the Raspberry Pi to diagnose Snapcast issues

echo "============================================================"
echo "Snapcast Server Diagnostic"
echo "============================================================"
echo ""

echo "1. Check if container is running:"
docker ps | grep snapcast
echo ""

echo "2. Check supervisord status (all services):"
docker exec plum-snapcast-server supervisorctl -c /app/supervisord/supervisord.conf status
echo ""

echo "3. Check if snapserver process is running:"
docker exec plum-snapcast-server ps aux | grep snapserver | grep -v grep
echo ""

echo "4. Check listening ports inside container:"
docker exec plum-snapcast-server netstat -tlnp 2>/dev/null | grep -E "snapserver|1780|1788" || \
docker exec plum-snapcast-server ss -tlnp 2>/dev/null | grep -E "snapserver|1780|1788"
echo ""

echo "5. Check snapserver logs:"
echo "--- Last 30 lines of snapserver log ---"
docker exec plum-snapcast-server tail -30 /var/log/supervisord/snapserver*.log 2>/dev/null || \
docker logs plum-snapcast-server 2>&1 | grep -i snapserver | tail -30
echo ""

echo "6. Check Snapcast configuration:"
docker exec plum-snapcast-server cat /app/config/snapserver.conf 2>/dev/null | head -40
echo ""

echo "7. Test connection to Snapcast from inside container:"
docker exec plum-snapcast-server sh -c 'echo "test" | nc -w 2 localhost 1780' 2>&1
echo ""

echo "8. Test connection to Snapcast from host:"
nc -z -w 2 localhost 1780 && echo "✓ Port 1780 accessible from host" || echo "✗ Port 1780 NOT accessible from host"
nc -z -w 2 localhost 1788 && echo "✓ Port 1788 accessible from host" || echo "✗ Port 1788 NOT accessible from host"
echo ""

echo "9. Check Docker port mappings:"
docker port plum-snapcast-server
echo ""

echo "10. Check network mode:"
docker inspect plum-snapcast-server | grep -A 5 NetworkMode
echo ""

echo "============================================================"
echo "Diagnostic complete"
echo "============================================================"
