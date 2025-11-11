#!/usr/bin/env python3
"""
Raw metadata inspector - shows the actual XML being sent
This will help us see if PICT elements exist but are empty
"""

import sys
import time
from pathlib import Path

METADATA_PIPE = "/tmp/shairport-sync-metadata"

def main():
    print("Raw Metadata XML Inspector", flush=True)
    print("=" * 60, flush=True)

    if not Path(METADATA_PIPE).exists():
        print(f"ERROR: Metadata pipe not found: {METADATA_PIPE}", flush=True)
        sys.exit(1)

    print(f"Reading from: {METADATA_PIPE}", flush=True)
    print("Play something via AirPlay and watch for PICT items...", flush=True)
    print("=" * 60, flush=True)
    print("", flush=True)

    buffer = ""
    item_count = 0

    try:
        with open(METADATA_PIPE, 'rb') as pipe:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    time.sleep(0.1)
                    continue

                try:
                    buffer += chunk.decode('utf-8', errors='ignore')
                except:
                    continue

                # Process complete items
                while "<item>" in buffer and "</item>" in buffer:
                    start_idx = buffer.find("<item>")
                    end_idx = buffer.find("</item>", start_idx)

                    if end_idx == -1:
                        break

                    end_idx += len("</item>")
                    item_xml = buffer[start_idx:end_idx]
                    buffer = buffer[end_idx:]

                    item_count += 1

                    # Check if this is a PICT or picture-related item
                    if "PICT" in item_xml or "pcst" in item_xml or "pcen" in item_xml:
                        print(f"\n{'=' * 60}", flush=True)
                        print(f"PICTURE-RELATED ITEM #{item_count}", flush=True)
                        print(f"{'=' * 60}", flush=True)
                        print(item_xml, flush=True)
                        print(f"{'=' * 60}", flush=True)
                        print("", flush=True)

                    # Also show artist/title/album for context
                    elif "asar" in item_xml or "minm" in item_xml or "asal" in item_xml:
                        # Extract code to show which metadata this is
                        if "asar" in item_xml:
                            print(f"[Item #{item_count}] Artist metadata received", flush=True)
                        elif "minm" in item_xml:
                            print(f"[Item #{item_count}] Title metadata received", flush=True)
                        elif "asal" in item_xml:
                            print(f"[Item #{item_count}] Album metadata received", flush=True)

                # Prevent buffer overflow
                if len(buffer) > 100000:
                    buffer = buffer[-10000:]

    except KeyboardInterrupt:
        print("\nStopping...", flush=True)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
