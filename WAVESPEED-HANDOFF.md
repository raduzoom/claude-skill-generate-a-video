# Handoff: add WaveSpeed (Topaz upscale + frame interpolation) to video-generator-via-api

Written 2026-11-23 from the One Room Iași reel session. The project has `WAVESPEED_API_KEY` in `.env` but no
WaveSpeed code yet: `generate_video.py` only knows KIE / ENHANCOR (images) and KINOVI / ENHANCOR / HIGGSFIELD (videos).

## Goal

Add WaveSpeed as a **post-processing** provider: Topaz upscale (Proteus by default) and Topaz frame
interpolation (Apollo by default), usable

1. as an optional step after `combine_videos()` in the Shorts pipeline (`--upscale`, `--interpolate FPS`), and
2. standalone on any local file: `.venv/bin/python3 generate_video.py --postprocess IN.mp4 --upscale --interpolate 48`.

Both steps cost money. Never run them by default; they only run when the flag is given (see
`~/Dropbox/Configs/claude/.claude/guides/paid-generation.md`: an agent must get the user's yes, with the price, before each run).

A working standalone version already exists:
`/Users/raduh/Dropbox/Ai Playground/oneroom iasi/video edit/gta/topaz_wavespeed.py`. Port its logic and don't
reinvent it.

## API facts (from wavespeed.ai docs, read 2026-11-23)

Auth: `Authorization: Bearer $WAVESPEED_API_KEY`. Base: `https://api.wavespeed.ai/api/v3`.

**Upload (inputs must be URLs).** Direct upload:
1. `POST /media/uploads` JSON `{"filename": "x.mp4", "size": <exact bytes>, "content_type": "video/mp4"}`
2. `PUT` the bytes to `data.upload.url` with exactly `data.upload.headers`. **No Authorization header** on the PUT; use the URL as-is.
3. Use `data.download_url` as the input. Limit 200 MB; files are deleted after 7 days.
Legacy: `POST /media/upload/binary`, multipart field `file`, max 100 MB, URL in `data.download_url`.

**Upscale.** `POST /topaz/video/upscale`
- `video` (URL, required)
- `model`: default `Proteus`; also `Proteus Natural`, `Rhea`, `Artemis *`, `Gaia *`, `Theia *`, `Iris *`, `Dione *`
- `target_resolution`: `720p` | `1080p` (default) | `2k` | `4k`, aspect ratio kept

**Frame interpolation.** `POST /topaz/video/frame-interpolation`
- `video` (URL, required)
- `model`: `Apollo` (default) | `Apollo Fast` | `Chronos` | `Chronos Fast` | `Aion`
- `resolution`: default `1080p`
- `fps`: 30 | 48 | 50 | 60 (default) | 120
- `slowmo`: 1 | 2 | 4 | 8

**Async.** Submit returns `data.id`. Poll `GET /predictions/{id}/result`:
- `data.status == "completed"`: the file is at `data.outputs[0]`.
- `failed` / `cancelled` / `timeout` / `deleted`: read `data.error`.
- Anything else: keep polling.
- Back off 10 s on 429 / 5xx.

**Never retry the submit POST**: a retry creates a second billed job. Save the id before polling so a crash can resume.

**Price.**
- Billed on source seconds, rounded up, $0.10 minimum, totals rounded up to $0.10.
- Examples for a 10 s source: upscale at 1080p is $0.20 (4K $0.50). Interpolation with Apollo at 1080p / 60 fps is $0.20 (Fast $0.10, Aion $0.40).
- fps and slowmo change the price, but no formula is published. `https://wavespeed.ai/docs/pricing-api` may give a quote endpoint; it is not read yet. Read it and use it to print the price before submitting.

## Implementation sketch (match the existing provider layering)

- `_wavespeed_headers()`, `_wavespeed_upload(path) -> url`, `_wavespeed_submit(endpoint, body) -> id`,
  `_wavespeed_poll(id) -> output_url`, in a new `# POST-PROCESSING PROVIDERS` block.
- `topaz_upscale(path, out, model="Proteus", res="1080p")` and `topaz_interpolate(path, out, model="Apollo", fps=48, res="1080p")`.
- `check_env()`: require `WAVESPEED_API_KEY` only when a post-processing flag is used.
- Record the WaveSpeed ids, models, prices and output URLs in the run doc (`save_run_doc`).
- Document the flags in `CLAUDE.md` (Provider switching table + Running the pipeline).

## Gotchas

- Upscaling a file that is already 1080×1920 to `1080p` only enhances it. Upscale the sources before the final composite when possible.
- Interpolation can blend frames across hard cuts. Check frames either side of each cut after a run.
- The project uses git-sync (`.git` is a file). Don't commit unless the user asks.

## Done when

- Both flags work on a local file and in the pipeline.
- The price is printed before submit, and the id is saved before polling.
- One short test run has been made, with the user's yes first, and its output checked with ffprobe (size, fps, frame count).
