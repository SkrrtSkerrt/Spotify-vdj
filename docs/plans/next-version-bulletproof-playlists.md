# Spotify VDJ Next Version: Bulletproof Playlist Loading Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make playlist loading feel instant, resilient, and understandable by caching the last successful playlist list, refreshing in the background, and showing clear rate-limit/offline states instead of a blank UI.

**Architecture:** Keep Spotify API access in `spotify_client.py`, add a tiny local playlist snapshot cache beside the existing config files, and teach `gui/main_window.py` to render cached data immediately while a background refresh runs. The cache stores the last good playlist list only; track fetching stays lazy and happens only when a playlist is selected.

**Tech Stack:** Python, PyQt5, spotipy, `unittest`, JSON file storage.

---

## What this version should change

1. On launch, show the last successful playlist list immediately if it exists.
2. Refresh playlists in the background after the UI is already usable.
3. If Spotify rate-limits or the network is flaky, keep the cached playlists visible and explain what happened.
4. Add a manual refresh control with a short cooldown so the app does not keep hammering Spotify.
5. Keep track loading lazy: only fetch tracks when a playlist is actually selected.

## Non-goals

- No downloader engine rewrite.
- No Spotify search or matching changes.
- No release/tag/version bump yet.
- No Windows build or GitHub release work yet.

## Proposed cache shape

Store the playlist snapshot in a small JSON file under the user home directory, using the same style as the existing config file.

Example payload:

```json
{
  "updated_at": "2026-05-27T14:22:11Z",
  "account_id": "spotify-user-id-or-null",
  "playlists": [
    {
      "id": "37i9dQZF1DXcBWIGoYBM5M",
      "name": "Daily Mix 1",
      "total": 42,
      "image": "https://...",
      "description": "",
      "owner_name": "Spotify",
      "public": true
    }
  ]
}
```

The cache should be treated as advisory, not authoritative: if Spotify later returns a fresh list, the fresh list replaces the cache.

---

## Task 1: Add a playlist snapshot cache helper

**Objective:** Create a tiny helper module that can save and load the last good playlist list.

**Files:**
- Create: `playlist_cache.py`
- Create: `tests/test_playlist_cache.py`

**Implementation notes:**
- Store the cache in a single JSON file in the user home directory, using a stable filename such as `~/.spotify_vdj_playlists_cache.json`.
- Keep the helper narrow: load, save, clear, and read freshness metadata.
- If the cache file is missing, unreadable, or corrupt, return `None` or an empty result instead of raising.
- Preserve the playlist list exactly as the UI needs it today: `id`, `name`, `total`, `image`, `description`, `owner_name`, `public`.

**Verification:**
- Round-trip a fake playlist list through save/load.
- Confirm a corrupt JSON file does not crash the loader.
- Confirm the cache helper does not modify the playlist payload structure.

**Expected test command:**
- `./.venv/bin/python -m unittest tests.test_playlist_cache -v`

---

## Task 2: Show cached playlists immediately at startup

**Objective:** Make the playlist pane useful before the network request finishes.

**Files:**
- Modify: `gui/main_window.py`
- Modify: `main.py` only if startup wiring needs a tiny hook for cache loading

**Implementation notes:**
- Change `_load_playlists()` so it first tries to load cached playlists and render them right away.
- Keep the playlist list enabled if cached data exists, even while the background refresh is running.
- Add a status message like `Showing cached playlists while Spotify refreshes in the background…`.
- If there is no cache, keep the current loading state.
- When fresh playlists arrive in `_on_playlists_loaded()`, replace the cache contents and refresh the list.
- If the refresh fails, do not blank out the cached list; keep what the operator can already see.

**Verification:**
- Launch the app with a valid cache and no network: cached playlists still appear.
- Launch with no cache: behavior stays the same as today.
- Launch with cache plus network: cached playlists appear first, then refresh silently to the latest list.

**Suggested smoke test:**
- Start the app twice.
- First run populates the cache.
- Second run should show playlists immediately, before Spotify finishes the background refresh.

---

## Task 3: Add a deliberate refresh control with cooldown

**Objective:** Give the operator a clear manual refresh button without creating a request storm.

**Files:**
- Modify: `gui/main_window.py`

**Implementation notes:**
- Add a `Refresh Playlists` action or button near the playlist controls.
- Disable the control while a refresh is already in flight.
- Add a short cooldown after a rate limit response so repeated clicks do not keep retrying instantly.
- Keep the current selected playlist and track table visible while refresh is happening, unless the selected playlist truly disappears.
- Reuse the existing background loader thread pattern so this stays consistent with the current Qt architecture.

**Verification:**
- Clicking refresh once starts a single background load.
- Clicking refresh again during the load does nothing except update the status text.
- A rate-limit response disables refresh temporarily and explains why.

---

## Task 4: Make rate-limit and offline states explicit in the UI

**Objective:** Replace the vague blank-loading feeling with clear, human-readable status.

**Files:**
- Modify: `spotify_client.py`
- Modify: `gui/main_window.py`
- Update: `tests/test_spotify_client.py`

**Implementation notes:**
- Preserve the existing `RuntimeError` mapping for rate limits, but make sure the user-facing text clearly says Spotify is rate-limiting playlist loading.
- If the Spotify exception includes retry timing, carry that information through in a compact form so the UI can show a better message.
- In the main window, distinguish between:
  - normal loading
  - cached data being shown
  - refresh in progress
  - Spotify rate-limited
  - network unavailable
- Keep the current playlist list visible on rate-limit or network failures if a cache exists.
- Do not clear the playlist pane just because the refresh failed.

**Verification:**
- Force a mocked 429 and confirm the UI shows a rate-limit message instead of a blank state.
- Force a network timeout and confirm the UI says the request failed but keeps cached data if present.
- Confirm the playlist loader still raises a clean `RuntimeError` for the UI to display.

**Suggested test cases:**
- Update `tests/test_spotify_client.py` to cover any richer rate-limit text.
- Add a UI-focused unit test if a light-weight harness is practical; otherwise keep this as a manual smoke-test step.

---

## Task 5: Keep lazy track loading behavior intact and verify the flow end to end

**Objective:** Make sure the new playlist cache does not accidentally make the app fetch too much too early.

**Files:**
- Review: `gui/main_window.py`
- Review: `spotify_client.py`
- Review: `tests/test_spotify_client.py`
- Optionally create: `tests/test_main_window.py` if a small harness is useful

**Implementation notes:**
- Do not fetch tracks for every playlist at startup.
- Continue loading tracks only when a playlist is selected.
- Preserve the current partial-playlist and unsupported-row handling already shipped in `spotify_client.py` and `gui/main_window.py`.
- Keep the list cache separate from the track list so the cache stays tiny and fast.

**Verification:**
- Startup only requests playlist metadata, not every playlist’s tracks.
- Selecting a playlist still loads its tracks on demand.
- Unsupported rows, local tracks, and partial playlist warnings still behave the same as before.

**Suggested full test command:**
- `./.venv/bin/python -m unittest discover -s tests -v`

---

## Execution order

1. Build the cache helper and tests.
2. Wire cached playlist rendering into the main window.
3. Add refresh control and cooldown.
4. Improve status text for rate-limit/offline states.
5. Run the full test suite and do a manual smoke pass.

## Definition of done

- Cached playlists appear immediately on relaunch.
- The UI stays useful when Spotify is slow or rate-limited.
- Manual refresh is present but controlled.
- Track loading remains lazy.
- The full test suite still passes.
- No version bump, tag, or release is created yet.
