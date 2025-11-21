#!/usr/bin/env python3
"""
gmrender-resurrect Metadata Bridge (stdout parser)
Reads gmrender's stdout logs and extracts DLNA/UPnP metadata

Based on HiFiBerry's dlna-mpris approach:
- Tails gmrender's log output
- Parses CurrentTrackMetaData (DIDL-Lite XML)
- Extracts title, artist, album, artwork
- Writes to /tmp/dlna-metadata.json for control script

Architecture:
  gmrender logs → this script → JSON file → control script → Snapcast
"""

import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Dict, Optional
import subprocess
import html

METADATA_FILE = "/tmp/dlna-metadata.json"
LOG_FILE = "/var/log/supervisord/gmrender.log"

def log(message: str):
    """Log to stderr"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [MetadataBridge] {message}", file=sys.stderr, flush=True)

def parse_didl_lite(didl_xml: str) -> Dict:
    """
    Parse DIDL-Lite XML metadata from UPnP AVTransport

    DIDL-Lite structure:
    <DIDL-Lite>
      <item>
        <dc:title>Track Name</dc:title>
        <dc:creator>Artist Name</dc:creator> or <upnp:artist>Artist</upnp:artist>
        <upnp:album>Album Name</upnp:album>
        <upnp:albumArtURI>http://...</upnp:albumArtURI>
      </item>
    </DIDL-Lite>
    """
    metadata = {}

    try:
        # Unescape HTML entities if present
        didl_xml = html.unescape(didl_xml)

        # Remove XML namespaces for easier parsing
        didl_xml = re.sub(r' xmlns[^=]*="[^"]*"', '', didl_xml)

        # Parse XML
        root = ET.fromstring(didl_xml)

        # Extract title (required)
        title_elem = root.find('.//title')
        if title_elem is not None and title_elem.text:
            metadata['title'] = title_elem.text.strip()

        # Extract artist (try multiple tags)
        artist_elem = root.find('.//artist') or root.find('.//creator')
        if artist_elem is not None and artist_elem.text:
            metadata['artist'] = artist_elem.text.strip()

        # Extract album
        album_elem = root.find('.//album')
        if album_elem is not None and album_elem.text:
            metadata['album'] = album_elem.text.strip()

        # Extract album art URI
        art_elem = root.find('.//albumArtURI')
        if art_elem is not None and art_elem.text:
            metadata['artUrl'] = art_elem.text.strip()

        # Extract duration if available
        duration_elem = root.find('.//duration')
        if duration_elem is not None and duration_elem.text:
            # Duration might be in HH:MM:SS format or milliseconds
            duration_str = duration_elem.text.strip()
            try:
                # Try parsing as HH:MM:SS
                if ':' in duration_str:
                    parts = duration_str.split(':')
                    if len(parts) == 3:
                        h, m, s = parts
                        duration_ms = (int(h) * 3600 + int(m) * 60 + int(s)) * 1000
                        metadata['duration'] = duration_ms
                else:
                    # Assume it's already in milliseconds
                    metadata['duration'] = int(duration_str)
            except:
                pass

    except Exception as e:
        log(f"Error parsing DIDL-Lite: {e}")

    return metadata

def write_metadata(metadata: Dict, status: str = "Playing"):
    """Write metadata to JSON file for control script"""
    try:
        # Add playback status
        metadata['status'] = status

        with open(METADATA_FILE, 'w') as f:
            json.dump(metadata, f, indent=2)

        if metadata.get('title'):
            log(f"Metadata: {metadata.get('title')} - {metadata.get('artist', 'Unknown')} [{status}]")
    except Exception as e:
        log(f"Error writing metadata: {e}")

def tail_follow_log():
    """
    Tail gmrender log and parse metadata events

    Uses subprocess to tail -F (follow with retry) the log file
    Parses these log lines:
    - INFO [...] TransportState: PLAYING/PAUSED/STOPPED
    - INFO [...] CurrentTrackMetaData: <DIDL-Lite>...</DIDL-Lite>
    """
    log("Starting gmrender log parser...")

    # Start tailing the log file
    try:
        process = subprocess.Popen(
            ['tail', '-F', '-n', '0', LOG_FILE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
    except Exception as e:
        log(f"Error starting tail: {e}")
        log("Falling back to polling mode...")
        return tail_poll_log()

    current_status = "Stopped"
    current_metadata = {}

    log(f"Monitoring: {LOG_FILE}")

    try:
        for line in iter(process.stdout.readline, ''):
            line = line.strip()

            if not line:
                continue

            # Parse TransportState changes
            if 'TransportState:' in line:
                match = re.search(r'TransportState:\s*(\w+)', line)
                if match:
                    state = match.group(1)
                    if state == 'PLAYING':
                        current_status = 'Playing'
                    elif state == 'PAUSED_PLAYBACK' or state == 'PAUSED':
                        current_status = 'Paused'
                    elif state == 'STOPPED':
                        current_status = 'Stopped'
                        # Clear metadata when stopped
                        current_metadata = {}
                        write_metadata({}, current_status)

                    log(f"State: {current_status}")

            # Parse CurrentTrackMetaData (contains DIDL-Lite XML)
            elif 'CurrentTrackMetaData:' in line:
                # Extract DIDL-Lite XML (everything after "CurrentTrackMetaData: ")
                match = re.search(r'CurrentTrackMetaData:\s*(.+)', line)
                if match:
                    didl_xml = match.group(1)

                    # Parse metadata from DIDL-Lite
                    metadata = parse_didl_lite(didl_xml)

                    if metadata:
                        current_metadata = metadata
                        write_metadata(current_metadata, current_status)

    except KeyboardInterrupt:
        log("Shutting down...")
    except Exception as e:
        log(f"Error reading log: {e}")
        import traceback
        traceback.print_exc()
    finally:
        process.terminate()

def tail_poll_log():
    """
    Fallback: Poll log file for changes (if tail command fails)
    """
    log("Using polling mode to read log file...")

    last_position = 0
    current_status = "Stopped"
    current_metadata = {}

    while True:
        try:
            with open(LOG_FILE, 'r') as f:
                # Seek to last position
                f.seek(last_position)

                # Read new lines
                for line in f:
                    line = line.strip()

                    if not line:
                        continue

                    # Parse TransportState
                    if 'TransportState:' in line:
                        match = re.search(r'TransportState:\s*(\w+)', line)
                        if match:
                            state = match.group(1)
                            if state == 'PLAYING':
                                current_status = 'Playing'
                            elif state in ['PAUSED_PLAYBACK', 'PAUSED']:
                                current_status = 'Paused'
                            elif state == 'STOPPED':
                                current_status = 'Stopped'
                                current_metadata = {}
                                write_metadata({}, current_status)

                    # Parse CurrentTrackMetaData
                    elif 'CurrentTrackMetaData:' in line:
                        match = re.search(r'CurrentTrackMetaData:\s*(.+)', line)
                        if match:
                            didl_xml = match.group(1)
                            metadata = parse_didl_lite(didl_xml)

                            if metadata:
                                current_metadata = metadata
                                write_metadata(current_metadata, current_status)

                # Save current position
                last_position = f.tell()

        except FileNotFoundError:
            log(f"Log file not found: {LOG_FILE}")
            time.sleep(5)
        except Exception as e:
            log(f"Error reading log: {e}")
            time.sleep(1)

        # Poll every 0.5 seconds
        time.sleep(0.5)

def main():
    """Main entry point"""
    log("Starting gmrender metadata bridge (stdout parser)...")

    # Try tail -F first (better), fall back to polling
    tail_follow_log()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Shutting down...")
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
