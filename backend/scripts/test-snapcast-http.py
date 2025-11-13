#!/usr/bin/env python3
"""
Test Snapcast metadata via HTTP (not raw socket)
"""

import json
import sys

try:
    import urllib.request
    import urllib.error
    import ssl
except ImportError:
    print("ERROR: urllib not available")
    sys.exit(1)

def test_snapcast_http():
    """Query Snapcast via HTTP POST to /jsonrpc endpoint"""

    print("=" * 70)
    print("SNAPCAST HTTP METADATA TEST")
    print("=" * 70)
    print()

    # Try both HTTP (1780) and HTTPS (1788)
    endpoints = [
        ("HTTP", "http://localhost:1780/jsonrpc"),
        ("HTTPS", "https://localhost:1788/jsonrpc"),
    ]

    for protocol, url in endpoints:
        print(f"[{protocol}] Testing {url}")
        print("-" * 70)

        try:
            # Prepare JSON-RPC request
            request_data = {
                "id": 1,
                "jsonrpc": "2.0",
                "method": "Server.GetStatus"
            }

            request_json = json.dumps(request_data).encode('utf-8')

            # Create HTTP request
            req = urllib.request.Request(
                url,
                data=request_json,
                headers={
                    'Content-Type': 'application/json',
                    'Content-Length': str(len(request_json))
                }
            )

            # For HTTPS, disable cert verification (self-signed cert)
            context = ssl._create_unverified_context() if protocol == "HTTPS" else None

            # Send request
            print(f"  Sending: {request_data}")

            if context:
                response = urllib.request.urlopen(req, context=context, timeout=10)
            else:
                response = urllib.request.urlopen(req, timeout=10)

            # Read response
            response_data = response.read().decode('utf-8')
            response_json = json.loads(response_data)

            print(f"  ✓ Response received ({len(response_data)} bytes)")
            print()

            # Parse streams
            if 'result' not in response_json:
                print("  ✗ No 'result' in response")
                if 'error' in response_json:
                    print(f"  ERROR: {response_json['error']}")
                print()
                continue

            server = response_json.get('result', {}).get('server', {})
            streams = server.get('streams', [])

            print(f"  Found {len(streams)} stream(s)")
            print()

            for stream in streams:
                stream_id = stream.get('id', 'unknown')
                status = stream.get('status', 'unknown')

                print(f"  Stream: {stream_id}")
                print(f"    Status: {status}")

                # Check properties
                if 'properties' not in stream:
                    print(f"    ✗ No properties")
                    print()
                    continue

                props = stream['properties']
                print(f"    ✓ Properties found")
                print(f"      Keys: {list(props.keys())}")

                # Check metadata
                if 'metadata' not in props:
                    print(f"    ✗ No metadata in properties")
                    print()
                    continue

                meta = props['metadata']
                if not meta:
                    print(f"    ✗✗ Metadata is empty object")
                    print()
                    continue

                print(f"    ✓✓ METADATA FOUND!")
                print(f"      Metadata keys: {list(meta.keys())}")
                print()

                # Display metadata
                for key, value in meta.items():
                    if key == 'mpris:artUrl' and isinstance(value, str) and len(value) > 100:
                        print(f"        {key}: [artwork, {len(value)} chars]")
                    else:
                        print(f"        {key}: {value}")

                print()

            print(f"  ✓✓ {protocol} test SUCCESSFUL!")
            print()
            return True

        except urllib.error.HTTPError as e:
            print(f"  ✗ HTTP Error {e.code}: {e.reason}")
            print()
            continue

        except urllib.error.URLError as e:
            print(f"  ✗ Connection failed: {e.reason}")
            print()
            continue

        except Exception as e:
            print(f"  ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            print()
            continue

    print("=" * 70)
    print("All endpoints failed")
    print("=" * 70)
    return False

if __name__ == '__main__':
    success = test_snapcast_http()
    sys.exit(0 if success else 1)
