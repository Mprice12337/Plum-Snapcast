"""
Unit tests for Playback Position API
Tests: Position tracking, interpolation, stale data cleanup
"""

import time
import pytest
from unittest.mock import patch
from freezegun import freeze_time


class TestPlaybackGetEndpoints:
    """Tests for GET /api/playback endpoints"""

    def test_get_all_playback_empty(self, playback_client):
        """GET /api/playback returns empty streams when none tracked"""
        response = playback_client.get('/api/playback')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['streams'] == {}

    def test_get_all_playback_with_data(self, playback_client, make_stream_data):
        """GET /api/playback returns all tracked streams"""
        # Add some streams
        playback_client.post('/api/playback/stream1', json=make_stream_data(position=1000))
        playback_client.post('/api/playback/stream2', json=make_stream_data(position=2000))

        response = playback_client.get('/api/playback')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'stream1' in data['streams']
        assert 'stream2' in data['streams']

    def test_get_stream_playback_exists(self, playback_client, make_stream_data):
        """GET /api/playback/{stream_id} returns stream data"""
        playback_client.post('/api/playback/test-stream', json=make_stream_data(
            position=5000,
            duration=180000,
            playback_status='playing'
        ))

        response = playback_client.get('/api/playback/test-stream')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['position'] == 5000
        assert data['duration'] == 180000
        assert data['playback_status'] == 'playing'

    def test_get_stream_playback_not_found(self, playback_client):
        """GET /api/playback/{stream_id} returns success:false for unknown stream"""
        response = playback_client.get('/api/playback/unknown-stream')

        # Returns 200 with success: false (not 404) to avoid console spam
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is False


class TestPlaybackPostEndpoint:
    """Tests for POST /api/playback/{stream_id}"""

    def test_post_playback_creates_entry(self, playback_client):
        """POST /api/playback/{stream_id} creates new entry"""
        response = playback_client.post('/api/playback/new-stream', json={
            'position': 10000,
            'duration': 200000,
            'playback_status': 'playing'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        # Verify it was stored
        get_response = playback_client.get('/api/playback/new-stream')
        assert get_response.get_json()['position'] == 10000

    def test_post_playback_updates_entry(self, playback_client):
        """POST /api/playback/{stream_id} updates existing entry"""
        # Create initial entry
        playback_client.post('/api/playback/stream1', json={
            'position': 1000,
            'duration': 180000
        })

        # Update with new position
        playback_client.post('/api/playback/stream1', json={
            'position': 5000,
            'duration': 180000
        })

        response = playback_client.get('/api/playback/stream1')
        data = response.get_json()
        assert data['position'] == 5000

    def test_post_playback_requires_position(self, playback_client):
        """POST /api/playback/{stream_id} requires position field"""
        response = playback_client.post('/api/playback/stream1', json={
            'duration': 180000
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'position' in data['error'].lower()

    def test_post_playback_requires_duration(self, playback_client):
        """POST /api/playback/{stream_id} requires duration field"""
        response = playback_client.post('/api/playback/stream1', json={
            'position': 1000
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'duration' in data['error'].lower()

    def test_post_playback_with_metadata(self, playback_client):
        """POST /api/playback/{stream_id} stores extra metadata"""
        response = playback_client.post('/api/playback/stream1', json={
            'position': 1000,
            'duration': 180000,
            'playback_status': 'playing',
            'artist': 'Test Artist',
            'title': 'Test Song',
            'album': 'Test Album'
        })

        assert response.status_code == 200

        get_response = playback_client.get('/api/playback/stream1')
        data = get_response.get_json()
        assert data['artist'] == 'Test Artist'
        assert data['title'] == 'Test Song'


class TestPlaybackDeleteEndpoint:
    """Tests for DELETE /api/playback/{stream_id}"""

    def test_delete_playback_removes_entry(self, playback_client, make_stream_data):
        """DELETE /api/playback/{stream_id} removes stream data"""
        # Create entry
        playback_client.post('/api/playback/stream1', json=make_stream_data())

        # Delete it
        response = playback_client.delete('/api/playback/stream1')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        # Verify it's gone
        get_response = playback_client.get('/api/playback/stream1')
        assert get_response.get_json()['success'] is False

    def test_delete_playback_not_found(self, playback_client):
        """DELETE /api/playback/{stream_id} returns 404 for unknown stream"""
        response = playback_client.delete('/api/playback/unknown')

        assert response.status_code == 404


class TestPlaybackInterpolation:
    """Tests for server-side position interpolation"""

    def test_interpolation_for_playing_stream(self, playback_client):
        """Interpolated position advances for playing streams"""
        # Create a playing stream
        playback_client.post('/api/playback/stream1', json={
            'position': 10000,
            'duration': 180000,
            'playback_status': 'playing'
        })

        # Wait a bit
        time.sleep(0.1)

        # Get the data
        response = playback_client.get('/api/playback/stream1')
        data = response.get_json()

        # Interpolated position should be >= base position
        assert data['interpolated_position'] >= data['position']

    def test_no_interpolation_for_paused_stream(self, playback_client):
        """Interpolated position stays fixed for paused streams"""
        # Create a paused stream
        playback_client.post('/api/playback/stream1', json={
            'position': 10000,
            'duration': 180000,
            'playback_status': 'paused'
        })

        # Wait a bit
        time.sleep(0.1)

        # Get the data
        response = playback_client.get('/api/playback/stream1')
        data = response.get_json()

        # Interpolated position should equal base position
        assert data['interpolated_position'] == data['position']

    def test_interpolation_capped_at_duration(self, playback_client):
        """Interpolated position does not exceed duration"""
        # Create stream near end
        playback_client.post('/api/playback/stream1', json={
            'position': 179900,  # 100ms from end
            'duration': 180000,
            'playback_status': 'playing'
        })

        # Wait longer than remaining time
        time.sleep(0.2)

        response = playback_client.get('/api/playback/stream1')
        data = response.get_json()

        # Should not exceed duration
        assert data['interpolated_position'] <= data['duration']


class TestPlaybackStaleness:
    """Tests for stale data detection and cleanup"""

    def test_age_seconds_calculated(self, playback_client, make_stream_data):
        """Response includes age_seconds field"""
        playback_client.post('/api/playback/stream1', json=make_stream_data())

        response = playback_client.get('/api/playback/stream1')
        data = response.get_json()

        assert 'age_seconds' in data
        assert isinstance(data['age_seconds'], (int, float))
        assert data['age_seconds'] >= 0

    def test_is_stale_flag(self, playback_client, make_stream_data):
        """Response includes is_stale flag"""
        playback_client.post('/api/playback/stream1', json=make_stream_data())

        response = playback_client.get('/api/playback/stream1')
        data = response.get_json()

        assert 'is_stale' in data
        # Fresh data should not be stale
        assert data['is_stale'] is False

    def test_cleanup_removes_stale_entries(self, playback_client):
        """POST /api/playback/cleanup removes stale entries"""
        import sys
        sys.path.insert(0, 'scripts')
        from playback_api import playback_store

        # Add a stream with old timestamp
        playback_store._data['old-stream'] = {
            'stream_id': 'old-stream',
            'position': 0,
            'duration': 180000,
            'playback_status': 'stopped',
            'last_update': time.time() - 60,  # 60 seconds ago
            'position_timestamp': time.time() - 60
        }

        # Run cleanup
        response = playback_client.post('/api/playback/cleanup')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['cleaned_up'] >= 1

        # Verify stream was removed
        get_response = playback_client.get('/api/playback/old-stream')
        assert get_response.get_json()['success'] is False


class TestPlaybackTimestamps:
    """Tests for dual-timestamp architecture"""

    def test_heartbeat_updates_last_update_only(self, playback_client):
        """Heartbeat (same position) updates last_update but not position_timestamp"""
        # Create initial entry
        playback_client.post('/api/playback/stream1', json={
            'position': 10000,
            'duration': 180000,
            'playback_status': 'playing'
        })

        # Wait a bit
        time.sleep(0.05)

        # Send heartbeat with same position
        playback_client.post('/api/playback/stream1', json={
            'position': 10000,
            'duration': 180000,
            'playback_status': 'playing'
        })

        # Data should still be fresh (not stale)
        response = playback_client.get('/api/playback/stream1')
        data = response.get_json()
        assert data['is_stale'] is False

    def test_position_change_updates_both_timestamps(self, playback_client):
        """Position change updates both timestamps"""
        # Create initial entry
        playback_client.post('/api/playback/stream1', json={
            'position': 10000,
            'duration': 180000,
            'playback_status': 'playing'
        })

        # Update with new position
        playback_client.post('/api/playback/stream1', json={
            'position': 15000,
            'duration': 180000,
            'playback_status': 'playing'
        })

        # Interpolation should start from new position
        response = playback_client.get('/api/playback/stream1')
        data = response.get_json()
        assert data['interpolated_position'] >= 15000
