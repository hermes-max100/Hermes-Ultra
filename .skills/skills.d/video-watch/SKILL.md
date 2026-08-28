---
name: video-watch
description: Hermes video ingestion and reverse-engineering skill for public URLs and local files using yt-dlp, ffmpeg, and local frame/transcript artifacts.
---

# Video Watch

## Purpose

Analyze public videos and local video files so Hermes can reverse-engineer
tutorials, funnels, demos, UI walkthroughs, and creator workflows into local
notes, blueprints, skills, and implementation plans.

## Driver

Use:

```bash
src/system/video-watch.sh doctor
src/system/video-watch.sh install
src/system/video-watch.sh metadata "URL"
src/system/video-watch.sh download "URL"
src/system/video-watch.sh understand "URL_OR_FILE" --frames 30 --mode scene
src/system/video-watch.sh blueprint "URL_OR_FILE" --frames 30 --mode scene
src/system/video-watch.sh blueprint "URL_OR_FILE" --frames 30 --mode interval --whisper-model tiny --ocr
src/system/video-watch.sh blueprint "URL_OR_FILE" --frames 30 --mode interval --no-transcribe --ocr
```

## Behavior

- Accept public URLs supported by `yt-dlp`.
- Accept local video files.
- Extract frames with `ffmpeg`.
- Transcribe with local Whisper only when installed.
- Use `--whisper-model tiny` for fast phone/VPS runs; use `base` or larger only when accuracy matters and runtime budget allows.
- Read on-screen captions/UI text with local `tesseract` OCR when `--ocr` is enabled.
- Write artifacts under `.hermes/reports/video-watch`.
- Produce implementation extraction checklists for Hermes workflows.

## Boundaries

- Do not post, comment, like, follow, message, upload, or delete.
- Do not reuse browser cookies or private sessions by default.
- Do not bypass paywalls, access controls, private accounts, or rate limits.
- Do not expose credentials, cookies, tokens, or session data.
- Human approval is required before public posting or any account action.
