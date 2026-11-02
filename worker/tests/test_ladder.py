import pytest

from encoder.ladder import build_hls_command, select_variants


def dims(variants):
    return [(v.quality, v.width, v.height) for v in variants]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ((1920, 1080), [("480p", 854, 480), ("720p", 1280, 720), ("1080p", 1920, 1080)]),
        ((3840, 2160), [("480p", 854, 480), ("720p", 1280, 720), ("1080p", 1920, 1080)]),
        ((1280, 720), [("480p", 854, 480), ("720p", 1280, 720)]),  # no upscaling
        ((640, 360), [("480p", 640, 360)]),  # smaller than the ladder: one rendition at source size
        ((1080, 1920), [("480p", 480, 854), ("720p", 720, 1280), ("1080p", 1080, 1920)]),  # portrait
        ((1920, 800), [("480p", 854, 356), ("720p", 1280, 534), ("1080p", 1920, 800)]),  # cinemascope
        ((1440, 1080), [("480p", 640, 480), ("720p", 960, 720), ("1080p", 1440, 1080)]),  # 4:3
    ],
)
def test_select_variants(source, expected):
    assert dims(select_variants(*source)) == expected


def test_dimensions_are_always_even():
    for w, h in [(1279, 719), (333, 777), (1921, 1081)]:
        for v in select_variants(w, h):
            assert v.width % 2 == 0 and v.height % 2 == 0


def test_command_maps_audio_per_variant():
    cmd = build_hls_command("in.mp4", "/out", select_variants(1280, 720), has_audio=True)
    assert cmd.count("0:a:0") == 2
    assert cmd[cmd.index("-var_stream_map") + 1] == "v:0,a:0,name:480p v:1,a:1,name:720p"
    assert "[0:v]split=2[v0][v1];[v0]scale=854:480,setsar=1[v0o];[v1]scale=1280:720,setsar=1[v1o]" in cmd


def test_command_without_audio_drops_audio_maps():
    cmd = build_hls_command("in.mp4", "/out", select_variants(1920, 1080), has_audio=False)
    assert "0:a:0" not in cmd and "-c:a" not in cmd
    assert cmd[cmd.index("-var_stream_map") + 1] == "v:0,name:480p v:1,name:720p v:2,name:1080p"
    assert cmd[cmd.index("-b:v:2") + 1] == "5000k"
