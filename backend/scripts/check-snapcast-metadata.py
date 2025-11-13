#!/usr/bin/env python3
"""
Check if Snapcast is receiving and storing metadata from the control script
"""

import json
import socket
import sys

def query_snapcast(host='localhost', port=1780):
    """Query Snapcast Server.GetStatus via JSON-RPC"""
    try:
        # Create socket connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))

        # Send request
        request = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "Server.GetStatus"
        }
        sock.sendall((json.dumps(request) + '\r\n').encode('utf-8'))

        # Read response
        response_data = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            # Check if we have a complete JSON object
            try:
                response = json.loads(response_data.decode('utf-8'))
                break
            except:
                continue

        sock.close()
        return response

    except Exception as e:
        print(f"Error querying Snapcast: {e}", file=sys.stderr)
        return None

def main():
    print("=" * 60)
    print("Snapcast Metadata Verification")
    print("=" * 60)
    print()

    response = query_snapcast()

    if not response:
        print("❌ Could not connect to Snapcast server")
        return 1

    if 'result' not in response:
        print("❌ Invalid response from Snapcast")
        print(json.dumps(response, indent=2))
        return 1

    server = response['result'].get('server', {})
    streams = server.get('streams', [])

    print(f"Found {len(streams)} stream(s)")
    print()

    for stream in streams:
        stream_id = stream.get('id', 'unknown')
        stream_name = stream.get('uri', {}).get('query', {}).get('name', 'unknown')
        status = stream.get('status', 'unknown')

        print(f"Stream ID: {stream_id}")
        print(f"  Name: {stream_name}")
        print(f"  Status: {status}")

        # Check for properties
        properties = stream.get('properties', {})
        if properties:
            print(f"  Properties: {list(properties.keys())}")

            # Check for metadata
            metadata = properties.get('metadata', None)
            if metadata:
                print(f"  ✅ Metadata FOUND:")
                print(f"     Title: {metadata.get('title', 'N/A')}")
                print(f"     Artist: {metadata.get('artist', 'N/A')}")
                print(f"     Album: {metadata.get('album', 'N/A')}")

                if 'artUrl' in metadata:
                    art_preview = metadata['artUrl'][:80] + "..." if len(metadata['artUrl']) > 80 else metadata['artUrl']
                    print(f"     Artwork: {art_preview}")
                else:
                    print(f"     Artwork: Not present")
            else:
                print(f"  ❌ Metadata NOT FOUND in properties")
        else:
            print(f"  ❌ No properties found on stream")

        print()

    return 0

if __name__ == '__main__':
    sys.exit(main())
