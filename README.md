# Music Finder Bot

A Telegram bot that downloads publicly accessible Instagram Reels, extracts a short audio sample, and uses ACRCloud to identify the song. When available, it returns the track details and links to streaming platforms.

## GitHub description

**Telegram bot that downloads Instagram Reels, extracts audio with FFmpeg, identifies songs using ACRCloud, and returns available streaming links.**

## Features

- Accepts Instagram Reel and video-post URLs (`/reel/`, `/reels/`, `/p/`, and `/tv/`).
- Downloads accessible videos using `yt-dlp`.
- Extracts the first 12 seconds of audio with FFmpeg.
- Sends the downloaded video and extracted MP3 sample back to Telegram.
- Sends the audio sample to the ACRCloud music-identification API.
- Displays the identified title, artist, album (when available), and provider match score.
- Adds Spotify and YouTube buttons when the recognition response provides matching track IDs.
- Deletes temporary video and audio files after processing.

## How it works

1. A user sends an Instagram Reel or video-post URL to the Telegram bot.
2. The bot validates the URL and attempts to download the public video with `yt-dlp`.
3. FFmpeg extracts a 12-second audio sample.
4. The bot sends the sample to ACRCloud for music identification.
5. The bot replies with the video, audio sample, and the match details and streaming links returned by the provider.

## Technology stack

- **Python**
- **python-telegram-bot** — Telegram bot interface
- **yt-dlp** — video extraction and downloading
- **FFmpeg / FFprobe** — audio extraction
- **ACRCloud** — music recognition
- **Requests** — HTTP requests to the recognition API
- **python-dotenv** — local environment configuration

## Requirements

- Python 3.11 or newer
- FFmpeg and FFprobe installed and available on `PATH`
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An ACRCloud project with its host, access key, and access secret
- Internet access while the bot is running

## Setup (Windows / PowerShell)

### 1. Clone the repository

```powershell
git clone <YOUR_REPOSITORY_URL>
cd music-finder-bot
```

If you already have the project locally, open PowerShell in its project folder instead.

### 2. Create and activate a virtual environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Python dependencies

```powershell
python -m pip install --upgrade pip
pip install python-telegram-bot python-dotenv yt-dlp requests
```

### 4. Install FFmpeg

Install an FFmpeg build appropriate for your system and add its `bin` directory to your `PATH`. For example, with Windows Package Manager:

```powershell
winget install --id Gyan.FFmpeg.Shared -e
```

Close and reopen the terminal, reactivate the virtual environment, and verify:

```powershell
ffmpeg -version
ffprobe -version
```

### 5. Configure environment variables

Create a `.env` file in the project root:

```dotenv
TELEGRAM_BOT_TOKEN=replace_with_your_telegram_bot_token
ACRCLOUD_HOST=your_project_host
ACRCLOUD_ACCESS_KEY=your_acrcloud_access_key
ACRCLOUD_ACCESS_SECRET=your_acrcloud_access_secret
```

Use the exact host displayed by your ACRCloud project. Store the host as the hostname only; do not add `https://` or `/v1/identify`.

**Never commit `.env` or publish tokens, API keys, secrets, browser cookies, or other credentials.** Add `.env` to `.gitignore` before committing.

### 6. Run the bot

```powershell
python bot.py
```

Open Telegram, start your bot, and send it a publicly accessible Instagram Reel URL.

## Usage

Supported URL path formats include:

```text
https://www.instagram.com/reel/SHORTCODE/
https://www.instagram.com/reels/SHORTCODE/
https://www.instagram.com/p/SHORTCODE/
https://www.instagram.com/tv/SHORTCODE/
```

The bot attempts to download the video, extracts its first 12 seconds of audio, and submits that sample to ACRCloud. A successful result may include the track title, artist, album, match score, and available Spotify or YouTube links.

## Current limitations (v1.0)

- **Recognition is based on a single 12-second sample from the beginning of the video.** Clips with speech, loud sound effects, very short music sections, or heavy background noise may not be identified correctly.
- ACRCloud scores are provider match scores; they should not be interpreted as calibrated probabilities that a result is correct.
- Streaming links are shown only when ACRCloud returns the required external metadata. Links and catalog availability are not guaranteed.
- Instagram downloading depends on what Instagram and `yt-dlp` can access at the time. Private, restricted, login-gated, or unsupported posts may fail. Updating `yt-dlp` may help, but does not guarantee success.
- The bot's current download and upload size limits are configured in `bot.py`; videos above the configured limit are rejected.
- The current version does not include MongoDB caching, a custom reference-music catalog, multi-segment recognition, or background-music separation.
- The bot must be running on your computer or a deployed server to respond to messages. A local setup is unavailable when the machine or process is stopped.

## Troubleshooting

### `FFmpeg is not installed or missing from PATH`

Run `ffmpeg -version` and `ffprobe -version`. Install FFmpeg or fix the `PATH`, then reopen your terminal.

### Instagram reports an empty media response or no video

Confirm the URL opens in a browser and points to an accessible video. Update `yt-dlp`:

```powershell
python -m pip install --upgrade yt-dlp
```

Instagram may change its access or media-delivery behaviour, so some public URLs may still fail. Do not share browser cookies or login credentials when asking for help.

### ACRCloud returns no match

Check that the project host, access key, and access secret in `.env` are correct and that the selected ACRCloud project supports music fingerprint identification. Try a clip with a clearly audible, commercially released song. A failed match can also mean that the sample is too short, noisy, speech-dominated, or not represented in the provider's catalog.

### Bot starts but does not respond

Confirm that `TELEGRAM_BOT_TOKEN` is valid, the Python process is still running, and the bot has been started in Telegram with `/start`.

## Security and responsible use

- Keep all tokens and API credentials private. If a token is exposed, revoke or rotate it immediately.
- Consider adding a Telegram user allowlist, request limits, and usage quotas before allowing public use.
- Temporary downloaded media is removed after each request by the current implementation, but logs and external providers may still process request metadata.
- Only process media you are permitted to access and use. Respect Instagram's terms, copyright, privacy, and the applicable terms of the recognition provider.
- Do not use personal Instagram session cookies as a shared authentication mechanism for untrusted users.

## Version

**v1.0** — Initial working release: Instagram URL handling, video download, 12-second audio extraction, ACRCloud identification, and available Spotify/YouTube links.
