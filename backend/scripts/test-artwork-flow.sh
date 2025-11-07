#!/bin/bash
# Debug script to test artwork flow through the system

set -e

echo "==================================="
echo "Artwork Flow Debug Test"
echo "==================================="
echo

# Test 1: Verify coverart directory exists and is writable
echo "Test 1: Checking coverart directory..."
COVERART_DIR="/usr/share/snapserver/snapweb/coverart"
if [ -d "$COVERART_DIR" ]; then
    echo "✓ Directory exists: $COVERART_DIR"
    ls -la "$COVERART_DIR" | head -10
    echo "Total artwork files: $(ls -1 "$COVERART_DIR" 2>/dev/null | wc -l)"
else
    echo "✗ Directory missing: $COVERART_DIR"
fi
echo

# Test 2: Create test artwork file
echo "Test 2: Creating test artwork..."
TEST_HASH="test_$(date +%s)"
TEST_FILE="$COVERART_DIR/${TEST_HASH}.jpg"

# Create a simple 100x100 red square JPEG (base64)
base64 -d > "$TEST_FILE" << 'EOF'
/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAIBAQIBAQICAgICAgICAwUDAwMDAwYEBAMFBwYHBwcGBwcICQsJCAgKCAcHCg0KCgsMDAwMBwkODw0MDgsMDAz/2wBDAQICAgMDAwYDAwYMCAcIDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAz/wAARCABkAGQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlbaWmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD9/KKKKACiiigAooooAKKKKACiiigD/9k=
EOF

echo "✓ Created test artwork: $TEST_FILE"
ls -lh "$TEST_FILE"
echo

# Test 3: Simulate sending artwork via control script
echo "Test 3: Simulating metadata update with artwork..."
echo "Manual test: Send a JSON-RPC notification"
echo
echo "To manually test, run this in another terminal:"
echo "echo '{\"jsonrpc\":\"2.0\",\"method\":\"Plugin.Stream.Player.Properties\",\"params\":{\"metadata\":{\"name\":\"Test Track\",\"artist\":[\"Test Artist\"],\"album\":\"Test Album\",\"mpris:artUrl\":\"/coverart/${TEST_HASH}.jpg\"},\"artUrl\":\"/coverart/${TEST_HASH}.jpg\",\"canPlay\":true,\"canPause\":true,\"canGoNext\":true,\"canGoPrevious\":true,\"canSeek\":false}}' | nc -U /var/run/snapserver/control"
echo

# Test 4: Check control script log for artwork events
echo "Test 4: Recent artwork events in control script log..."
if [ -f /tmp/airplay-control-script.log ]; then
    echo "Last 20 artwork-related log lines:"
    grep -i "PICT\|artUrl\|Cover art" /tmp/airplay-control-script.log | tail -20
else
    echo "✗ Control script log not found"
fi
echo

# Test 5: Check what artwork the stream currently has
echo "Test 5: Current stream properties (via snapcast API)..."
echo "Run this command to check stream properties:"
echo "curl -s http://localhost:1780/jsonrpc -d '{\"id\":1,\"jsonrpc\":\"2.0\",\"method\":\"Server.GetStatus\"}' | jq '.result.server.streams[0].properties'"
echo

# Test 6: List most recent artwork files
echo "Test 6: Most recent artwork files..."
ls -lt "$COVERART_DIR" | head -10
echo

# Test 7: Check if artwork is accessible via HTTP
echo "Test 7: Testing artwork HTTP access..."
LATEST_ART=$(ls -t "$COVERART_DIR"/*.jpg 2>/dev/null | head -1)
if [ -n "$LATEST_ART" ]; then
    FILENAME=$(basename "$LATEST_ART")
    echo "Testing access to: /coverart/$FILENAME"
    echo "Run: curl -I http://localhost:1780/coverart/$FILENAME"
    echo "Or:  curl -I https://localhost:1788/coverart/$FILENAME"
else
    echo "No artwork files found"
fi
echo

# Test 8: Watch for new artwork in real-time
echo "Test 8: Monitor for new artwork (Ctrl+C to stop)..."
echo "Watching: $COVERART_DIR"
echo "Play a new track on AirPlay to see artwork being created..."
echo
inotifywait -m -e create,modify "$COVERART_DIR" 2>/dev/null || echo "inotifywait not available, install inotify-tools to use this feature"

echo
echo "==================================="
echo "Debug test complete"
echo "==================================="
