# Spotify VDJ v0.1.12 Release Notes

Date: 2026-05-27

## Fixes

- Spotify playlist loading now fails fast on HTTP 429 instead of hanging for a very long retry window.
- The app now shows a clear rate-limit message when Spotify tells it to slow down.
- Spotify client startup uses shorter request timeouts and disables long status-code retry delays for playlist loading.

## Verification

- Spotify client tests passed.
- Full test suite passed.

## Notes

- If Spotify rate-limits the account, wait a few minutes and reopen the app.
- v0.1.12 is a hotfix for the blank-loading behavior seen after a 429 response.
