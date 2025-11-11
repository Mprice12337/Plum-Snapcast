#!/bin/bash
# Check if shairport-sync is caching any cover art files

echo "============================================"
echo "Shairport-Sync Cover Art Cache Inspector"
echo "============================================"
echo ""

CACHE_DIR="/tmp/shairport-sync/.cache/coverart"

echo "Cache directory: $CACHE_DIR"
echo ""

if [ ! -d "$CACHE_DIR" ]; then
    echo "ERROR: Cache directory doesn't exist!"
    echo "This means shairport-sync hasn't tried to cache any artwork yet."
    exit 1
fi

echo "Directory contents:"
ls -lah "$CACHE_DIR"
echo ""

FILE_COUNT=$(find "$CACHE_DIR" -type f 2>/dev/null | wc -l)
echo "Total files in cache: $FILE_COUNT"
echo ""

if [ "$FILE_COUNT" -eq 0 ]; then
    echo "❌ No cover art files found in cache."
    echo ""
    echo "This means shairport-sync is NOT receiving or caching album artwork."
    echo ""
    echo "Possible reasons:"
    echo "1. The audio source isn't sending cover art via AirPlay"
    echo "2. Try playing from Apple Music app (known to send artwork)"
    echo "3. Some streaming apps don't send artwork over AirPlay"
else
    echo "✅ Found $FILE_COUNT cover art file(s) in cache!"
    echo ""
    echo "Recent files:"
    find "$CACHE_DIR" -type f -exec ls -lh {} \; | head -5
    echo ""

    # Show the newest file
    NEWEST=$(find "$CACHE_DIR" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [ -n "$NEWEST" ]; then
        echo "Newest file: $NEWEST"
        file "$NEWEST" 2>/dev/null || echo "(file command not available)"
    fi
fi

echo ""
echo "============================================"
