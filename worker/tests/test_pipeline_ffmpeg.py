"""Real FFmpeg runs on tiny generated clips. Run inside the worker image (it has ffmpeg)."""

import shutil
import subprocess

import pytest

from encoder.errors import InvalidSource
from encoder.pipeline import encode

pytestmark = [
    pytest.mark.ffmpeg,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed"),
]


def make_clip(path, size, seconds=7, audio=True):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}"]  # fmt: skip
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def test_720p_with_audio_gets_two_aligned_renditions(tmp_path):
    source = make_clip(tmp_path / "in.mp4", "1280x720")
    result = encode(source, tmp_path / "out", max_duration_sec=3600)

    assert [v.quality for v in result.variants] == ["480p", "720p"]
    master = (result.hls_dir / "master.m3u8").read_text()
    assert "480p/index.m3u8" in master and "720p/index.m3u8" in master and "1080p" not in master
    assert "RESOLUTION=854x480" in master and "RESOLUTION=1280x720" in master
    assert 'CODECS="avc1' in master and "mp4a" in master
    for quality in ("480p", "720p"):
        playlist = (result.hls_dir / quality / "index.m3u8").read_text()
        assert "#EXT-X-PLAYLIST-TYPE:VOD" in playlist and "#EXT-X-ENDLIST" in playlist
        # 7 s at 6 s segments: 2 segments in every rendition, cut at the same points.
        assert sorted(p.name for p in (result.hls_dir / quality).glob("seg_*.ts")) == ["seg_000.ts", "seg_001.ts"]
        assert "#EXTINF:6.000000," in playlist
    assert result.thumbnail.stat().st_size > 1000
    assert result.source.has_audio and result.source.duration_sec == pytest.approx(7, abs=0.2)


def test_portrait_without_audio(tmp_path):
    source = make_clip(tmp_path / "in.mp4", "480x854", seconds=3, audio=False)
    result = encode(source, tmp_path / "out", max_duration_sec=3600)
    assert [(v.quality, v.width, v.height) for v in result.variants] == [("480p", 480, 854)]
    master = (result.hls_dir / "master.m3u8").read_text()
    assert "RESOLUTION=480x854" in master and "mp4a" not in master


def test_rejects_non_video_and_too_long(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"\x00" * 4096)
    with pytest.raises(InvalidSource):
        encode(junk, tmp_path / "out1", max_duration_sec=3600)

    source = make_clip(tmp_path / "in.mp4", "320x240", seconds=3, audio=False)
    with pytest.raises(InvalidSource, match="limited"):
        encode(source, tmp_path / "out2", max_duration_sec=2)
