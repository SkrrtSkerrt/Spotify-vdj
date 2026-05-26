# Next Steps

Based on the current review, the most useful follow-up tasks are:

1. **Fix cancelled queued downloads**
   - Update `download_manager.py` so cancelling a pending job also updates the UI/state.
   - Ensure the queue row changes to `Cancelled` instead of staying stuck on `Queued`.

2. **Unify the Spotify redirect URI**
   - Pick one redirect URI and use it everywhere:
     - `config.py`
     - `gui/setup_dialog.py`
     - `README.md`
     - any saved config files
   - Prefer the loopback IP form (`http://127.0.0.1:8888/callback`) to avoid Spotify's localhost warning.

3. **Avoid redirect port conflicts**
   - Check whether port `8888` is already in use before auth starts.
   - If needed, let the user choose a different callback port.

4. **Fix the Windows build script**
   - Add the missing `icon.ico`, or remove the `--icon=icon.ico` flag from `build_windows.bat`.

5. **Optional cleanup**
   - Confirm the README matches the actual behavior of the app.
   - Consider adding a small regression test for queue cancellation logic.
