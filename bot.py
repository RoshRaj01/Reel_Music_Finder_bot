
import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from dotenv import load_dotenv
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ACR_HOST = os.getenv("ACRCLOUD_HOST", "").strip()
ACR_KEY = os.getenv("ACRCLOUD_ACCESS_KEY", "").strip()
ACR_SECRET = os.getenv("ACRCLOUD_ACCESS_SECRET", "").strip()

MAX_VIDEO_SIZE = 45 * 1024 * 1024
MAX_AUDIO_SIZE = 5 * 1024 * 1024
AUDIO_SAMPLE_SECONDS = 12


class YTDLLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        logger.error("yt-dlp: %s", msg)


def validate_instagram_url(raw_url):
    raw_url = raw_url.strip().rstrip(".,)>]")

    if not raw_url or any(char.isspace() for char in raw_url):
        return None

    if "://" not in raw_url:
        raw_url = "https://" + raw_url

    try:
        parsed = urlsplit(raw_url)
        hostname = (parsed.hostname or "").lower()

        if parsed.scheme not in {"http", "https"}:
            return None
        if parsed.username or parsed.password:
            return None
        if hostname not in {
            "instagram.com", "www.instagram.com", "m.instagram.com"
        }:
            return None
        if parsed.port not in {None, 80, 443}:
            return None
        if not re.fullmatch(
            r"/(?:p|reel|reels|tv)/[A-Za-z0-9_-]+/?",
            parsed.path,
            re.IGNORECASE,
        ):
            return None

        return urlunsplit(
            ("https", "www.instagram.com", parsed.path, "", "")
        )
    except ValueError:
        return None


def download_video(url, folder):
    options = {
        "format": "best[ext=mp4]/best",
        "outtmpl": str(Path(folder) / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 2,
        "max_filesize": MAX_VIDEO_SIZE,
        "logger": YTDLLogger(),
    }

    with YoutubeDL(options) as downloader:
        downloader.extract_info(url, download=True)

    files = [
        p for p in Path(folder).iterdir()
        if p.is_file()
        and not p.name.endswith((".part", ".ytdl"))
        and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
    ]

    if not files:
        raise RuntimeError("No video file was downloaded.")

    video_path = max(files, key=lambda p: p.stat().st_size)

    if video_path.stat().st_size == 0:
        raise RuntimeError("The downloaded video is empty.")
    if video_path.stat().st_size > MAX_VIDEO_SIZE:
        raise ValueError("The video exceeds the 45 MB limit.")

    return video_path


def extract_audio(video_path, output_dir):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is not installed or missing from PATH.")

    audio_path = Path(output_dir) / "sample.mp3"

    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-y", "-i", str(video_path), "-vn",
        "-t", str(AUDIO_SAMPLE_SECONDS),
        "-ac", "1", "-ar", "44100", "-b:a", "128k",
        str(audio_path),
    ]

    result = subprocess.run(
        command, capture_output=True, text=True,
        timeout=120, check=False,
    )

    if result.returncode != 0:
        raise RuntimeError("Audio extraction failed: " + result.stderr[-800:])
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("No audio was found in the video.")
    if audio_path.stat().st_size > MAX_AUDIO_SIZE:
        raise RuntimeError("Audio sample exceeds the 5 MB API limit.")

    return audio_path


def identify_song(audio_path):
    """Submit an audio sample to the signed ACRCloud identification API."""
    if not all([ACR_HOST, ACR_KEY, ACR_SECRET]):
        raise RuntimeError("ACRCloud credentials are missing from .env.")

    host = ACR_HOST.removeprefix("https://").removeprefix("http://").rstrip("/")
    if "/" in host:
        host = host.split("/", 1)[0]

    endpoint = "/v1/identify"
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(time.time()))

    string_to_sign = (
        f"POST\n{endpoint}\n{ACR_KEY}\n{data_type}\n"
        f"{signature_version}\n{timestamp}"
    )

    signature = base64.b64encode(
        hmac.new(
            ACR_SECRET.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")

    data = {
        "access_key": ACR_KEY,
        "sample_bytes": str(audio_path.stat().st_size),
        "timestamp": timestamp,
        "signature": signature,
        "data_type": data_type,
        "signature_version": signature_version,
    }

    with audio_path.open("rb") as audio_file:
        response = requests.post(
            f"https://{host}{endpoint}",
            data=data,
            files={
                "sample": (
                    audio_path.name, audio_file, "audio/mpeg"
                )
            },
            timeout=45,
        )

    response.raise_for_status()
    result = response.json()

    status = result.get("status", {})
    if status.get("code") != 0:
        logger.info(
            "ACRCloud did not identify the song: code=%s",
            status.get("code"),
        )
        return {"matched": False, "reason": status.get("msg", "No match")}

    music_items = result.get("metadata", {}).get("music", [])
    if not music_items:
        return {"matched": False, "reason": "No matching track returned"}

    track = music_items[0]
    artists = track.get("artists", [])
    artist_names = [a.get("name", "") for a in artists if a.get("name")]

    external = track.get("external_metadata", {})
    spotify = external.get("spotify", {})
    youtube = external.get("youtube", {})

    spotify_track = spotify.get("track", {})
    spotify_id = spotify_track.get("id")
    youtube_id = youtube.get("vid")

    links = {}
    if spotify_id:
        links["Spotify"] = f"https://open.spotify.com/track/{spotify_id}"
    if youtube_id:
        links["YouTube"] = f"https://www.youtube.com/watch?v={youtube_id}"

    # The score is a provider match score, not a calibrated probability.
    score = track.get("score")

    return {
        "matched": True,
        "title": track.get("title", "Unknown title"),
        "artist": ", ".join(artist_names) or "Unknown artist",
        "album": track.get("album", {}).get("name"),
        "score": score,
        "links": links,
    }


def format_song_result(song):
    lines = [
        "Song identified!",
        "",
        f"Title: {song['title']}",
        f"Artist: {song['artist']}",
    ]

    if song.get("album"):
        lines.append(f"Album: {song['album']}")

    if song.get("score") is not None:
        lines.append(f"Match score: {song['score']}/100")
        lines.append(
            "Note: this is the provider's match score, not a probability."
        )

    if not song.get("links"):
        lines.extend([
            "",
            "No direct streaming links were returned by the provider.",
        ])

    return "\n".join(lines)


def make_link_keyboard(links):
    rows = [
        [InlineKeyboardButton(name, url=url)]
        for name, url in links.items()
    ]
    return InlineKeyboardMarkup(rows) if rows else None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Welcome to Music Finder!\n\n"
        "Send a public Instagram Reel or video-post URL. "
        "I'll download it, extract its audio and try to identify the song."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Send a public Instagram Reel or video post link.\n"
        "Supported paths: /reel/, /reels/, /p/ and /tv/."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or not message.text:
        return

    reel_url = validate_instagram_url(message.text)
    if not reel_url:
        await message.reply_text("Please send a valid Instagram Reel or video-post URL.")
        return

    status = await message.reply_text("Downloading the Reel...")

    try:
        with tempfile.TemporaryDirectory(prefix="musicfinder_") as temp_dir:
            video_path = await asyncio.to_thread(download_video, reel_url, temp_dir)

            await status.edit_text("Extracting audio...")
            audio_path = await asyncio.to_thread(
                extract_audio, video_path, temp_dir
            )

            await status.edit_text("Identifying the song with ACRCloud...")

            try:
                song = await asyncio.to_thread(identify_song, audio_path)
            except Exception as exc:
                logger.exception("ACRCloud identification failed")
                song = {
                    "matched": False,
                    "reason": "Recognition service error",
                }

            # Send video and audio so the working stages remain testable.
            with video_path.open("rb") as video_file:
                video_input = InputFile(video_file, filename=video_path.name)
                if video_path.suffix.lower() == ".mp4":
                    await message.reply_video(
                        video=video_input,
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=30,
                    )
                else:
                    await message.reply_document(
                        document=video_input,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=30,
                    )

            with audio_path.open("rb") as audio_file:
                await message.reply_audio(
                    audio=InputFile(audio_file, filename="sample.mp3"),
                    title="Extracted Reel Audio (12 seconds)",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=30,
                )

            if song["matched"]:
                await message.reply_text(
                    format_song_result(song),
                    reply_markup=make_link_keyboard(song.get("links", {})),
                )
            else:
                await message.reply_text(
                    "I couldn't identify a song confidently from this sample.\n\n"
                    f"Reason: {song.get('reason', 'No match')}\n\n"
                    "The audio may be too short, contain speech/noise, "
                    "or the track may not be in the recognition catalog."
                )

        await status.delete()

    except DownloadError as exc:
        logger.warning("Instagram download failed: %s", type(exc).__name__)
        await status.edit_text(
            "I couldn't download this Instagram video. It may be private, "
            "restricted, or unsupported."
        )
    except Exception as exc:
        logger.exception("Video processing failed: %s", type(exc).__name__)
        await status.edit_text(
            "Processing failed. Check the terminal for the error details."
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from .env")

    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is not installed or missing from PATH.")

    if not all([ACR_HOST, ACR_KEY, ACR_SECRET]):
        raise RuntimeError("ACRCloud credentials are missing from .env")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    logger.info("Music Finder bot is running.")
    app.run_polling()


if __name__ == "__main__":
    main()
