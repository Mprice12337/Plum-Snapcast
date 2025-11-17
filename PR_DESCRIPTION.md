# Fix AirPlay artwork loading issues and race conditions

## Summary

Fixes critical artwork loading issues that prevented album art from displaying correctly during AirPlay playback, especially in pause-then-skip scenarios.

## Issues Fixed

### 1. Missing Artwork Cache Directory
**Problem**: The shairport-sync artwork cache directory (`/tmp/shairport-sync/.cache/coverart/`) was never created during container startup, causing all artwork to fail silently.

**Impact**:
- Shairport-sync couldn't write artwork files
- Control script couldn't read artwork files
- Frontend always received `null` for artwork URLs
- Intermittent behavior where artwork briefly appeared then disappeared

**Fix**: Added directory creation to `backend/scripts/setup.sh`:
```bash
mkdir -p /tmp/shairport-sync/.cache/coverart
chmod -R 777 /tmp/shairport-sync/.cache
```

**Commit**: `8e74fbb`

### 2. Artwork Race Condition
**Problem**: AirPlay sends metadata events in this order during track skips:
1. `pcen` (artwork loaded) → Applied to Snapcast
2. `mper` (track ID changed) → Cleared all metadata including artwork

**Impact**: Artwork would flash correctly for 50-100ms, then revert to placeholder

**Fix**: Added timestamp-based artwork protection in `backend/scripts/airplay-control-script.py`:
- Track when artwork is loaded
- On track change, check if artwork loaded within last 2 seconds
- If yes: Keep artwork (it's for the new track)
- If no: Clear artwork (it's stale from old track)

**Commit**: `1be8621`

### 3. Invalid Artwork URL Validation
**Problem**: Backend sometimes returned `null` or empty string for `artUrl`, which frontend accepted as valid, causing browser to show broken image icon.

**Impact**: Blue question mark icon instead of placeholder SVG

**Fix**: Changed artwork validation from `!== undefined` to truthy check in `frontend/App.tsx`:
```typescript
// OLD: if (metadata.artUrl !== undefined)
// NEW: if (artUrl && artUrl.trim() !== '')
```

**Commits**: `0e45be0`, `78c7739`

### 4. Delayed Artwork During Pause-Then-Skip
**Problem**: When skipping tracks while paused, AirPlay waits to send artwork until playback resumes (1-10 second delay).

**Impact**: Artwork would stay as placeholder even after track resumed

**Fix**: Added periodic retry mechanism in `frontend/App.tsx`:
- Detects when placeholder artwork is showing
- Polls backend every 1 second for up to 15 seconds
- Applies artwork as soon as it arrives

**Commits**: `8cd47d1`, `a8196c7`

## Changes Made

### Backend

**`backend/scripts/setup.sh`**:
- Added artwork cache directory creation with proper permissions
- Logs creation for visibility during container startup

**`backend/scripts/airplay-control-script.py`**:
- Added `last_artwork_load_time` timestamp tracking
- Modified track change handler to preserve recently-loaded artwork
- Enhanced logging for debugging artwork flow

### Frontend

**`frontend/App.tsx`**:
- Fixed malformed SVG placeholder causing broken image icons
- Added artwork URL validation (truthy check + trim)
- Implemented periodic artwork retry mechanism (1s intervals, 15s timeout)
- Added comprehensive logging for debugging:
  - `[Metadata]` - Metadata handler artwork processing
  - `[Polling]` - Background sync artwork processing
  - `[ArtworkRetry]` - Periodic retry mechanism status
  - Shows artwork type (valid/null/empty/undefined) and preview

### Documentation

**`docs/ARCHITECTURE.md`**:
- Updated script references (process-airplay-metadata.sh → airplay-control-script.py)
- Rewrote Section 4.3 (Metadata Storage) with correct paths and requirements
- Rewrote metadata flow diagram showing complete data flow
- Updated Decision 5 to reflect stream properties approach
- Added artwork troubleshooting section with diagnostic commands
- Documented both critical bugs fixed

## Testing

### Manual Testing Performed

1. **Normal playback** (playing → skip):
   - ✅ Artwork loads within 1-2 seconds
   - ✅ Transitions smoothly between tracks

2. **Pause-then-skip**:
   - ✅ Metadata (title/artist) appears immediately
   - ✅ Placeholder shown initially
   - ✅ Artwork loads within 1-10 seconds after resume
   - ✅ No broken image icons

3. **Fast consecutive skips**:
   - ✅ Artwork from new track not cleared by track change event
   - ✅ No flickering between correct and placeholder artwork

4. **Edge cases**:
   - ✅ Tracks without artwork show placeholder indefinitely
   - ✅ Same artwork on consecutive tracks loads correctly
   - ✅ Backend timeout (15s) works correctly

### Diagnostic Output

Before fix:
```
=== Artwork Cache Files ===
ls: /tmp/shairport-sync-covers/: No such file or directory
```

After fix:
```
=== Artwork Cache Files ===
-rw-r--r-- 1 snapcast audio 42156 Nov 17 10:23 cover-1234567890.jpg
```

Frontend logs show proper flow:
```
[Metadata] artUrl received: type=undefined
[Metadata] ⚠ New track without artwork - using placeholder
[ArtworkRetry] ⏱ Starting periodic check for "Track Name"
[ArtworkRetry] Attempt 3/15: Checking backend...
[ArtworkRetry] Backend responded: artUrl type=valid
[ArtworkRetry] ✓ SUCCESS! Found artwork (142567 chars)
```

## Deployment Notes

### Required Actions

Since `setup.sh` runs during container build, a **rebuild and redeploy** is required:

```bash
# On Raspberry Pi
cd ~/Plum-Snapcast
git pull
cd docker
docker compose build backend
docker compose down
docker compose up -d

# Verify cache directory created
docker exec plum-snapcast-server ls -la /tmp/shairport-sync/.cache/coverart/
```

### Verification

After deployment:
```bash
# 1. Check cache directory exists
docker exec plum-snapcast-server ls -la /tmp/shairport-sync/.cache/coverart/

# 2. Play a track and check for artwork files
docker exec plum-snapcast-server ls -lht /tmp/shairport-sync/.cache/coverart/ | head -5

# 3. Check control script logs
docker logs plum-snapcast-server 2>&1 | grep "Artwork"
```

## Breaking Changes

None - all changes are backwards compatible.

## Commits

- `02d3df4` - docs: Update ARCHITECTURE.md with artwork implementation details
- `1be8621` - fix: Prevent artwork from being cleared immediately after loading
- `8e74fbb` - fix: Create artwork cache directory on container startup
- `dd76594` - debug: Add comprehensive artwork loading diagnostics
- `0e45be0` - fix: Validate artwork URLs to prevent broken image icons
- `78c7739` - fix: Correct malformed SVG placeholder causing broken image icons
- `8cd47d1` - fix: Add periodic artwork retry for delayed AirPlay artwork
- `a8196c7` - fix: Fetch artwork when resuming playback after skip-while-paused

## Related Issues

Fixes artwork loading issues reported during pause-then-skip testing.
