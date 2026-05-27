# Spotify VDJ v0.1.11 Release Notes

Date: 2026-05-27

## Improvements

- Playlist metadata is richer in the sidebar/tooltips: description, owner, and public/private state are now preserved when Spotify provides them.
- Playlist cover selection now prefers the best available image instead of assuming the first image is the one to show.
- Playlist rows now keep Spotify ordering and show a stable playlist position number.
- Unsupported rows are now kept visible and clearly labeled instead of disappearing silently.
- Spotify podcast episodes are now surfaced explicitly as unsupported items, so users can see why they are not downloadable.
- Download actions only enable for truly downloadable rows.
- The Download All button now stays disabled when there are no pending downloadable tracks.

## Fixes

- Improved resilience against mixed Spotify playlist payloads, including local files, episode rows, missing track objects, and partial API responses.
- Improved status messaging when Spotify returns fewer usable items than the playlist total.
- Cleaned up manual-search and download selection behavior so unsupported items are not treated like normal tracks.

## Verification

- Syntax checks passed.
- Full test suite passed: 24/24.
- Spotify client tests passed: 12/12.

## Notes

- v0.1.10 fixed the core playlist-loading fallback path.
- v0.1.11 builds on that by improving metadata handling, unsupported-row visibility, and the download UI.
