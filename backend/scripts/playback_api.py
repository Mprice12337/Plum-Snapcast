#!/usr/bin/env python3
"""
Playback Position API - Real-time position tracking without audio stuttering

PROBLEM:
========
Snapcast's Plugin.Stream.Player.Properties notifications cause audio stuttering
when position updates are pushed frequently. This makes real-time position tracking
impossible through the standard Snapcast API.

SOLUTION:
=========
This API provides an independent position tracking system with server-side interpolation:

1. Control scripts POST position updates when they change (track start, seek, pause)
2. Server interpolates position between updates using dual timestamps
3. Frontend polls for interpolated position every 2 seconds
4. No impact on Snapcast audio pipeline

TWO-TIMESTAMP ARCHITECTURE:
===========================
- last_update: Updated on every heartbeat (prevents staleness)
- position_timestamp: Updated only when position changes (enables interpolation)

This allows heartbeat updates to keep data fresh while maintaining accurate
interpolation between actual position changes.

ENDPOINTS:
==========
POST /api/playback/{stream_id} - Control scripts post position updates
GET  /api/playback/{stream_id} - Frontend polls for specific stream
GET  /api/playback             - Frontend polls for all streams
"""

import logging
import threading
import time
from typing import Dict, Any, Optional
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


class PlaybackStore:
    """Thread-safe in-memory storage for playback position data"""

    def __init__(self, stale_threshold_seconds: int = 30):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stale_threshold = stale_threshold_seconds

    def update(self, stream_id: str, position: int, duration: int,
               playback_status: str = "playing", **extra) -> None:
        """
        Update playback position for a stream.

        Args:
            stream_id: Snapcast stream ID
            position: Current position in milliseconds
            duration: Total duration in milliseconds
            playback_status: "playing", "paused", "stopped", or "unknown"
            **extra: Additional metadata (artist, title, album, etc.)
        """
        with self._lock:
            existing = self._data.get(stream_id)
            now = time.time()

            # Only reset position_timestamp if position actually changed
            # This allows heartbeats (same position) to keep data fresh without breaking interpolation
            position_changed = (
                not existing or
                position != existing.get("position", 0) or  # Any position change
                playback_status != existing.get("playback_status")
            )

            self._data[stream_id] = {
                "stream_id": stream_id,
                "position": position,
                "duration": duration,
                "playback_status": playback_status,
                "last_update": now,  # Always update (staleness check)
                "position_timestamp": now if position_changed else existing.get("position_timestamp", now),  # Only update if position changed (interpolation)
                **extra
            }

    def get(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """Get playback data for a specific stream"""
        with self._lock:
            data = self._data.get(stream_id)
            if data:
                # Add calculated fields
                return self._enrich_data(data.copy())
            return None

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Get playback data for all streams"""
        with self._lock:
            result = {}
            for stream_id, data in self._data.items():
                result[stream_id] = self._enrich_data(data.copy())
            return result

    def remove(self, stream_id: str) -> bool:
        """Remove playback data for a stream"""
        with self._lock:
            if stream_id in self._data:
                del self._data[stream_id]
                return True
            return False

    def cleanup_stale(self) -> int:
        """Remove stale entries (streams inactive for >30s)"""
        with self._lock:
            now = time.time()
            stale_ids = [
                stream_id for stream_id, data in self._data.items()
                if now - data.get("last_update", 0) > self._stale_threshold
            ]
            for stream_id in stale_ids:
                del self._data[stream_id]
            return len(stale_ids)

    def _enrich_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate interpolated position and staleness"""
        now = time.time()
        last_update = data.get("last_update", 0)
        position_timestamp = data.get("position_timestamp", 0)

        age_seconds = now - last_update
        is_stale = age_seconds > self._stale_threshold

        # Server-side interpolation for playing streams
        position = data.get("position", 0)
        if data.get("playback_status") == "playing" and not is_stale:
            elapsed = now - position_timestamp
            interpolated_position = position + int(elapsed * 1000)
            duration = data.get("duration", 0)
            if duration > 0:
                interpolated_position = min(interpolated_position, duration)
            data["interpolated_position"] = interpolated_position
        else:
            data["interpolated_position"] = position

        data["age_seconds"] = round(age_seconds, 2)
        data["is_stale"] = is_stale
        return data


# Global playback store instance
playback_store = PlaybackStore()


def create_playback_blueprint() -> Blueprint:
    """Create Flask blueprint for playback position API"""

    bp = Blueprint('playback', __name__)

    @bp.route("/api/playback", methods=["GET"])
    def get_all_playback():
        """Get playback position for all streams"""
        try:
            data = playback_store.get_all()
            return jsonify({
                "success": True,
                "streams": data
            })
        except Exception as e:
            logger.error(f"Failed to get all playback data: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/playback/<stream_id>", methods=["GET"])
    def get_stream_playback(stream_id: str):
        """Get playback position for a specific stream"""
        try:
            data = playback_store.get(stream_id)
            if data:
                return jsonify({
                    "success": True,
                    **data
                })
            else:
                return jsonify({
                    "success": False,
                    "error": f"No playback data for stream: {stream_id}"
                }), 404
        except Exception as e:
            logger.error(f"Failed to get playback data for {stream_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/playback/<stream_id>", methods=["POST"])
    def update_stream_playback(stream_id: str):
        """
        Update playback position for a stream.

        Expected JSON body:
        {
            "position": 12345,        // Current position in milliseconds
            "duration": 180000,       // Total duration in milliseconds
            "playback_status": "playing",  // Optional: "playing", "paused", "stopped"
            "artist": "...",          // Optional: metadata
            "title": "...",           // Optional: metadata
            "album": "..."            // Optional: metadata
        }
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({"success": False, "error": "JSON body required"}), 400

            # Validate required fields
            position = data.get("position")
            duration = data.get("duration")

            if position is None:
                return jsonify({"success": False, "error": "position is required"}), 400
            if duration is None:
                return jsonify({"success": False, "error": "duration is required"}), 400

            # Extract optional fields
            playback_status = data.get("playback_status", "playing")
            extra = {k: v for k, v in data.items()
                     if k not in ("position", "duration", "playback_status")}

            playback_store.update(
                stream_id=stream_id,
                position=int(position),
                duration=int(duration),
                playback_status=playback_status,
                **extra
            )

            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"Failed to update playback for {stream_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/playback/<stream_id>", methods=["DELETE"])
    def delete_stream_playback(stream_id: str):
        """Remove playback data for a stream"""
        try:
            removed = playback_store.remove(stream_id)
            if removed:
                return jsonify({"success": True})
            else:
                return jsonify({
                    "success": False,
                    "error": f"No playback data for stream: {stream_id}"
                }), 404
        except Exception as e:
            logger.error(f"Failed to delete playback data for {stream_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/playback/cleanup", methods=["POST"])
    def cleanup_stale():
        """Manually trigger cleanup of stale playback entries"""
        try:
            count = playback_store.cleanup_stale()
            return jsonify({
                "success": True,
                "cleaned_up": count
            })
        except Exception as e:
            logger.error(f"Failed to cleanup stale playback data: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    return bp


# For standalone testing
if __name__ == "__main__":
    from flask import Flask
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)

    bp = create_playback_blueprint()
    app.register_blueprint(bp)

    print("Playback API running on http://localhost:5005")
    app.run(host="0.0.0.0", port=5005, debug=True)
