#!/bin/sh
set -e

# Check if snapserver API is responding
RESPONSE=$(curl --silent --max-time 5 -X POST \
    -d '{"id":1,"jsonrpc":"2.0","method":"Server.GetStatus"}' \
    http://localhost:1780/jsonrpc 2>/dev/null || echo "")

if echo "${RESPONSE}" | grep -q "snapserver"; then
    echo "✅ Snapserver API healthy"
    exit 0
else
    echo "❌ Snapserver API not responding"
    exit 1
fi