# Spotify VDJ v0.1.9 Release Notes

Date: 2026-05-26

## Highlights

- Fixed playlist totals so private/custom playlists that expose the count through `items.total` no longer show as `0` tracks.
- Added a regression test for the playlist total resolution path.
- Kept the playlist mismatch warning in place so the app now surfaces cases where Spotify reports more tracks than the API returns.
- Updated the app title and version string to `Spotify VDJ v0.1.9`.

## What was fixed

This release addresses the bug where playlists like `Sunny UKG` could appear with `0` tracks even though Spotify reported a valid total.

The client now resolves playlist totals in this order:

1. `tracks.total`
2. `items.total`
3. fallback detail request for `tracks.total`

## Verification

- Syntax checks passed.
- Full test suite passed: 21/21.
- Commit published: `640eaad`
- Tag published: `v0.1.9`

## Packaging note

The Windows portable build is still based on `build_windows.bat` and `SpotifyVDJ.spec`.
FFmpeg remains a runtime dependency unless it is bundled alongside the executable.
