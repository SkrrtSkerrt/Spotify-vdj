# Spotify VDJ

Download tracks from your Spotify playlists as local MP3s so Virtual DJ can use them with full waveform, BPM detection, and cue points.

## Setup

### 1. Prerequisites
- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and on your PATH (required for audio conversion)
- If FFmpeg is missing, the app will show install instructions on launch

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Create a Spotify Developer App
1. Go to https://developer.spotify.com/dashboard
2. Click **Create App**
3. Fill in any name/description
4. Set Redirect URI to: `http://127.0.0.1:8888/callback`
5. Copy your **Client ID** and **Client Secret**

If port 8888 is already in use on your machine, pick another free localhost port and use the exact same Redirect URI in both Spotify and the app settings.

### 4. Run the app
```bash
python main.py
```

On first run, the Setup dialog will ask for your credentials and output folder.

### 5. Set up VDJ
In Virtual DJ, go to **Settings → Folders** and add the output folder you chose. VDJ will automatically detect downloaded tracks.

## Windows: best install path

If you want the full GUI on Windows, the smoothest approach is:

1. Install Python 3.10 or 3.11
2. Install FFmpeg and add it to PATH
3. Copy this project to the Windows machine
4. Run `build_windows.bat` once to create the standalone app
5. Use `dist\SpotifyVDJ.exe` as your launcher

The build script now bundles the app icon and sets up a local build environment automatically.

## Windows build notes

- `build_windows.bat` builds a one-file GUI executable with PyInstaller
- The app icon lives at `icon.ico`
- The executable still needs FFmpeg available on the Windows machine unless you bundle FFmpeg separately, or place `ffmpeg.exe` next to the EXE
- If you want true one-click installation, wrap `dist\SpotifyVDJ.exe` with an installer tool like Inno Setup or NSIS

## Usage

1. Select a playlist from the left panel
2. Click tracks to select them (Ctrl+click for multiple)
3. Click **Download Selected** or **Download All**
4. Tracks appear in VDJ's library within seconds of download completing

Already-downloaded tracks show "Downloaded" in green — re-downloading is skipped automatically.

## Building a Windows .exe

On your Windows machine:
```
build_windows.bat
```

This creates `dist\SpotifyVDJ.exe` — a standalone app with no Python install required.

## Notes

- Audio is downloaded at **320kbps MP3** from YouTube Music
- Duration matching (±15 seconds) ensures the correct version of a track is downloaded
- ID3 tags (artist, title, album art) are embedded automatically
- The Spotify token is cached locally so you only need to log in once
