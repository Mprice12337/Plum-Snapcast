#!/bin/bash
# Quick diagnostic script to see raw metadata from shairport-sync
# This will help us understand what's actually being sent

METADATA_PIPE="/tmp/shairport-sync-metadata"

if [ ! -p "$METADATA_PIPE" ]; then
    echo "Metadata pipe not found: $METADATA_PIPE"
    exit 1
fi

echo "Reading raw metadata from pipe..."
echo "Play something via AirPlay and watch for PICT-related codes"
echo "Press Ctrl+C to stop"
echo "================================"

# Read and parse XML to show codes and data lengths
cat "$METADATA_PIPE" | while IFS= read -r line; do
    # Look for item tags
    if echo "$line" | grep -q "<item>"; then
        buffer="$line"
        # Keep reading until we get the closing tag
        while ! echo "$buffer" | grep -q "</item>"; do
            IFS= read -r line
            buffer="$buffer$line"
        done

        # Extract type and code
        type_hex=$(echo "$buffer" | grep -oP '(?<=<type encoding="base64">)[^<]+' | head -1)
        code_hex=$(echo "$buffer" | grep -oP '(?<=<code encoding="base64">)[^<]+' | head -1)

        if [ -n "$type_hex" ] && [ -n "$code_hex" ]; then
            type=$(echo "$type_hex" | base64 -d 2>/dev/null)
            code=$(echo "$code_hex" | base64 -d 2>/dev/null)

            # Get data length if present
            data=$(echo "$buffer" | grep -oP '(?<=<data encoding="base64">)[^<]+' | head -1)
            if [ -n "$data" ]; then
                data_len=${#data}

                # Show details for picture-related codes
                if [[ "$code" == "PICT" ]] || [[ "$code" == "pcst" ]] || [[ "$code" == "pcen" ]]; then
                    echo ">>> PICTURE CODE: type='$type' code='$code' data_length=$data_len"

                    # For PICT, try to identify image format
                    if [[ "$code" == "PICT" ]]; then
                        # Decode first few bytes to check magic number
                        magic=$(echo "$data" | base64 -d 2>/dev/null | head -c 4 | xxd -p)
                        echo "    Image magic bytes: $magic"
                        if [[ "$magic" == ffd8ff* ]]; then
                            echo "    Format: JPEG"
                        elif [[ "$magic" == 89504e47* ]]; then
                            echo "    Format: PNG"
                        fi
                    fi
                else
                    # Show other metadata more briefly
                    echo "type='$type' code='$code' data_length=$data_len"
                fi
            else
                echo "type='$type' code='$code' (no data)"
            fi
        fi
    fi
done
