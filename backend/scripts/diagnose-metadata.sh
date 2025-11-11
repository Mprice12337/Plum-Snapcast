#!/bin/bash
# Comprehensive metadata debugging script
# Run this while playing AirPlay audio

echo "============================================"
echo "Metadata Debug Server Diagnostics"
echo "============================================"
echo ""

echo "1. Checking if metadata-debug-server is running..."
docker exec plum-snapcast-server supervisorctl status metadata-debug-server
echo ""

echo "2. Checking metadata pipe exists..."
docker exec plum-snapcast-server ls -la /tmp/shairport-sync-metadata
echo ""

echo "3. Checking recent metadata server logs (last 50 lines)..."
docker exec plum-snapcast-server tail -50 /var/log/supervisord/metadata-debug-server.log
echo ""

echo "4. Checking shairport-sync is running..."
docker exec plum-snapcast-server ps aux | grep shairport | grep -v grep
echo ""

echo "5. Testing metadata endpoints..."
echo "   - Checking /status endpoint:"
curl -s http://localhost:8080/status 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "Server not responding"
echo ""

echo "6. Checking for PICT messages in last 100 log lines..."
docker exec plum-snapcast-server tail -100 /var/log/supervisord/metadata-debug-server.log | grep -i "pict\|picture\|artwork"
echo ""

echo "============================================"
echo "Next steps:"
echo "1. Play something via AirPlay if not already playing"
echo "2. Wait 5 seconds"
echo "3. Run this script again to see if PICT messages appear"
echo "4. Check: curl http://localhost:8080/metadata"
echo "============================================"
