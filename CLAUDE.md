# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Automated YouTube Shorts pipeline. Given an idea defined in `video_ideas.txt`, it generates three images (Nanobanana 2), three videos (Seedance 2.0), combines them with ffmpeg (hook 4s + grid1 15s + grid2 15s), uploads the result, and logs the link.

## Running the pipeline

```bash
# Run (random idea selection)
.venv/bin/python3 generate_video.py

# Run a specific idea (partial name match, case-insensitive)
.venv/bin/python3 generate_video.py --idea "Fake Stoicism"
```

### First-time setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
xattr -w com.dropbox.ignored 1 .venv   # suppress Dropbox sync
```

## Provider switching

Set `IMAGE_PROVIDER` and `VIDEO_PROVIDER` in `.env`:

| Variable | Options |
|---|---|
| `IMAGE_PROVIDER` | `KIE` (default) · `ENHANCOR` |
| `VIDEO_PROVIDER` | `KINOVI` · `ENHANCOR` · `HIGGSFIELD` |

Each provider needs its own API key (or CLI auth) in `.env`. All providers expose the same logical interface — swapping one does not require any code change.

### Higgsfield one-time setup

```bash
# Install CLI
curl -fsSL https://raw.githubusercontent.com/higgsfield-ai/cli/main/install.sh | sh -s -- --prefix=$HOME

# Authenticate (opens browser once)
~/bin/higgsfield auth login
```

After login the credentials are stored locally and persist across runs. No API key needed in `.env`.

## Architecture of generate_video.py

The script is split into four layers:

**1. Provider implementations** (prefixed `_kie_`, `_kinovi_`, `_enhancor_`, `_higgsfield_`)
Each provider implements submit + poll functions independently. They are never called directly by `main()`. Higgsfield is a CLI subprocess provider — it downloads images to temp files and calls `higgsfield generate create seedance_2_0 --wait`, running all three jobs in parallel threads.

**2. Provider routers** (`generate_image()`, `generate_videos()`)
These read `IMAGE_PROVIDER` / `VIDEO_PROVIDER` from the environment and delegate to the correct implementation. Adding a third provider means adding an implementation block and a branch in the router — nothing else changes.

**3. Pipeline logic** (`main()`)
Calls `generate_image()` three times sequentially (hook → grid1 → grid2, each passing the previous result as `reference_url`), then calls `generate_videos()` with all three jobs at once (they poll concurrently), then downloads, ffmpegs, uploads, and writes the run doc.

**4. Parser** (`parse_ideas_file()`)
Reads `video_ideas.txt`. Recognises `[IDEA]` / `[END IDEA]` block markers, `field = value` assignments (field names are `[a-z][a-z0-9_]*`), and `#` comment lines. Multi-line field values: everything after the `field = first line` until the next `field =` or `[END IDEA]` is concatenated as continuation. `title_examples` is the only list field — each continuation line becomes one entry.

## Ideas file format

**Always follow the format shown in `examples/`.** The file `follow-format.txt` shows an older, deprecated format — do not use it.

Canonical format (from `examples/video_ideas--the-cat-waited-at-the-shelter-gate.txt`):

```
[IDEA]

name = Your Idea Name

title_examples = First example title in your target style
Second example title
Third example title

hook_image_prompt = Full image generation prompt.
Can span multiple lines — everything until the next field
is treated as part of this field's value.

hook_video_prompt = 4-second motion prompt for the hook clip.

grid1_image_prompt = Describe a 2x3 story-grid image.
Hook image is passed as reference — maintain visual consistency.
Label each panel: Panel 1 [Top-Left]: ...

grid1_video_prompt = @image1 Animation instructions per panel (2.5s each).
Label: 1 [Top-Left]: ...

grid2_image_prompt = Second 2x3 story-grid. Grid 1 image is passed as reference.

grid2_video_prompt = @image1 Animation instructions per panel (2.5s each).

[END IDEA]
```

Key rules:
- `@image1` must appear in both `grid1_video_prompt` and `grid2_video_prompt` (Enhancor/Kinovi reference mode requires it; it is prepended automatically if missing, but explicit is better)
- `title_examples` uses continuation lines — do NOT repeat `title_examples =` per line or only the last one survives
- `#` comment lines anywhere in the file are silently skipped
- Blank lines inside a field value are preserved

## Output locations

| Path | Contents |
|---|---|
| `videos/` | Final combined MP4s (only the finished product — no parts) |
| `runs/` | Per-run `.txt` with all prompts used, asset URLs, and share link |
| `video_log.md` | Running markdown table: date · idea · generated title · link |

## After a successful run

The script prints a `---RESULT_JSON---` block containing `idea_name`, `title_examples`, `share_url`, `output_file`, and `run_file`. Use this to:
1. Generate one new title in the exact style of `title_examples` (do not copy verbatim)
2. Append a row to `video_log.md`
3. Present the share URL to the user
