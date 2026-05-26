# Spotify VDJ v0.1.10 Release Notes

Date: 2026-05-26

## Fix

- Fixed playlist loading for playlists whose first returned Spotify page contains only `track: null` items or otherwise yields no usable tracks even though the playlist total is nonzero.
- The loader now keeps splitting the page range until it finds playable tracks instead of stopping at the first non-empty but unusable page.

## Result

This addresses cases where the playlist list shows a valid count, but clicking the playlist still produced:

- `Spotify returned 0 of 39 tracks for this playlist`

## Verification

- Syntax checks passed.
- Full test suite passed: 22/22.

## Notes

- v0.1.9 fixed playlist totals in the sidebar.
- v0.1.10 fixes the actual track-loading path.
