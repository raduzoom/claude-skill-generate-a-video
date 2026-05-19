Generate a YouTube Short by running the AI video pipeline.

## Pre-flight check

Before running, verify that `video_ideas.txt` contains at least one real idea (not just the "Example Idea Name" placeholder). If it only has the placeholder, stop and tell the user to fill in their ideas first.

## Steps

### 1. Install dependencies (if needed)

Verify the venv exists:
```
test -f .venv/bin/python3 && echo "OK" || echo "MISSING"
```
If missing, run: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

### 2. Run the generation pipeline

Run the script using the project venv:
```
.venv/bin/python3 generate_video.py
```

This takes roughly 10–25 minutes (image generation + video generation + upload). Keep the user informed that it's running — share progress lines as they appear. Do NOT show the raw `---RESULT_JSON---` block to the user.

### 3. Parse the result

Find the JSON between the `---RESULT_JSON---` and `---END_RESULT---` markers in the script output. Extract:
- `idea_name`
- `title_examples` (array of style examples)
- `catbox_url`
- `output_file`
- `run_file`

### 4. Generate a title

Create ONE new title in the **exact same style** as the `title_examples`:
- Match the energy, length, formatting, and word choices
- Do NOT copy any example title verbatim
- Do NOT use generic phrasing that doesn't match the examples' tone

### 5. Update the video log

Append a new row to `video_log.md`. The file has a markdown table — add:
```
| YYYY-MM-DD HH:MM | <idea_name> | <generated_title> | [Link](<catbox_url>) |
```
Use the current date and time. Preserve the existing table rows.

### 6. Present results to the user

Show:
- **Idea selected:** `<idea_name>`
- **Title:** `<generated_title>`
- **Video:** `[<catbox_url>](<catbox_url>)`
- **Saved to:** `<output_file>`
