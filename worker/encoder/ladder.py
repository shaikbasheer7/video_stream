"""Rendition ladder selection and the FFmpeg HLS command (pure functions, unit-tested)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rung:
    quality: str
    width: int
    height: int
    bitrate_kbps: int
    maxrate_kbps: int


LADDER = (
    Rung("480p", 854, 480, 1400, 1500),
    Rung("720p", 1280, 720, 2800, 3000),
    Rung("1080p", 1920, 1080, 5000, 5350),
)
AUDIO_KBPS = 128
SEGMENT_SEC = 6
KEYFRAME_SEC = 2  # divides SEGMENT_SEC, so every rendition cuts segments at the same instants


@dataclass(frozen=True)
class Variant:
    quality: str
    width: int
    height: int
    bitrate_kbps: int
    maxrate_kbps: int


def _even(value):
    """Nearest even integer (x264 needs even dimensions); 16:9 at 480 lines gives the usual 854, not 852."""
    return max(2, round(value / 2) * 2)


def fit(src_w, src_h, box_w, box_h):
    """Scale to fit inside the box, keeping aspect ratio, never upscaling."""
    scale = min(box_w / src_w, box_h / src_h, 1.0)
    return _even(src_w * scale), _even(src_h * scale)


def select_variants(width, height):
    """Rungs the source can fill without upscaling. Portrait sources use portrait boxes.

    A rung is kept if the source reaches its long or its short side (so 1920x800 still gets 1080p).
    Sources smaller than 480p get a single 480p-labelled rendition at their own size.
    """
    portrait = height > width
    long_side, short_side = max(width, height), min(width, height)
    chosen = [r for r in LADDER if long_side >= r.width or short_side >= r.height] or [LADDER[0]]
    variants = []
    for rung in chosen:
        box = (rung.height, rung.width) if portrait else (rung.width, rung.height)
        w, h = fit(width, height, *box)
        variants.append(Variant(rung.quality, w, h, rung.bitrate_kbps, rung.maxrate_kbps))
    return variants


def build_hls_command(source, out_dir, variants, has_audio):
    n = len(variants)
    filters = [f"[0:v]split={n}" + "".join(f"[v{i}]" for i in range(n))]
    filters += [f"[v{i}]scale={v.width}:{v.height},setsar=1[v{i}o]" for i, v in enumerate(variants)]

    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source), "-filter_complex", ";".join(filters)]
    for i, v in enumerate(variants):
        cmd += [
            "-map", f"[v{i}o]",
            f"-c:v:{i}", "libx264",
            f"-b:v:{i}", f"{v.bitrate_kbps}k",
            f"-maxrate:v:{i}", f"{v.maxrate_kbps}k",
            f"-bufsize:v:{i}", f"{v.bitrate_kbps * 3 // 2}k",
        ]  # fmt: skip
    if has_audio:
        for _ in variants:
            cmd += ["-map", "0:a:0"]
        cmd += ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "2"]

    stream_map = [
        f"v:{i},a:{i},name:{v.quality}" if has_audio else f"v:{i},name:{v.quality}" for i, v in enumerate(variants)
    ]
    cmd += [
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        # Time-based keyframes (instead of a fixed -g) stay aligned across renditions at any frame rate.
        "-force_key_frames", f"expr:gte(t,n_forced*{KEYFRAME_SEC})",
        "-sc_threshold", "0",
        "-f", "hls",
        "-hls_time", str(SEGMENT_SEC),
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", f"{out_dir}/%v/seg_%03d.ts",
        "-master_pl_name", "master.m3u8",
        "-var_stream_map", " ".join(stream_map),
        f"{out_dir}/%v/index.m3u8",
    ]  # fmt: skip
    return cmd


def build_thumbnail_command(source, output, duration_sec):
    at = min(3.0, duration_sec / 2)
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-ss", f"{at:.2f}", "-i", str(source),
        "-frames:v", "1", "-vf", "scale='min(640,iw)':-2", "-q:v", "3",
        str(output),
    ]  # fmt: skip
