#!/usr/bin/env python3
"""
Debug script to analyze artwork synchronization issues
Traces artwork from control script through to frontend
"""

import json
import sys
import time
from pathlib import Path
import hashlib

# Paths
CONTROL_LOG = "/tmp/airplay-control-script.log"
COVERART_DIR = "/usr/share/snapserver/snapweb/coverart"
ARTWORK_JSON = "/usr/share/snapserver/snapweb/airplay-artwork.json"

def parse_log_for_artwork_events():
    """Extract artwork-related events from control script log"""
    print("=" * 60)
    print("ARTWORK EVENTS FROM CONTROL SCRIPT LOG")
    print("=" * 60)

    if not Path(CONTROL_LOG).exists():
        print(f"ERROR: Log file not found: {CONTROL_LOG}")
        return []

    events = []
    with open(CONTROL_LOG, 'r') as f:
        for line in f:
            line = line.strip()
            # Look for artwork-related events
            if any(keyword in line for keyword in ['PICT', 'Cover art', 'artUrl', 'Preserved existing artUrl']):
                events.append(line)

    # Show last 30 events
    recent_events = events[-30:]
    for event in recent_events:
        print(event)

    print(f"\nTotal artwork events: {len(events)}")
    print(f"Showing last: {len(recent_events)}")
    return events

def analyze_metadata_sequence():
    """Analyze the sequence of metadata updates to find artwork issues"""
    print("\n" + "=" * 60)
    print("METADATA UPDATE SEQUENCE ANALYSIS")
    print("=" * 60)

    if not Path(CONTROL_LOG).exists():
        return

    # Track metadata updates
    updates = []
    with open(CONTROL_LOG, 'r') as f:
        for line in f:
            if 'Sent metadata update:' in line:
                # Extract the metadata fields that were sent
                parts = line.split('Sent metadata update:')
                if len(parts) > 1:
                    fields = parts[1].strip()
                    timestamp = line.split()[0] + " " + line.split()[1]
                    updates.append({'time': timestamp, 'fields': fields})

    # Show last 20 updates
    print(f"Last 20 metadata updates:")
    for update in updates[-20:]:
        has_artwork = 'artUrl' in update['fields']
        marker = "📷" if has_artwork else "  "
        print(f"{marker} {update['time']} - Fields: {update['fields']}")

    # Count updates with/without artwork
    total = len(updates[-20:])
    with_art = sum(1 for u in updates[-20:] if 'artUrl' in u['fields'])
    without_art = total - with_art

    print(f"\nSummary of last 20 updates:")
    print(f"  With artwork:    {with_art}/{total}")
    print(f"  Without artwork: {without_art}/{total}")

    if without_art > with_art:
        print("\n⚠️  WARNING: More updates WITHOUT artwork than with!")
        print("   This suggests artwork is being sent separately/late")

def check_artwork_preservation_issue():
    """Check if artwork preservation is causing stale artwork"""
    print("\n" + "=" * 60)
    print("ARTWORK PRESERVATION ISSUE CHECK")
    print("=" * 60)

    if not Path(CONTROL_LOG).exists():
        return

    preserved_count = 0
    new_track_without_art = []

    with open(CONTROL_LOG, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if 'Preserved existing artUrl' in line:
            preserved_count += 1
            # Look back for "New track" message
            for j in range(max(0, i-5), i):
                if 'New track:' in lines[j]:
                    track_info = lines[j].split('New track:')[1].strip()
                    new_track_without_art.append(track_info)
                    break

    print(f"Artwork preservation events: {preserved_count}")

    if preserved_count > 0:
        print(f"\n⚠️  Found {preserved_count} instances where old artwork was preserved!")
        print("   This means new tracks started WITHOUT artwork,")
        print("   so the old artwork was kept (causing mismatched artwork).")
        print("\nTracks that got preserved (stale) artwork:")
        for track in new_track_without_art[-10:]:
            print(f"  - {track}")
    else:
        print("✓ No artwork preservation detected (good!)")

def check_artwork_files():
    """Check artwork files on disk"""
    print("\n" + "=" * 60)
    print("ARTWORK FILES ON DISK")
    print("=" * 60)

    coverart_path = Path(COVERART_DIR)
    if not coverart_path.exists():
        print(f"ERROR: Coverart directory not found: {COVERART_DIR}")
        return

    artwork_files = list(coverart_path.glob("*.jpg"))
    artwork_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    print(f"Total artwork files: {len(artwork_files)}")
    print(f"\nMost recent 10 files:")
    for art_file in artwork_files[:10]:
        stat = art_file.stat()
        size_kb = stat.st_size / 1024
        mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
        print(f"  {art_file.name} - {size_kb:.1f}KB - {mtime}")

    # Check artwork JSON file
    if Path(ARTWORK_JSON).exists():
        with open(ARTWORK_JSON, 'r') as f:
            artwork_data = json.load(f)
        print(f"\nCurrent artwork JSON file:")
        print(f"  artUrl: {artwork_data.get('artUrl')}")
        print(f"  title:  {artwork_data.get('title')}")
        print(f"  artist: {artwork_data.get('artist')}")
    else:
        print(f"\nArtwork JSON not found: {ARTWORK_JSON}")

def check_timing_issue():
    """Check if there's a timing issue between metadata and artwork"""
    print("\n" + "=" * 60)
    print("TIMING ANALYSIS: Metadata vs Artwork Arrival")
    print("=" * 60)

    if not Path(CONTROL_LOG).exists():
        return

    # Track new tracks and when their artwork arrives
    tracks = []
    current_track = None

    with open(CONTROL_LOG, 'r') as f:
        for line in f:
            timestamp = ' '.join(line.split()[:2])

            if 'New track:' in line:
                track_info = line.split('New track:')[1].strip()
                current_track = {
                    'name': track_info,
                    'start_time': timestamp,
                    'metadata_sent': None,
                    'artwork_complete': None
                }
                tracks.append(current_track)

            elif current_track and 'Sent metadata update:' in line:
                if not current_track['metadata_sent']:
                    current_track['metadata_sent'] = timestamp

            elif current_track and 'Track complete with cover art' in line:
                current_track['artwork_complete'] = timestamp

    print(f"Analyzed {len(tracks)} track changes\n")
    print("Last 5 tracks:")
    for track in tracks[-5:]:
        print(f"\nTrack: {track['name']}")
        print(f"  Started:          {track['start_time']}")
        print(f"  Metadata sent:    {track['metadata_sent'] or 'NOT SENT'}")
        print(f"  Artwork complete: {track['artwork_complete'] or '⚠️  NEVER ARRIVED'}")

        if not track['artwork_complete']:
            print(f"  ⚠️  PROBLEM: Artwork never completed for this track!")

def main():
    """Run all diagnostics"""
    print("\n" + "=" * 60)
    print("ARTWORK SYNCHRONIZATION DIAGNOSTIC TOOL")
    print("=" * 60)
    print()

    # Run all checks
    parse_log_for_artwork_events()
    analyze_metadata_sequence()
    check_artwork_preservation_issue()
    check_artwork_files()
    check_timing_issue()

    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)
    print("""
Based on the analysis above, common issues are:

1. ARTWORK PRESERVATION ISSUE:
   - When a new track starts, metadata arrives BEFORE artwork
   - Control script preserves OLD artwork temporarily
   - Frontend shows wrong artwork until next update

   FIX: Don't preserve artwork across track changes. Let it be empty
   briefly rather than show wrong artwork.

2. TIMING ISSUE:
   - Metadata and artwork arrive in separate shairport-sync messages
   - Control script sends multiple updates per track
   - Frontend might miss the artwork update

   FIX: Always include artwork in metadata updates, or ensure frontend
   re-renders when artwork property changes.

3. BROWSER CACHING:
   - Artwork URLs are based on content hash
   - Same hash = browser uses cached version
   - Different artwork with same hash shows old image

   FIX: Add cache-busting query parameter or use Last-Modified headers.
""")
    print("=" * 60)

if __name__ == "__main__":
    main()
