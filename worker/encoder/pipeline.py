"""Local encoding: probe → ladder → FFmpeg HLS → thumbnail. No Kafka or S3 here."""

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import EncodeError, InvalidSource
from .ladder import build_hls_command, build_thumbnail_command, select_variants
from .probe import SourceInfo, probe

logger = logging.getLogger(__name__)


@dataclass
class EncodeResult:
    source: SourceInfo
    variants: list
    hls_dir: Path  # contains master.m3u8 and one folder per quality
    thumbnail: Path


def run(cmd, timeout):
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise EncodeError(f"{cmd[0]} timed out after {timeout:.0f}s") from exc
    if proc.returncode != 0:
        tail = proc.stderr.strip()[-800:]
        raise EncodeError(f"{cmd[0]} exited with {proc.returncode}: {tail}")
    logger.info("%s finished in %.1fs", cmd[0], time.monotonic() - started)


def encode(source_path, work_dir, max_duration_sec):
    source_path, work_dir = Path(source_path), Path(work_dir)
    info = probe(source_path)
    if info.duration_sec > max_duration_sec:
        raise InvalidSource(f"Videos are limited to {max_duration_sec / 60:.0f} minutes.")

    variants = select_variants(info.width, info.height)
    logger.info(
        "source %dx%d %.1fs audio=%s -> %s",
        info.width, info.height, info.duration_sec, info.has_audio, [v.quality for v in variants],
    )  # fmt: skip

    hls_dir = work_dir / "hls"
    for v in variants:
        (hls_dir / v.quality).mkdir(parents=True, exist_ok=True)
    # Generous timeout: a slow CPU can take several times real time for three renditions.
    run(build_hls_command(source_path, hls_dir, variants, info.has_audio), timeout=600 + 4 * info.duration_sec)
    if not (hls_dir / "master.m3u8").exists():
        raise EncodeError("FFmpeg did not write master.m3u8")

    thumbnail = work_dir / "thumbnail.jpg"
    run(build_thumbnail_command(source_path, thumbnail, info.duration_sec), timeout=120)
    return EncodeResult(source=info, variants=variants, hls_dir=hls_dir, thumbnail=thumbnail)
