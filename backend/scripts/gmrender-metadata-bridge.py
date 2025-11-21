#!/usr/bin/env python3
"""
gmrender-resurrect Metadata Bridge
Monitors gmrender's UPnP AVTransport service for metadata changes
and writes them to /tmp/dlna-metadata.json for the control script

This bridges the gap between gmrender's internal UPnP metadata
and Snapcast's control script interface.
"""

import json
import time
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict
import urllib.request
import urllib.error

METADATA_FILE = "/tmp/dlna-metadata.json"
GMRENDER_PORT = 49494  # Default gmrender port (may change)
POLL_INTERVAL = 2  # Poll every 2 seconds

def log(message: str):
    """Log to stderr"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [MetadataBridge] {message}", file=sys.stderr, flush=True)

def find_gmrender_port() -> Optional[int]:
    """Find gmrender's actual port by reading from logs"""
    try:
        # Try to read from gmrender log
        with open("/var/log/supervisord/gmrender.log", "r") as f:
            for line in f:
                # Look for: Registered IPv4 192.168.x.x:PORT
                match = re.search(r'Registered IPv4 [\d.]+:(\d+)', line)
                if match:
                    port = int(match.group(1))
                    log(f"Found gmrender port: {port}")
                    return port
    except Exception as e:
        log(f"Could not find gmrender port from logs: {e}")

    return 49494  # Default fallback

def get_transport_info(port: int) -> Optional[str]:
    """Query gmrender's AVTransport service for current URI metadata"""
    try:
        # SOAP request to get AVTransport URI
        soap_request = '''<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
<s:Body>
<u:GetTransportInfo xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
<InstanceID>0</InstanceID>
</u:GetTransportInfo>
</s:Body>
</s:Envelope>'''

        url = f"http://127.0.0.1:{port}/upnp/control/rendertransport1"
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPAction': '"urn:schemas-upnp-org:service:AVTransport:1#GetTransportInfo"'
        }

        req = urllib.request.Request(url, data=soap_request.encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.read().decode('utf-8')

    except Exception as e:
        # Don't spam logs - gmrender might not be playing
        return None

def get_position_info(port: int) -> Optional[str]:
    """Query gmrender for current track metadata"""
    try:
        soap_request = '''<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
<s:Body>
<u:GetPositionInfo xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
<InstanceID>0</InstanceID>
</u:GetPositionInfo>
</s:Body>
</s:Envelope>'''

        url = f"http://127.0.0.1:{port}/upnp/control/rendertransport1"
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPAction': '"urn:schemas-upnp-org:service:AVTransport:1#GetPositionInfo"'
        }

        req = urllib.request.Request(url, data=soap_request.encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.read().decode('utf-8')

    except Exception as e:
        return None

def parse_didl_metadata(didl_xml: str) -> Dict:
    """Parse DIDL-Lite XML metadata"""
    metadata = {}

    try:
        # Remove XML namespaces for easier parsing
        didl_xml = re.sub(r' xmlns[^=]*="[^"]*"', '', didl_xml)

        root = ET.fromstring(didl_xml)

        # Extract title
        title_elem = root.find('.//title')
        if title_elem is not None and title_elem.text:
            metadata['title'] = title_elem.text

        # Extract artist
        artist_elem = root.find('.//artist') or root.find('.//creator')
        if artist_elem is not None and artist_elem.text:
            metadata['artist'] = artist_elem.text

        # Extract album
        album_elem = root.find('.//album')
        if album_elem is not None and album_elem.text:
            metadata['album'] = album_elem.text

        # Extract album art
        art_elem = root.find('.//albumArtURI')
        if art_elem is not None and art_elem.text:
            metadata['artUrl'] = art_elem.text

    except Exception as e:
        log(f"Error parsing DIDL: {e}")

    return metadata

def extract_metadata_from_position_info(xml_response: str) -> Dict:
    """Extract metadata from GetPositionInfo SOAP response"""
    metadata = {}

    try:
        # Parse SOAP response
        root = ET.fromstring(xml_response)

        # Find TrackMetaData element
        # It contains DIDL-Lite XML with metadata
        for elem in root.iter():
            if 'TrackMetaData' in elem.tag:
                didl = elem.text
                if didl:
                    metadata = parse_didl_metadata(didl)
                break

        # Also get transport state
        for elem in root.iter():
            if 'CurrentTransportState' in elem.tag:
                state = elem.text
                if state == 'PLAYING':
                    metadata['status'] = 'Playing'
                elif state == 'PAUSED_PLAYBACK':
                    metadata['status'] = 'Paused'
                else:
                    metadata['status'] = 'Stopped'
                break

    except Exception as e:
        log(f"Error extracting metadata: {e}")

    return metadata

def write_metadata(metadata: Dict):
    """Write metadata to JSON file for control script"""
    try:
        with open(METADATA_FILE, 'w') as f:
            json.dump(metadata, f, indent=2)

        if metadata.get('title'):
            log(f"Updated metadata: {metadata.get('title')} - {metadata.get('artist', 'Unknown')}")
    except Exception as e:
        log(f"Error writing metadata: {e}")

def main():
    """Main monitoring loop"""
    log("Starting gmrender metadata bridge...")

    # Find gmrender port
    port = find_gmrender_port()

    last_metadata = {}

    while True:
        try:
            # Query gmrender for position info (includes metadata)
            position_xml = get_position_info(port)

            if position_xml:
                # Extract metadata from response
                metadata = extract_metadata_from_position_info(position_xml)

                # Only update if metadata changed
                if metadata != last_metadata:
                    write_metadata(metadata)
                    last_metadata = metadata

        except Exception as e:
            log(f"Error in monitoring loop: {e}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Shutting down...")
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
