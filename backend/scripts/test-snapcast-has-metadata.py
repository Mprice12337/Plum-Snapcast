#!/usr/bin/env python3
"""
Simple test: Query Snapcast and dump the raw metadata it has stored
"""

import socket
import json

def query_snapcast():
    response = None
    sock = None

    try:
        # Connect to Snapcast
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(('localhost', 1780))

        # Send Server.GetStatus request
        request = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "Server.GetStatus"
        }

        sock.sendall((json.dumps(request) + '\r\n').encode('utf-8'))

        # Read response (read until we get valid JSON)
        data = b''
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data += chunk

            # Try to parse what we have
            try:
                response = json.loads(data.decode('utf-8'))
                break
            except:
                # Not complete yet, keep reading
                if len(data) > 1000000:  # Safety: don't read more than 1MB
                    break
                continue

        if not response:
            print("ERROR: No valid JSON response received")
            return False

        # Extract streams
        streams = response.get('result', {}).get('server', {}).get('streams', [])

        print("=" * 70)
        print("SNAPCAST METADATA TEST")
        print("=" * 70)
        print()

        for stream in streams:
            print(f"Stream ID: {stream['id']}")
            print(f"  Status: {stream.get('status', 'unknown')}")
            print()

            # Check if properties exist
            if 'properties' in stream:
                print("  ✓ Properties found")
                props = stream['properties']
                print(f"    Property keys: {list(props.keys())}")
                print()

                # Check for metadata
                if 'metadata' in props:
                    print("  ✓✓ METADATA FOUND!")
                    meta = props['metadata']
                    print(f"    Metadata keys: {list(meta.keys())}")
                    print()

                    # Print each field
                    for key, value in meta.items():
                        if key == 'mpris:artUrl' and isinstance(value, str) and len(value) > 100:
                            print(f"      {key}: [artwork data, {len(value)} chars]")
                        else:
                            print(f"      {key}: {value}")
                else:
                    print("  ✗✗ NO METADATA in properties")
            else:
                print("  ✗ No properties on stream")

            print()
            print("-" * 70)
            print()

        return True

    except socket.timeout:
        print("ERROR: Connection timed out")
        return False
    except ConnectionRefusedError:
        print("ERROR: Connection refused - is Snapcast running?")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass

if __name__ == '__main__':
    query_snapcast()
