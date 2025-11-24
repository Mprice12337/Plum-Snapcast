#!/bin/bash
# Quick timeline feature test script

echo "=== Plum-Snapcast Timeline Feature Test ==="
echo ""

echo "1. Checking containers..."
docker ps | grep plum

echo ""
echo "2. Checking control scripts..."
docker exec plum-snapcast-server ps aux | grep control-script | grep -v grep

echo ""
echo "3. Recent log activity (last 5 lines each):"
for source in spotify airplay bluetooth dlna plexamp; do
    echo "--- $source ---"
    docker exec plum-snapcast-server tail -5 /tmp/${source}-control-script.log 2>/dev/null || echo "Not available"
done

echo ""
echo "4. Snapcast streams with position info:"
echo '{"jsonrpc":"2.0","method":"Server.GetStatus","id":1}' | \
  docker exec -i plum-snapcast-server nc localhost 1705 | \
  jq -r '.result.server.streams[] | "Stream: \(.id) | Position: \(.properties.position // 0)ms | canSeek: \(.properties.canSeek // false)"' 2>/dev/null || echo "jq not available - install with: sudo apt install jq"

echo ""
echo "=== Test Complete ==="
