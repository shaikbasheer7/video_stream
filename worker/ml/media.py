"""Pull audio and frames out of an already encoded rendition with FFmpeg. No Kafka, S3 or models here."""

import json
import subprocess
from pathlib import Path

from encoder.errors import EncodeError
from encoder.pipeline import run

SAMPLE_RATE = 16_000  # what Whisper expects


def input_args(playlist):
    # Local files only: FFmpeg must never follow a playlist entry to the network.
    return ["-protocol_whitelist", "file", "-i", str(playlist)]


def has_audio(playlist):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json"]
    proc = subprocess.run([*cmd, *input_args(playlist)], capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise EncodeError(f"ffprobe exited with {proc.returncode}: {proc.stderr.strip()[-800:]}")
    return bool(json.loads(proc.stdout).get("streams"))


def extract_audio(playlist, out, max_seconds):
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", *input_args(playlist)]
    run([*cmd, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-t", str(max_seconds), str(out)], timeout=900)
    return Path(out)


def extract_frames(playlist, out_dir, duration_sec, count):
    """Up to `count` evenly spaced JPEGs, skipping the very start (often a fade-in or a black frame).

    Same size and quality as the encoder's thumbnail, because one of them may replace it.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    interval = max(duration_sec / count, 0.1)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{interval / 2:.3f}", *input_args(playlist)]
    filters = f"fps=1/{interval:.3f},scale='min(640,iw)':-2"
    run([*cmd, "-vf", filters, "-q:v", "3", "-frames:v", str(count), str(out_dir / "%03d.jpg")], timeout=900)
    return sorted(out_dir.glob("*.jpg"))
