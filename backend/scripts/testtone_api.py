#!/usr/bin/env python3
"""
Test Tone API
Provides endpoints for playing test tones during volume calibration.
Uses sox to generate tones that play through Snapcast for accurate calibration.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Dict, Any, Optional
from flask import Blueprint, jsonify, request

# Import SettingsManager for Snapcast client volume control
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)

# Test tone state
_tone_process: Optional[subprocess.Popen] = None
_tone_lock = threading.Lock()
_current_tone_info: Dict[str, Any] = {}

# Test tone FIFO path - we'll use a dedicated FIFO for calibration
CALIBRATION_FIFO = "/tmp/calibration-tone-fifo"
CALIBRATION_STREAM_NAME = "calibration"

# Snapcast WebSocket for volume control
SNAPCAST_HOST = "localhost"
SNAPCAST_PORT = 1780


def _ensure_fifo_exists():
    """Ensure the calibration FIFO exists"""
    if not os.path.exists(CALIBRATION_FIFO):
        try:
            os.mkfifo(CALIBRATION_FIFO)
            os.chmod(CALIBRATION_FIFO, 0o666)
            logger.info(f"Created calibration FIFO: {CALIBRATION_FIFO}")
        except Exception as e:
            logger.error(f"Failed to create FIFO: {e}")
            raise


def _stop_tone_internal():
    """Internal function to stop any running tone"""
    global _tone_process, _current_tone_info

    if _tone_process:
        try:
            _tone_process.terminate()
            _tone_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _tone_process.kill()
            _tone_process.wait()
        except Exception as e:
            logger.error(f"Error stopping tone: {e}")
        finally:
            _tone_process = None
            _current_tone_info = {}


def _set_client_volume_via_websocket(client_id: str, volume: int) -> bool:
    """Set Snapcast client volume via WebSocket JSON-RPC"""
    import websocket
    import json

    try:
        ws_url = f"ws://{SNAPCAST_HOST}:{SNAPCAST_PORT}/jsonrpc"
        ws = websocket.create_connection(ws_url, timeout=5)

        request_data = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "Client.SetVolume",
            "params": {
                "id": client_id,
                "volume": {
                    "percent": volume,
                    "muted": False
                }
            }
        }

        ws.send(json.dumps(request_data))
        response = ws.recv()
        ws.close()

        result = json.loads(response)
        return "error" not in result

    except Exception as e:
        logger.error(f"Failed to set volume via WebSocket: {e}")
        return False


def _get_snapcast_clients() -> list:
    """Get list of Snapcast clients"""
    import websocket
    import json

    try:
        ws_url = f"ws://{SNAPCAST_HOST}:{SNAPCAST_PORT}/jsonrpc"
        ws = websocket.create_connection(ws_url, timeout=5)

        request_data = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "Server.GetStatus",
            "params": {}
        }

        ws.send(json.dumps(request_data))
        response = ws.recv()
        ws.close()

        result = json.loads(response)

        clients = []
        if "result" in result:
            server = result["result"].get("server", {})
            for group in server.get("groups", []):
                for client in group.get("clients", []):
                    clients.append({
                        "id": client.get("id"),
                        "name": client.get("config", {}).get("name", client.get("id")),
                        "connected": client.get("connected", False),
                        "volume": client.get("config", {}).get("volume", {}).get("percent", 100),
                        "stream_id": group.get("stream_id")
                    })

        return clients

    except Exception as e:
        logger.error(f"Failed to get Snapcast clients: {e}")
        return []


def create_testtone_blueprint() -> Blueprint:
    """Create Flask blueprint for test tone API"""
    bp = Blueprint('testtone', __name__)

    @bp.route("/api/testtone/start", methods=["POST"])
    def start_tone():
        """
        Start playing a test tone at specified volume.

        Request body:
        {
            "client_id": "abc123",     // Snapcast client ID to play on
            "volume": 80,              // Volume level (0-100)
            "type": "pink",            // Tone type: "pink", "sine", or "sweep"
            "duration": 60             // Duration in seconds (default: 60)
        }
        """
        global _tone_process, _current_tone_info

        try:
            data = request.get_json() or {}
            client_id = data.get("client_id")
            volume = data.get("volume", 80)
            tone_type = data.get("type", "pink")
            duration = data.get("duration", 60)

            if not client_id:
                return jsonify({"error": "client_id is required"}), 400

            if tone_type not in ["pink", "sine", "sweep"]:
                return jsonify({"error": "type must be 'pink', 'sine', or 'sweep'"}), 400

            if not 0 <= volume <= 100:
                return jsonify({"error": "volume must be between 0 and 100"}), 400

            with _tone_lock:
                # Stop any existing tone
                _stop_tone_internal()

                # Set client volume
                if not _set_client_volume_via_websocket(client_id, volume):
                    logger.warning(f"Failed to set volume for {client_id}, continuing anyway")

                # Build sox command based on tone type
                # Output directly to ALSA for immediate playback
                # We use the snapclient's configured device

                if tone_type == "pink":
                    # Pink noise - equal energy per octave, good for SPL meters
                    cmd = [
                        "sox", "-n", "-t", "alsa", "default",
                        "synth", str(duration), "pinknoise",
                        "gain", "-3"  # Slight attenuation to prevent clipping
                    ]
                elif tone_type == "sine":
                    # 1kHz sine wave - standard reference tone
                    cmd = [
                        "sox", "-n", "-t", "alsa", "default",
                        "synth", str(duration), "sine", "1000",
                        "gain", "-3"
                    ]
                elif tone_type == "sweep":
                    # Frequency sweep 20Hz-20kHz
                    cmd = [
                        "sox", "-n", "-t", "alsa", "default",
                        "synth", str(duration), "sine", "20-20000",
                        "gain", "-3"
                    ]

                # Start tone generation in background
                logger.info(f"Starting {tone_type} tone at {volume}% for {duration}s")

                try:
                    _tone_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )

                    _current_tone_info = {
                        "client_id": client_id,
                        "volume": volume,
                        "type": tone_type,
                        "duration": duration,
                        "started_at": time.time()
                    }

                    return jsonify({
                        "status": "playing",
                        "type": tone_type,
                        "volume": volume,
                        "duration": duration,
                        "client_id": client_id
                    })

                except FileNotFoundError:
                    logger.error("sox command not found - ensure sox is installed")
                    return jsonify({"error": "sox not installed on server"}), 500

        except Exception as e:
            logger.error(f"Start tone failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/testtone/stop", methods=["POST"])
    def stop_tone():
        """Stop the currently playing test tone"""
        try:
            with _tone_lock:
                _stop_tone_internal()

            return jsonify({"status": "stopped"})

        except Exception as e:
            logger.error(f"Stop tone failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/testtone/volume", methods=["POST"])
    def set_tone_volume():
        """
        Adjust volume while tone is playing.

        Request body:
        {
            "client_id": "abc123",
            "volume": 50
        }
        """
        try:
            data = request.get_json() or {}
            client_id = data.get("client_id")
            volume = data.get("volume")

            if not client_id:
                return jsonify({"error": "client_id is required"}), 400

            if volume is None or not 0 <= volume <= 100:
                return jsonify({"error": "volume must be between 0 and 100"}), 400

            # Set volume via Snapcast
            success = _set_client_volume_via_websocket(client_id, volume)

            if success:
                # Update current tone info
                with _tone_lock:
                    if _current_tone_info:
                        _current_tone_info["volume"] = volume

                return jsonify({"status": "ok", "volume": volume})
            else:
                return jsonify({"error": "Failed to set volume"}), 500

        except Exception as e:
            logger.error(f"Set tone volume failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/testtone/status", methods=["GET"])
    def get_tone_status():
        """Get current test tone status"""
        try:
            with _tone_lock:
                if _tone_process and _tone_process.poll() is None:
                    elapsed = time.time() - _current_tone_info.get("started_at", 0)
                    remaining = max(0, _current_tone_info.get("duration", 0) - elapsed)

                    return jsonify({
                        "status": "playing",
                        "type": _current_tone_info.get("type"),
                        "volume": _current_tone_info.get("volume"),
                        "client_id": _current_tone_info.get("client_id"),
                        "elapsed": round(elapsed, 1),
                        "remaining": round(remaining, 1)
                    })
                else:
                    return jsonify({"status": "stopped"})

        except Exception as e:
            logger.error(f"Get tone status failed: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/testtone/clients", methods=["GET"])
    def get_clients():
        """Get list of available Snapcast clients for tone playback"""
        try:
            clients = _get_snapcast_clients()
            return jsonify({"clients": clients})

        except Exception as e:
            logger.error(f"Get clients failed: {e}")
            return jsonify({"error": str(e)}), 500

    return bp


# For standalone testing
if __name__ == "__main__":
    from flask import Flask
    from flask_cors import CORS

    logging.basicConfig(level=logging.DEBUG)

    app = Flask(__name__)
    CORS(app)

    bp = create_testtone_blueprint()
    app.register_blueprint(bp)

    print("Test Tone API running on http://localhost:5005")
    app.run(host="0.0.0.0", port=5005, debug=True)
