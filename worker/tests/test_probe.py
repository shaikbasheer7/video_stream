import pytest

from encoder.errors import InvalidSource
from encoder.probe import parse_probe


def video_stream(**extra):
    return {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, **extra}


def test_parses_dimensions_duration_and_audio():
    info = parse_probe(
        {"streams": [video_stream(), {"codec_type": "audio"}], "format": {"duration": "12.5"}},
    )
    assert (info.width, info.height, info.duration_sec, info.has_audio) == (1920, 1080, 12.5, True)


@pytest.mark.parametrize(
    "stream",
    [video_stream(side_data_list=[{"rotation": -90}]), video_stream(tags={"rotate": "90"})],
)
def test_rotation_swaps_to_display_orientation(stream):
    info = parse_probe({"streams": [stream], "format": {"duration": "3"}})
    assert (info.width, info.height, info.has_audio) == (1080, 1920, False)


def test_cover_art_is_not_a_video():
    with pytest.raises(InvalidSource):
        parse_probe(
            {"streams": [video_stream(disposition={"attached_pic": 1}), {"codec_type": "audio"}], "format": {}},
        )


def test_missing_duration_is_invalid():
    with pytest.raises(InvalidSource):
        parse_probe({"streams": [video_stream()], "format": {}})
