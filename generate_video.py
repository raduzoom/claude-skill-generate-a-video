#!/usr/bin/env python3
"""
AI Video Generation Pipeline
Hook Image → Grid 1 Image → Grid 2 Image → 3 Videos → ffmpeg combine → upload

Image providers : KIE | ENHANCOR              (set IMAGE_PROVIDER in .env)
Video providers : KINOVI | ENHANCOR | HIGGSFIELD (set VIDEO_PROVIDER in .env)
"""

import json
import os
import re as _re
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR   = Path(__file__).parent
IDEAS_FILE = BASE_DIR / "video_ideas.txt"
VIDEOS_DIR = BASE_DIR / "videos"
RUNS_DIR   = BASE_DIR / "runs"
IMAGES_DIR = BASE_DIR / "images"

VIDEOS_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")

KIE_KEY      = os.environ.get("KIE_API_KEY", "")
KINOVI_KEY   = os.environ.get("KINOVI_API_KEY", "")
ENHANCOR_KEY = os.environ.get("ENHANCOR_API_KEY", "")

IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "KIE").upper().strip()
VIDEO_PROVIDER = os.environ.get("VIDEO_PROVIDER", "KINOVI").upper().strip()

# Higgsfield CLI path — override with HIGGSFIELD_CLI_PATH in .env
HIGGSFIELD_CLI = os.environ.get(
    "HIGGSFIELD_CLI_PATH",
    os.path.expanduser("~/bin/higgsfield"),
)

POLL_INTERVAL = 5


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE PROVIDERS
# ══════════════════════════════════════════════════════════════════════════════

# ── KIE AI (Nanobanana 2) ──────────────────────────────────────────────────────

_KIE_BASE = "https://api.kie.ai/api/v1"

def _kie_headers():
    return {"Authorization": f"Bearer {KIE_KEY}", "Content-Type": "application/json"}

def _kie_submit_image(prompt, reference_url=None):
    payload = {
        "model": "nano-banana-2",
        "input": {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "output_format": "jpg",
        },
    }
    if reference_url:
        payload["input"]["image_input"] = [reference_url]

    r = requests.post(f"{_KIE_BASE}/jobs/createTask", headers=_kie_headers(), json=payload, timeout=30)
    r.raise_for_status()
    task_id = r.json()["data"]["taskId"]
    print(f"    task: {task_id}")
    return task_id

def _kie_poll_image(task_id):
    while True:
        r = requests.get(
            f"{_KIE_BASE}/jobs/recordInfo",
            headers={"Authorization": f"Bearer {KIE_KEY}"},
            params={"taskId": task_id},
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()["data"]
        state = d["state"]
        if state == "success":
            return _kie_extract_url(d["resultJson"])
        if state == "fail":
            raise RuntimeError(f"[KIE] Image task failed: {d.get('failMsg', 'unknown')}")
        print(f"    status: {state}...")
        time.sleep(POLL_INTERVAL)

def _kie_extract_url(result_json_str):
    result = json.loads(result_json_str)
    if isinstance(result, list) and result:
        item = result[0]
        for key in ("url", "imageUrl", "image_url"):
            if key in item:
                return item[key]
    if isinstance(result, dict):
        if "resultUrls" in result:
            return result["resultUrls"][0]
        if "images" in result:
            return result["images"][0]["url"]
        for key in ("url", "imageUrl", "image_url"):
            if key in result:
                return result[key]
    raise RuntimeError(f"[KIE] Cannot extract image URL from result: {result}")


# ── ENHANCOR (Nano Banana 2 — image) ──────────────────────────────────────────
# Base URL : https://apireq.enhancor.ai/api/nano-banana-2-new/v1
# Auth     : x-api-key header
# Submit   : POST /queue  →  {"success": true, "requestId": "..."}
# Poll     : POST /status  with body {"request_id": "..."}
# Reference images passed via input_images[] (up to 14 URLs)

_ENHANCOR_IMG_BASE   = "https://apireq.enhancor.ai/api/nano-banana-2-new/v1"
_ENHANCOR_BASE       = "https://apireq.enhancor.ai/api/enhancor-video-pro/v1"

def _enhancor_headers():
    return {"x-api-key": ENHANCOR_KEY, "Content-Type": "application/json"}

def _enhancor_submit_image(prompt, reference_url=None):
    payload = {
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "webhook_url": "https://example.com/webhook",   # required field; we use polling
    }
    if reference_url:
        payload["input_images"] = [reference_url]

    r = requests.post(f"{_ENHANCOR_IMG_BASE}/queue", headers=_enhancor_headers(), json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    request_id = data.get("requestId") or data.get("request_id")
    if not request_id:
        raise RuntimeError(f"[ENHANCOR IMG] No requestId in response: {data}")
    print(f"    task: {request_id}")
    return request_id

def _enhancor_poll_image(request_id):
    while True:
        r = requests.post(
            f"{_ENHANCOR_IMG_BASE}/status",
            headers=_enhancor_headers(),
            json={"request_id": request_id},
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        status = d.get("status", "PENDING")
        if status == "COMPLETED":
            return d["result"]
        if status == "FAILED":
            raise RuntimeError(f"[ENHANCOR IMG] Image task failed: {d.get('error', 'unknown')}")
        print(f"    status: {status}...")
        time.sleep(POLL_INTERVAL)


# ── Provider router (images) ───────────────────────────────────────────────────

def generate_image(prompt, reference_url=None):
    """Submit an image generation job and wait for the result URL."""
    if IMAGE_PROVIDER == "KIE":
        task_id = _kie_submit_image(prompt, reference_url)
        return _kie_poll_image(task_id)
    elif IMAGE_PROVIDER == "ENHANCOR":
        task_id = _enhancor_submit_image(prompt, reference_url)
        return _enhancor_poll_image(task_id)
    else:
        raise ValueError(f"Unknown IMAGE_PROVIDER: '{IMAGE_PROVIDER}'. Options: KIE | ENHANCOR")


# ══════════════════════════════════════════════════════════════════════════════
# VIDEO PROVIDERS
# ══════════════════════════════════════════════════════════════════════════════

# ── KINOVI (Seedance 2.0) ──────────────────────────────────────────────────────

_KINOVI_BASE = "https://kinovi.ai/api/v1"

def _kinovi_headers():
    return {"Authorization": f"Bearer {KINOVI_KEY}", "Content-Type": "application/json"}

def _kinovi_submit_video(image_url, prompt, duration_seconds, mode="keyframe"):
    # Reference mode requires @image1 in the prompt
    if mode == "reference" and "@image1" not in prompt.lower():
        prompt = f"@image1 {prompt}"
    payload = {
        "model": "seedance-20",
        "inputs": {
            "urls": [image_url],
            "prompt": prompt,
            "duration": str(duration_seconds),
            "aspectRatio": "9:16",
            "mode": mode,
        },
    }
    r = requests.post(f"{_KINOVI_BASE}/jobs/createTask", headers=_kinovi_headers(), json=payload, timeout=30)
    r.raise_for_status()
    task_id = r.json()["taskId"]
    print(f"    task: {task_id}")
    return task_id

def _kinovi_poll_videos(task_id_map):
    """Poll multiple Kinovi tasks concurrently. Returns {label: url}."""
    results = {}
    pending = dict(task_id_map)
    while pending:
        still_pending = {}
        for label, task_id in pending.items():
            r = requests.get(
                f"{_KINOVI_BASE}/jobs/recordInfo",
                headers={"Authorization": f"Bearer {KINOVI_KEY}"},
                params={"taskId": task_id},
                timeout=30,
            )
            r.raise_for_status()
            d = r.json()
            status = d["status"]
            if status == "success":
                results[label] = d["output"][0]["url"]
                print(f"    [{label}] done")
            elif status == "fail":
                raise RuntimeError(f"[KINOVI] Video task failed ({label}): {d.get('error', 'unknown')}")
            else:
                print(f"    [{label}] {status}...")
                still_pending[label] = task_id
        pending = still_pending
        if pending:
            time.sleep(POLL_INTERVAL)
    return results


# ── ENHANCOR (Seed 2 Unrestricted — video) ────────────────────────────────────
# Endpoint : POST https://apireq.enhancor.ai/api/enhancor-video-pro/v1/queue
# Auth     : x-api-key header  (same _enhancor_headers() defined above)
# Polling  : POST /status  with body {"request_id": "..."}
#
# Mode mapping:
#   keyframe  → first_n_last_frames  (image becomes the literal first frame)
#   reference → multi_reference      (image used as creative guide via @image1)

def _enhancor_submit_video(image_url, prompt, duration_seconds, mode="keyframe"):
    if mode == "keyframe":
        payload = {
            "type": "image-to-video",
            "mode": "first_n_last_frames",
            "first_frame_image": image_url,
            "prompt": prompt,
            "duration": str(duration_seconds),
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "webhook_url": "https://example.com/webhook",   # required field; we use polling
        }
    else:
        # Reference mode — pass image as @image1 reference
        if "@image1" not in prompt.lower():
            prompt = f"@image1 {prompt}"
        payload = {
            "type": "image-to-video",
            "mode": "multi_reference",
            "images": [image_url],
            "prompt": prompt,
            "duration": str(duration_seconds),
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "webhook_url": "https://example.com/webhook",   # required field; we use polling
        }

    r = requests.post(f"{_ENHANCOR_BASE}/queue", headers=_enhancor_headers(), json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"[ENHANCOR] {r.status_code} submitting video: {r.text}")
    data = r.json()
    # API returns requestId (camelCase); fall back to request_id (snake_case)
    request_id = data.get("requestId") or data.get("request_id")
    if not request_id:
        raise RuntimeError(f"[ENHANCOR] No requestId in response: {data}")
    print(f"    task: {request_id}")
    return request_id

def _enhancor_poll_videos(task_id_map):
    """Poll multiple Enhancor tasks concurrently. Returns {label: url}."""
    results = {}
    pending = dict(task_id_map)
    while pending:
        still_pending = {}
        for label, request_id in pending.items():
            r = requests.post(
                f"{_ENHANCOR_BASE}/status",
                headers=_enhancor_headers(),
                json={"request_id": request_id},
                timeout=30,
            )
            r.raise_for_status()
            d = r.json()
            status = d.get("status", "PENDING")
            if status == "COMPLETED":
                results[label] = d["result"]
                print(f"    [{label}] done")
            elif status == "FAILED":
                raise RuntimeError(
                    f"[ENHANCOR] Video task failed ({label}): {d.get('error', 'unknown')}"
                )
            else:
                print(f"    [{label}] {status}...")
                still_pending[label] = request_id
        pending = still_pending
        if pending:
            time.sleep(POLL_INTERVAL)
    return results


# ── HIGGSFIELD (Seedance 2.0 — via CLI subprocess) ────────────────────────────
# Requires: ~/bin/higgsfield (installed via install.sh) + `higgsfield auth login` run once.
# Override CLI path with HIGGSFIELD_CLI_PATH in .env.
#
# Seedance 2.0 parameters (from model catalog):
#   duration    : 4–15 seconds (continuous range)
#   resolution  : 480p | 720p | 1080p
#   mode        : std | fast
#   Media roles:
#     keyframe  → --start-image  (image locked as first frame)
#     reference → --image        (image as style/identity reference)
#
# The CLI only accepts local file paths or upload UUIDs, not URLs.
# Flow: download image → submit (get job_id) → stagger next → poll all concurrently.
# Submissions are serialised with a 20s gap to avoid IP/rate-limit errors.

def _higgsfield_parse_json(raw, label):
    """Extract a JSON object from CLI stdout (may have non-JSON lines mixed in)."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
    raise RuntimeError(f"[HIGGSFIELD] Cannot parse CLI output ({label}):\n{raw}")


def _higgsfield_extract_url(data, label):
    """Pull the video URL out of whatever JSON shape the CLI returned."""
    item = data[0] if isinstance(data, list) and data else data
    url = (
        item.get("result_url")
        or item.get("url")
        or item.get("video_url")
        or (item.get("results") or [{}])[0].get("url")
        or (item.get("output") or [{}])[0].get("url")
        or (item.get("jobs") or [{}])[0].get("result_url")
    )
    if not url:
        raise RuntimeError(
            f"[HIGGSFIELD] Cannot find video URL in response ({label}):\n"
            + json.dumps(data, indent=2)
        )
    return url


def _higgsfield_submit(label, image_url, prompt, duration, mode):
    """
    Download image to a temp file, submit a Seedance 2.0 job (no --wait),
    return the job_id string. Temp file is cleaned up before returning.
    """
    clean_prompt = prompt.replace("@image1", "").strip()
    duration_clamped = max(4, min(15, duration))
    image_flag = "--start-image" if mode == "keyframe" else "--image"

    # Accept either a URL or a local file path
    if os.path.isfile(image_url):
        tmp_path = image_url
        needs_cleanup = False
    else:
        suffix = ".jpg" if any(x in image_url.lower() for x in ("jpg", "jpeg")) else ".png"
        r = requests.get(image_url, timeout=60)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(r.content)
            tmp_path = f.name
        needs_cleanup = True

    try:
        cmd = [
            HIGGSFIELD_CLI, "generate", "create", "seedance_2_0",
            "--prompt", clean_prompt,
            image_flag, tmp_path,
            "--duration", str(duration_clamped),
            "--resolution", "720p",
            "--aspect_ratio", "9:16",   # underscore required — hyphen is rejected
            "--json",
        ]
        print(f"    [{label}] submitting ({image_flag.lstrip('-')}, {duration_clamped}s)...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "Not authenticated" in stderr:
                raise RuntimeError("[HIGGSFIELD] Not authenticated. Run: ~/bin/higgsfield auth login")
            raise RuntimeError(f"[HIGGSFIELD] Submit error ({label}): {stderr}")

        data = _higgsfield_parse_json(result.stdout.strip(), label)

        # CLI may return: "id", ["id"], {"id":...}, [{"id":...}]
        item = data[0] if isinstance(data, list) and data else data

        # Plain string → it IS the job ID
        if isinstance(item, str):
            job_id = item
        else:
            job_id = (
                item.get("id")
                or item.get("job_id")
                or (item.get("job") or {}).get("id")
                or (item.get("jobs") or [{}])[0].get("id")
            )

        if not job_id:
            # If CLI returned the finished video immediately (edge case), extract URL
            try:
                url = _higgsfield_extract_url(item, label)
                print(f"    [{label}] instant result → {url}")
                return ("DONE", url)     # sentinel: already complete
            except RuntimeError:
                pass
            raise RuntimeError(
                f"[HIGGSFIELD] Cannot find job_id in submit response ({label}):\n"
                + json.dumps(data, indent=2)
            )
        print(f"    [{label}] queued as {job_id}")
        return ("JOB", job_id)
    finally:
        if needs_cleanup:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _higgsfield_poll_one(label, job_id):
    """Poll a submitted job until complete. Returns video URL."""
    while True:
        result = subprocess.run(
            [HIGGSFIELD_CLI, "generate", "get", job_id, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"[HIGGSFIELD] Poll error ({label}): {result.stderr.strip()}")
        data = _higgsfield_parse_json(result.stdout.strip(), label)
        item = data[0] if isinstance(data, list) and data else data
        status = (item.get("status") or "").upper()
        if status in ("COMPLETED", "DONE", "SUCCESS"):
            url = _higgsfield_extract_url(item, label)
            print(f"    [{label}] done → {url}")
            return url
        if status in ("FAILED", "ERROR", "CANCELLED"):
            raise RuntimeError(f"[HIGGSFIELD] Job failed ({label}): {item}")
        print(f"    [{label}] {status or 'pending'}...")
        time.sleep(15)


def _higgsfield_generate_videos(jobs, jobs_file=None):
    """
    Higgsfield enforces a 2-concurrent-job limit per account.

    Strategy:
      1. Submit + fully complete the hook (4 s, fast) — 1 slot used then freed.
      2. Submit grid1, wait 5 s, submit grid2 — 2 slots used simultaneously, OK.
      3. Poll grid1 + grid2 concurrently.

    jobs_file: optional Path — job IDs are saved here immediately after each
    submit so a retry can resume polling without re-submitting.  If jobs_file
    already contains IDs for any label those labels are skipped (no duplicate
    submissions).

    Returns {label: url}.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # ── Load any previously-saved job IDs (crash-resume) ─────────────────────
    saved_ids = {}
    if jobs_file and Path(jobs_file).exists():
        for line in Path(jobs_file).read_text().splitlines():
            if "=" in line:
                lbl, jid = line.split("=", 1)
                saved_ids[lbl.strip()] = jid.strip()
        if saved_ids:
            print(f"    [resume] found saved job IDs in {jobs_file}:")
            for lbl, jid in saved_ids.items():
                print(f"      {lbl} = {jid}")

    def _save_id(label, job_id):
        """Append/update label=job_id in jobs_file atomically."""
        if not jobs_file:
            return
        p = Path(jobs_file)
        existing = {}
        if p.exists():
            for line in p.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        existing[label] = job_id
        p.write_text("".join(f"{k}={v}\n" for k, v in existing.items()))

    results = {}

    # ── Step 1: hook ─────────────────────────────────────────────────────────
    if "hook" in saved_ids:
        print(f"    [hook] resuming existing job {saved_ids['hook']} (skipping submit)...")
        results["hook"] = _higgsfield_poll_one("hook", saved_ids["hook"])
    else:
        hook_job = next(j for j in jobs if j["label"] == "hook")
        print(f"    Completing hook first (frees a job slot for the grid videos)...")
        kind, value = _higgsfield_submit(
            hook_job["label"], hook_job["image_url"],
            hook_job["prompt"], hook_job["duration"], hook_job["mode"],
        )
        if kind == "DONE":
            results["hook"] = value
        else:
            _save_id("hook", value)
            results["hook"] = _higgsfield_poll_one("hook", value)

    # ── Step 2: grid1 + grid2 ─────────────────────────────────────────────────
    grid_jobs = [j for j in jobs if j["label"] != "hook"]
    grid_ids = {}
    for i, j in enumerate(grid_jobs):
        label = j["label"]
        if label in saved_ids:
            print(f"    [{label}] resuming existing job {saved_ids[label]} (skipping submit)...")
            grid_ids[label] = saved_ids[label]
        else:
            if i > 0:
                time.sleep(5)
            kind, value = _higgsfield_submit(
                label, j["image_url"], j["prompt"], j["duration"], j["mode"],
            )
            if kind == "DONE":
                results[label] = value
            else:
                _save_id(label, value)
                grid_ids[label] = value

    # ── Step 3: poll grid1 + grid2 concurrently ───────────────────────────────
    if grid_ids:
        with ThreadPoolExecutor(max_workers=len(grid_ids)) as executor:
            futures = {
                executor.submit(_higgsfield_poll_one, label, jid): label
                for label, jid in grid_ids.items()
            }
            for future in as_completed(futures):
                label = futures[future]
                results[label] = future.result()

    # ── Clean up jobs file once all complete ──────────────────────────────────
    if jobs_file and Path(jobs_file).exists():
        try:
            Path(jobs_file).unlink()
        except OSError:
            pass

    return results


# ── Provider router (videos) ───────────────────────────────────────────────────

def generate_videos(jobs, jobs_file=None):
    """
    Submit and poll all video jobs concurrently.

    jobs: list of dicts with keys:
        label          – e.g. "hook", "grid1", "grid2"
        image_url      – reference image URL
        prompt         – video prompt text
        duration       – int seconds
        mode           – "keyframe" | "reference"
    jobs_file: optional Path — Higgsfield-only, used to save/resume job IDs.

    Returns: {label: video_url}
    """
    if VIDEO_PROVIDER == "KINOVI":
        task_id_map = {}
        for job in jobs:
            task_id_map[job["label"]] = _kinovi_submit_video(
                job["image_url"], job["prompt"], job["duration"], job["mode"]
            )
        return _kinovi_poll_videos(task_id_map)

    elif VIDEO_PROVIDER == "ENHANCOR":
        task_id_map = {}
        for job in jobs:
            task_id_map[job["label"]] = _enhancor_submit_video(
                job["image_url"], job["prompt"], job["duration"], job["mode"]
            )
        return _enhancor_poll_videos(task_id_map)

    elif VIDEO_PROVIDER == "HIGGSFIELD":
        return _higgsfield_generate_videos(jobs, jobs_file=jobs_file)

    else:
        raise ValueError(f"Unknown VIDEO_PROVIDER: '{VIDEO_PROVIDER}'. Options: KINOVI | ENHANCOR | HIGGSFIELD")


# ══════════════════════════════════════════════════════════════════════════════
# FILE UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def download_file(url, path):
    r = requests.get(url, stream=True, timeout=180)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)


def save_image(url, img_dir, label):
    """Download image URL to img_dir/<label>.jpg and return the local path."""
    ext = "jpg" if any(x in url.lower() for x in ("jpg", "jpeg")) else "png"
    dest = img_dir / f"{label}.{ext}"
    download_file(url, dest)
    return dest




def combine_videos(part_paths, output_path):
    concat_file = output_path.parent / "_concat.txt"
    concat_file.write_text("\n".join(f"file '{p.absolute()}'" for p in part_paths))
    try:
        subprocess.run(
            ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(output_path), "-y"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        # Fall back to re-encode if streams are incompatible
        subprocess.run(
            ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c:v", "libx264", "-an", str(output_path), "-y"],
            check=True, capture_output=True, text=True,
        )
    finally:
        concat_file.unlink(missing_ok=True)


def upload_video_file(file_path):
    """Upload final video to gofile.io, return public download page URL."""
    r = requests.get("https://api.gofile.io/servers", timeout=15)
    r.raise_for_status()
    server = r.json()["data"]["servers"][0]["name"]

    with open(file_path, "rb") as f:
        r = requests.post(
            f"https://{server}.gofile.io/uploadFile",
            files={"file": (file_path.name, f, "video/mp4")},
            timeout=600,
        )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"gofile upload failed: {data}")
    return data["data"]["downloadPage"]


# ══════════════════════════════════════════════════════════════════════════════
# IDEAS FILE PARSER
# ══════════════════════════════════════════════════════════════════════════════

_FIELD_RE = _re.compile(r'^([a-z][a-z0-9_]*)\s*=\s*(.*)')
PLACEHOLDER_NAME = "Example Idea Name"


def parse_ideas_file(path):
    """Parse [IDEA] / field = value / [END IDEA] format into a list of dicts."""
    ideas = []
    current = None
    current_field = None
    current_lines = []

    def flush_field():
        if current_field is None or current is None:
            return
        text = "\n".join(current_lines).strip()
        if current_field == "title_examples":
            current[current_field] = [l.strip() for l in text.splitlines() if l.strip()]
        else:
            current[current_field] = text

    def flush_idea():
        flush_field()
        if current is None:
            return
        name = current.get("name", "").strip()
        if name and name != PLACEHOLDER_NAME:
            ideas.append(dict(current))

    with open(path) as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()

            if stripped.startswith("#"):
                continue

            if stripped == "[IDEA]":
                if current is not None:
                    flush_idea()
                current = {}
                current_field = None
                current_lines = []
                continue

            if stripped == "[END IDEA]":
                flush_idea()
                current = None
                current_field = None
                current_lines = []
                continue

            if current is None:
                continue

            m = _FIELD_RE.match(stripped)
            if m:
                flush_field()
                current_field = m.group(1)
                first = m.group(2).strip()
                current_lines = [first] if first else []
                continue

            if current_field is not None:
                current_lines.append(line)

    if current is not None:
        flush_idea()

    return ideas


# ══════════════════════════════════════════════════════════════════════════════
# RUN DOCUMENT
# ══════════════════════════════════════════════════════════════════════════════

def save_run_doc(run_file, idea, images, videos, final_path, share_url):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"RUN DATE:        {ts}",
        f"IDEA:            {idea['name']}",
        f"IMAGE PROVIDER:  {IMAGE_PROVIDER}",
        f"VIDEO PROVIDER:  {VIDEO_PROVIDER}",
        "",
        "=== PROMPTS USED ===",
        "",
        "HOOK IMAGE PROMPT:",
        idea["hook_image_prompt"].strip(),
        "",
        "HOOK VIDEO PROMPT:",
        idea["hook_video_prompt"].strip(),
        "",
        "GRID 1 IMAGE PROMPT:",
        idea["grid1_image_prompt"].strip(),
        "",
        "GRID 1 VIDEO PROMPT:",
        idea["grid1_video_prompt"].strip(),
        "",
        "GRID 2 IMAGE PROMPT:",
        idea["grid2_image_prompt"].strip(),
        "",
        "GRID 2 VIDEO PROMPT:",
        idea["grid2_video_prompt"].strip(),
        "",
        "=== GENERATED ASSETS ===",
        "",
        f"Hook Image:   {images['hook']}",
        f"Grid 1 Image: {images['grid1']}",
        f"Grid 2 Image: {images['grid2']}",
        f"Hook Video:   {videos['hook']}",
        f"Grid 1 Video: {videos['grid1']}",
        f"Grid 2 Video: {videos['grid2']}",
        "",
        "=== OUTPUT ===",
        "",
        f"Local File:  {final_path}",
        f"Share URL:   {share_url}",
    ]
    run_file.write_text("\n".join(lines))


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def check_env():
    errors = []

    if IMAGE_PROVIDER == "KIE":
        if not KIE_KEY or KIE_KEY == "your_kie_api_key_here":
            errors.append("KIE_API_KEY is not set in .env")
    elif IMAGE_PROVIDER == "ENHANCOR":
        if not ENHANCOR_KEY or ENHANCOR_KEY == "your_enhancor_api_key_here":
            errors.append("ENHANCOR_API_KEY is not set in .env")
    else:
        errors.append(f"IMAGE_PROVIDER='{IMAGE_PROVIDER}' is not valid. Options: KIE | ENHANCOR")

    if VIDEO_PROVIDER == "KINOVI":
        if not KINOVI_KEY or KINOVI_KEY == "your_kinovi_api_key_here":
            errors.append("KINOVI_API_KEY is not set in .env")
    elif VIDEO_PROVIDER == "ENHANCOR":
        if not ENHANCOR_KEY or ENHANCOR_KEY == "your_enhancor_api_key_here":
            errors.append("ENHANCOR_API_KEY is not set in .env")
    elif VIDEO_PROVIDER == "HIGGSFIELD":
        import shutil as _shutil
        cli = os.path.expanduser(os.environ.get("HIGGSFIELD_CLI_PATH", "~/bin/higgsfield"))
        if not _shutil.which(cli) and not os.path.isfile(cli):
            errors.append(
                f"HIGGSFIELD_CLI_PATH not found at '{cli}'. "
                "Install: curl -fsSL https://raw.githubusercontent.com/higgsfield-ai/cli/main/install.sh | sh -s -- --prefix=$HOME"
            )
    else:
        errors.append(f"VIDEO_PROVIDER='{VIDEO_PROVIDER}' is not valid. Options: KINOVI | ENHANCOR | HIGGSFIELD")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--idea", default=None, help="Partial idea name to select (case-insensitive). Omit for random.")
    parser.add_argument(
        "--from-images", default=None, metavar="DIR",
        help="Skip image generation — reuse images from this directory (images/TIMESTAMP_slug/).",
    )
    args = parser.parse_args()

    check_env()

    ideas = parse_ideas_file(IDEAS_FILE)
    if not ideas:
        print("ERROR: No ideas found in video_ideas.txt (add your own ideas first)", file=sys.stderr)
        sys.exit(1)

    if args.idea:
        query = args.idea.lower()
        matches = [i for i in ideas if query in i["name"].lower()]
        if not matches:
            names = ", ".join(f'"{i["name"]}"' for i in ideas)
            print(f"ERROR: No idea matching '{args.idea}'. Available: {names}", file=sys.stderr)
            sys.exit(1)
        idea = matches[0]
    else:
        idea = random.choice(ideas)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = idea["name"].lower().replace(" ", "-")

    print(f"\n{'='*60}")
    print(f"  Idea:           {idea['name']}")
    print(f"  Image provider: {IMAGE_PROVIDER}")
    print(f"  Video provider: {VIDEO_PROVIDER}")
    print(f"{'='*60}\n")

    # ── Images ──────────────────────────────────────────────────────────────────
    # Each image is saved to images/<ts>_<slug>/ immediately after generation.
    # Use --from-images <dir> on a retry to skip regeneration entirely.

    if args.from_images:
        img_dir = Path(args.from_images)
        if not img_dir.is_dir():
            print(f"ERROR: --from-images directory not found: {img_dir}", file=sys.stderr)
            sys.exit(1)
        urls_file = img_dir / "urls.txt"
        if not urls_file.exists():
            print(f"ERROR: {urls_file} not found. Only dirs created by this script support --from-images.", file=sys.stderr)
            sys.exit(1)
        urls = dict(
            line.split("=", 1)
            for line in urls_file.read_text().splitlines()
            if "=" in line
        )
        # Prefer local file paths for video jobs (URLs in urls.txt may have expired).
        # Fall back to the stored URL only if no local file is found.
        def _local_or_url(label):
            for ext in ("jpg", "jpeg", "png"):
                p = img_dir / f"{label}.{ext}"
                if p.exists():
                    return str(p)
            return urls[label]

        hook_img  = _local_or_url("hook")
        grid1_img = _local_or_url("grid1")
        grid2_img = _local_or_url("grid2")
        print(f"[--from-images] Reusing images from {img_dir}")
        print(f"  hook  -> {hook_img}")
        print(f"  grid1 -> {grid1_img}")
        print(f"  grid2 -> {grid2_img}\n")
    else:
        img_dir = IMAGES_DIR / f"{ts}_{slug}"
        img_dir.mkdir(parents=True, exist_ok=True)

        print("[1/3] Generating Hook Image...")
        hook_img = generate_image(idea["hook_image_prompt"])
        save_image(hook_img, img_dir, "hook")
        print(f"    -> {hook_img}")
        print(f"    saved: {img_dir}/hook.jpg\n")

        print("[2/3] Generating Grid 1 Image  (reference: hook)...")
        grid1_img = generate_image(idea["grid1_image_prompt"], reference_url=hook_img)
        save_image(grid1_img, img_dir, "grid1")
        print(f"    -> {grid1_img}")
        print(f"    saved: {img_dir}/grid1.jpg\n")

        print("[3/3] Generating Grid 2 Image  (reference: grid 1)...")
        grid2_img = generate_image(idea["grid2_image_prompt"], reference_url=grid1_img)
        save_image(grid2_img, img_dir, "grid2")
        print(f"    -> {grid2_img}")
        print(f"    saved: {img_dir}/grid2.jpg\n")

        # Save URLs for retry with --from-images
        (img_dir / "urls.txt").write_text(
            f"hook={hook_img}\ngrid1={grid1_img}\ngrid2={grid2_img}\n"
        )
        print(f"  Images saved to: {img_dir}\n")

    # ── Videos (submit all 3 at once, poll concurrently) ──

    print("Submitting video jobs...")
    print("  Hook video   (4s, keyframe):")
    print("  Grid 1 video (15s, reference):")
    print("  Grid 2 video (15s, reference):")

    video_urls = generate_videos([
        {"label": "hook",  "image_url": hook_img,  "prompt": idea["hook_video_prompt"],  "duration": 4,  "mode": "keyframe"},
        {"label": "grid1", "image_url": grid1_img, "prompt": idea["grid1_video_prompt"], "duration": 15, "mode": "reference"},
        {"label": "grid2", "image_url": grid2_img, "prompt": idea["grid2_video_prompt"], "duration": 15, "mode": "reference"},
    ], jobs_file=img_dir / "video_jobs.txt")

    print(f"\n    hook   -> {video_urls['hook']}")
    print(f"    grid1  -> {video_urls['grid1']}")
    print(f"    grid2  -> {video_urls['grid2']}")

    # ── Download, combine, upload ──

    print("\nDownloading videos...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        hook_file  = tmp / "hook.mp4"
        grid1_file = tmp / "grid1.mp4"
        grid2_file = tmp / "grid2.mp4"

        download_file(video_urls["hook"],  hook_file)
        download_file(video_urls["grid1"], grid1_file)
        download_file(video_urls["grid2"], grid2_file)

        output_path = VIDEOS_DIR / f"{ts}_{slug}.mp4"
        print("Combining with ffmpeg...")
        combine_videos([hook_file, grid1_file, grid2_file], output_path)

    print(f"    -> {output_path}\n")

    print("Uploading...")
    share_url = upload_video_file(output_path)
    print(f"    -> {share_url}\n")

    # ── Save run document ──

    run_file = RUNS_DIR / f"{ts}_{slug}.txt"
    save_run_doc(
        run_file, idea,
        images={"hook": hook_img, "grid1": grid1_img, "grid2": grid2_img},
        videos=video_urls,
        final_path=output_path,
        share_url=share_url,
    )

    # ── Output JSON for Claude to parse ──

    result = {
        "idea_name":      idea["name"],
        "title_examples": idea.get("title_examples", []),
        "share_url":      share_url,
        "output_file":    str(output_path),
        "run_file":       str(run_file),
        "image_provider": IMAGE_PROVIDER,
        "video_provider": VIDEO_PROVIDER,
    }
    print("---RESULT_JSON---")
    print(json.dumps(result, indent=2))
    print("---END_RESULT---")


if __name__ == "__main__":
    main()
