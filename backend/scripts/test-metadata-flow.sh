#!/bin/bash
# Test script to verify metadata flow from control script to Snapcast

echo "=== Testing Metadata Flow ==="
echo ""

echo "1. Check control script logs for sent metadata:"
echo "Looking for [Snapcast] Metadata → lines..."
docker exec plum-snapcast-server tail -20 /tmp/airplay-control-script.log | grep -A 2 "\[Snapcast\] Metadata"
echo ""

echo "2. Check what stream ID the control script is using:"
docker exec plum-snapcast-server tail -20 /tmp/airplay-control-script.log | grep "stream="
echo ""

echo "3. Query Snapcast for current stream status and properties:"
echo '{"id":1,"jsonrpc":"2.0","method":"Server.GetStatus"}' | \
  docker exec -i plum-snapcast-server nc localhost 1780 | \
  python3 -m json.tool | \
  grep -A 30 '"streams"'
echo ""

echo "4. Check if Snapcast received metadata (look for properties.metadata):"
echo '{"id":2,"jsonrpc":"2.0","method":"Server.GetStatus"}' | \
  docker exec -i plum-snapcast-server nc localhost 1780 | \
  python3 -c "import json, sys; data=json.load(sys.stdin); streams=data.get('result',{}).get('server',{}).get('streams',[]);
for s in streams:
    print(f\"Stream: {s['id']}\");
    print(f\"  Properties: {s.get('properties', {})}\");
    print(f\"  Metadata: {s.get('properties', {}).get('metadata', 'NONE')}\");
    print()" 2>/dev/null || echo "Error parsing JSON"

echo ""
echo "5. Check metadata-debug-server /metadata endpoint:"
docker exec plum-snapcast-server curl -s http://localhost:8080/metadata
echo ""
