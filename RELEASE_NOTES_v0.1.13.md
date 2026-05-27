# Spotify VDJ v0.1.13

## Highlights
- Persisted playlist refresh cooldown and last-opened playlist across restarts.
- Added stronger stale/fresh cache badges for playlists and tracks.
- Restores queued downloads from the last session.
- Added auto-refresh when the refresh cooldown expires.
- Added debug bundle export improvements with runtime, playlist-cache, and track-cache state.
- Continued cache-first polish to reduce Spotify API calls and rate-limit pressure.

## Verification
- Full test suite passed: 53/53
- Python bytecode compilation passed for touched modules

## Notes
- Queue persistence now includes the track payload so restored entries can resume cleanly.
- Cached playlist/track state remains account-aware and failure-tolerant.
