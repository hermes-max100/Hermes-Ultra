# Hermes Video Watch

`src/system/video-watch.sh` wires video ingestion into Hermes for public URLs
and local video files.

## Install

```bash
src/system/video-watch.sh install
```

This creates `.hermes/venvs/video-watch` and installs `yt-dlp` there.

System dependencies:

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
```

Optional local transcription:

```bash
src/system/video-watch.sh install --with-whisper
```

Optional local OCR for burned-in captions and UI text:

```bash
src/system/video-watch.sh install --with-ocr
src/system/video-watch.sh blueprint "URL_OR_FILE" --frames 30 --mode interval --no-transcribe --ocr
```

## Use

```bash
src/system/video-watch.sh doctor
src/system/video-watch.sh metadata "https://www.instagram.com/reel/Db1USzsMNnZ/"
src/system/video-watch.sh blueprint "https://www.instagram.com/reel/Db1USzsMNnZ/" --frames 30 --mode scene
src/system/video-watch.sh blueprint "https://www.instagram.com/reel/Db1USzsMNnZ/" --frames 30 --mode interval --whisper-model tiny --ocr
src/system/video-watch.sh blueprint "https://www.instagram.com/reel/Db1USzsMNnZ/" --frames 30 --mode interval --no-transcribe --ocr
```

Outputs are written under `.hermes/reports/video-watch`.

## Policy

The driver is permissive for public URLs and local files. It does not perform
public actions and does not use browser cookies or private sessions by default.
Do not use it to bypass access controls, scrape private accounts, expose
credentials, or repost copyrighted material.
