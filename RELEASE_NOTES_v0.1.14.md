# Spotify VDJ v0.1.14

## Highlights
- Public-release cleanup: ignored local Spotify credential/config files and token cache.
- Removed build, dist, venv, and archive leftovers from the release tree.
- Verified the repo is clean and free of obvious secret-bearing files before tagging.
- No functional feature changes in this release; this is a hygiene and ship-ready drop.

## Verification
- Local secret scan completed with no hardcoded credentials found in source.
- Git working tree is clean after the cleanup commit.
- Release prep verified against the current main branch state.

## Notes
- This drop is intended for public publication with sensitive local state removed.
- Runtime Spotify credentials should be entered only on the user's machine at first run.
