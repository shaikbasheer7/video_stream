"""Real FFmpeg against a real HLS output, including one with no audio track."""

import shutil
import subprocess

import pytest

from ml import media

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")


def make_hls(folder, audio=True):
    inputs = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=4"]
    if audio:
        inputs += ["-f", "lavfi", "-i", "sine=frequency=440:duration=4"]
    folder.mkdir()
    playlist = folder / "index.m3u8"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-c:v", "libx264", "-preset", "ultrafast"]
    subprocess.run([*cmd, "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod", str(playlist)], check=True)
    return playlist


def test_finds_audio_and_extracts_it_as_16khz_mono(tmp_path):
    playlist = make_hls(tmp_path / "hls")
    assert media.has_audio(playlist) is True
    out = media.extract_audio(playlist, tmp_path / "audio.wav", max_seconds=2)
    probe = ["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels:format=duration", "-of", "csv=p=0"]
    fields = subprocess.run([*probe, str(out)], capture_output=True, text=True, check=True).stdout.split()
    assert fields[0] == "16000,1"
    assert float(fields[1]) == pytest.approx(2, abs=0.1)  # the cap applies


def test_notices_a_missing_audio_track(tmp_path):
    assert media.has_audio(make_hls(tmp_path / "hls", audio=False)) is False


def test_frames_are_spread_over_the_video(tmp_path):
    frames = media.extract_frames(make_hls(tmp_path / "hls"), tmp_path / "frames", duration_sec=4, count=4)
    assert len(frames) == 4
    assert len({path.read_bytes() for path in frames}) == 4  # testsrc changes over time: really different moments


def test_a_clip_shorter_than_one_interval_still_yields_a_frame(tmp_path):
    frames = media.extract_frames(make_hls(tmp_path / "hls"), tmp_path / "frames", duration_sec=0, count=8)
    assert frames


def test_a_playlist_cannot_reach_out_of_the_local_filesystem(tmp_path):
    playlist = tmp_path / "index.m3u8"
    playlist.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nhttp://169.254.169.254/latest/meta-data\n")
    with pytest.raises(Exception, match="exited with"):
        media.extract_frames(playlist, tmp_path / "frames", duration_sec=2, count=1)
