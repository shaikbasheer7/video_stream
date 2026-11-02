import json
import subprocess
from dataclasses import dataclass

from .errors import InvalidSource


@dataclass(frozen=True)
class SourceInfo:
    width: int  # display orientation (rotation metadata applied)
    height: int
    duration_sec: float
    has_audio: bool
    video_codec: str


def _rotation(stream):
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            return int(side_data["rotation"])
    return int(stream.get("tags", {}).get("rotate", 0))


def parse_probe(data):
    streams = data.get("streams", [])
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    if video is None or not video.get("width") or not video.get("height"):
        raise InvalidSource("The file has no video stream.")

    width, height = int(video["width"]), int(video["height"])
    # Phones store portrait video as landscape plus a rotation flag; FFmpeg applies it when decoding.
    if _rotation(video) % 180 != 0:
        width, height = height, width

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise InvalidSource("Could not read the video's duration.")

    return SourceInfo(
        width=width,
        height=height,
        duration_sec=duration,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        video_codec=video.get("codec_name", ""),
    )


def probe(path, timeout=120):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise InvalidSource("The file is not a readable video.")
    return parse_probe(json.loads(proc.stdout))
