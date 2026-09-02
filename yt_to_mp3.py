"""Download YouTube audio and convert it to MP3.

Requires:
    pip install yt-dlp
    ffmpeg on PATH (https://ffmpeg.org/download.html)

Usage:
    python yt_to_mp3.py "https://www.youtube.com/watch?v=..."
    python yt_to_mp3.py URL1 URL2 -o D:/Music -q 320
    python yt_to_mp3.py "https://www.youtube.com/playlist?list=..." --playlist
"""

import argparse
import shutil
import sys

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed. Run: pip install yt-dlp")


def progress_hook(d):
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "").strip()
        speed = d.get("_speed_str", "").strip()
        print(f"\r  downloading {pct} at {speed}   ", end="", flush=True)
    elif d["status"] == "finished":
        print("\r  download complete, converting to mp3...        ")


def build_options(outdir, quality, keep_playlist):
    return {
        "format": "bestaudio/best",
        "outtmpl": f"{outdir}/%(title)s.%(ext)s",
        "noplaylist": not keep_playlist,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(quality),
            },
            # writes title/artist/etc. into the mp3 tags
            {"key": "FFmpegMetadata"},
        ],
    }


def download(urls, outdir, quality, keep_playlist):
    opts = build_options(outdir, quality, keep_playlist)
    failed = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        for url in urls:
            print(f"\n> {url}")
            try:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "unknown")
                print(f"  saved: {title}.mp3")
            except Exception as e:  # noqa: BLE001 - report and continue
                print(f"  FAILED: {e}")
                failed.append(url)
    return failed


def main():
    parser = argparse.ArgumentParser(description="Convert YouTube videos to MP3.")
    parser.add_argument("urls", nargs="+", help="one or more YouTube URLs")
    parser.add_argument("-o", "--output", default="downloads",
                        help="output folder (default: ./downloads)")
    parser.add_argument("-q", "--quality", default=192, type=int,
                        choices=[64, 128, 192, 256, 320],
                        help="mp3 bitrate in kbps (default: 192)")
    parser.add_argument("--playlist", action="store_true",
                        help="download the whole playlist, not just one video")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg was not found on PATH. Install it first "
                 "(e.g. winget install Gyan.FFmpeg) and reopen your terminal.")

    failed = download(args.urls, args.output, args.quality, args.playlist)

    print(f"\nDone. Files are in: {args.output}")
    if failed:
        print("These URLs failed:")
        for url in failed:
            print(f"  - {url}")
        sys.exit(1)


if __name__ == "__main__":
    main()
