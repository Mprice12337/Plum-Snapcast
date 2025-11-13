#!/usr/bin/env python3
"""
Debug script: Shows exactly what Snapcast is sending over the socket
"""

import socket
import json
import sys

def debug_snapcast_socket():
    sock = None

    try:
        print("=" * 70)
        print("SNAPCAST SOCKET DEBUG")
        print("=" * 70)
        print()

        # Connect to Snapcast
        print("[1] Connecting to localhost:1780...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(('localhost', 1780))
        print("    ✓ Connected")
        print()

        # Send Server.GetStatus request
        request = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "Server.GetStatus"
        }
        request_json = json.dumps(request) + '\r\n'

        print("[2] Sending request:")
        print(f"    {request_json.strip()}")
        sock.sendall(request_json.encode('utf-8'))
        print("    ✓ Sent")
        print()

        # Read response with detailed logging
        print("[3] Reading response...")
        data = b''
        chunk_count = 0

        while True:
            chunk = sock.recv(8192)
            chunk_count += 1

            if not chunk:
                print(f"    No more data after {chunk_count} chunks")
                break

            data += chunk
            print(f"    Chunk {chunk_count}: received {len(chunk)} bytes (total: {len(data)} bytes)")

            # Try to parse what we have
            try:
                response = json.loads(data.decode('utf-8'))
                print("    ✓ Valid JSON received!")
                print()

                # Show response structure
                print("[4] Response structure:")
                if 'result' in response:
                    print("    ✓ Has 'result' key")
                    if 'server' in response['result']:
                        print("    ✓ Has 'server' key")
                        server = response['result']['server']
                        if 'streams' in server:
                            print(f"    ✓ Has 'streams' key ({len(server['streams'])} streams)")

                            for i, stream in enumerate(server['streams']):
                                print(f"\n    Stream {i}: {stream.get('id', 'unknown')}")
                                if 'properties' in stream:
                                    print(f"      ✓ Has properties")
                                    props = stream['properties']
                                    print(f"        Keys: {list(props.keys())}")

                                    if 'metadata' in props:
                                        meta = props['metadata']
                                        if meta:
                                            print(f"      ✓✓ Has metadata!")
                                            print(f"        Metadata keys: {list(meta.keys())}")
                                            for key, value in meta.items():
                                                if key == 'mpris:artUrl' and len(str(value)) > 100:
                                                    print(f"          {key}: [{len(value)} chars]")
                                                else:
                                                    print(f"          {key}: {value}")
                                        else:
                                            print(f"      ✗✗ Metadata is empty object")
                                    else:
                                        print(f"      ✗ No metadata key in properties")
                                else:
                                    print(f"      ✗ No properties key")
                        else:
                            print("    ✗ No 'streams' key")
                    else:
                        print("    ✗ No 'server' key")
                else:
                    print("    ✗ No 'result' key")
                    if 'error' in response:
                        print(f"    ERROR in response: {response['error']}")

                return True

            except json.JSONDecodeError as e:
                # Not complete yet, keep reading
                if len(data) > 1000000:  # Safety: don't read more than 1MB
                    print(f"    ✗ Data too large (>{len(data)} bytes), stopping")
                    print(f"    Raw data preview: {data[:500]}")
                    break
                continue

        # If we get here, we didn't get valid JSON
        print()
        print("[ERROR] Failed to get valid JSON response")
        print(f"Total data received: {len(data)} bytes")
        if data:
            print()
            print("Raw data received:")
            print("-" * 70)
            try:
                print(data.decode('utf-8'))
            except:
                print(f"[Binary data, first 500 bytes]")
                print(data[:500])
            print("-" * 70)
        else:
            print("No data received at all!")

        return False

    except socket.timeout:
        print("ERROR: Connection timed out")
        return False
    except ConnectionRefusedError:
        print("ERROR: Connection refused - is Snapcast running on port 1780?")
        print()
        print("Try checking:")
        print("  supervisorctl -c /app/supervisord/supervisord.conf status snapserver")
        print("  netstat -tlnp | grep 1780")
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
    success = debug_snapcast_socket()
    sys.exit(0 if success else 1)
