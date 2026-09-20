# yt_to_mp3

Downloads the audio track from YouTube and converts it to MP3 with tags.

## Installation

```
pip install yt-dlp
winget install Gyan.FFmpeg     # ffmpeg must be on PATH
```

## Graphical interface

```
python yt_to_mp3_gui.py
```

A tkinter window (part of the Python standard library, no extra
dependencies):

- a language selector in the header — Russian or English, switched live and
  remembered for the next run;
- a field for several links — one per line;
- destination folder picker and an "Open" button;
- bitrate from 64 to 320 kbps and a "Download the whole playlist" checkbox —
  a playlist is saved into its own subfolder named after the playlist;
- progress bar with speed and remaining time, plus a "Cancel" button;
- a log that highlights successful and failed downloads.

Downloading runs on a background thread, so the window never freezes;
progress reaches the interface through a queue (Tk widgets may only be
touched from the main thread).

The chosen language is stored in a small JSON file outside the project:
`%APPDATA%\yt_to_mp3\settings.json` on Windows,
`~/.config/yt_to_mp3/settings.json` on Linux,
`~/Library/Application Support/yt_to_mp3/settings.json` on macOS. Deleting it
simply resets the app to Russian.

## Command line

```
python yt_to_mp3.py "https://www.youtube.com/watch?v=..."
python yt_to_mp3.py URL1 URL2 -o D:/Music -q 320
python yt_to_mp3.py "https://www.youtube.com/playlist?list=..." --playlist
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `-o`, `--output` | destination folder | `./downloads` |
| `-q`, `--quality` | mp3 bitrate: 64, 128, 192, 256, 320 | `192` |
| `--playlist` | download the whole playlist instead of a single video, into a subfolder named after it | off |

## Layout

| File | Purpose |
| --- | --- |
| `yt_to_mp3.py` | download logic + command-line interface |
| `yt_to_mp3_gui.py` | tkinter window on top of the same logic |
| `test_yt_to_mp3.py` | unit tests for the download logic (no network, no ffmpeg) |
| `test_yt_to_mp3_gui.py` | unit tests for the translations and settings file (no window) |

## Tests

```
python -m unittest discover -v
```
