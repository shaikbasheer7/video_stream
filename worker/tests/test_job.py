from pathlib import Path

import pytest

from encoder import config
from encoder.errors import EncodeError, InvalidSource
from encoder.ladder import select_variants
from encoder.main import GENERIC_FAILURE, EncodeJob
from encoder.pipeline import EncodeResult
from encoder.probe import SourceInfo

VIDEO_ID = "8a6d0000-0000-0000-0000-000000000001"
EVENT = {"event": "video.uploaded", "video_id": VIDEO_ID, "source_key": f"raw/{VIDEO_ID}/source.mp4"}


class FakeDb:
    def __init__(self, claimable=True, exists=True):
        self.claimable, self._exists, self.claims = claimable, exists, 0

    def claim(self, video_id, event_id):
        self.claims += 1
        return EVENT["source_key"] if self.claimable else None

    def exists(self, video_id):
        return self._exists


class FakeStorage:
    def __init__(self):
        self.downloaded, self.uploaded, self.deleted = [], [], []

    def download(self, key, path):
        self.downloaded.append((key, Path(path).name))

    def upload_dir(self, local_dir, prefix):
        self.uploaded.append(prefix)
        return 7

    def upload_file(self, path, key):
        self.uploaded.append(key)

    def delete_prefix(self, prefix):
        self.deleted.append(prefix)


def ok_encode(source, work_dir, max_duration):
    info = SourceInfo(width=1280, height=720, duration_sec=31.25, has_audio=True, video_codec="h264")
    return EncodeResult(info, select_variants(1280, 720), Path(work_dir) / "hls", Path(work_dir) / "t.jpg")


def make_job(db=None, encode=ok_encode):
    published, sleeps, storage = [], [], FakeStorage()
    job = EncodeJob(
        db or FakeDb(),
        storage=storage,
        encode=encode,
        publish=lambda topic, key, payload: published.append((topic, key, payload)),
        sleep=sleeps.append,
    )
    return job, storage, published, sleeps


def test_success_uploads_outputs_and_publishes_ready():
    job, storage, published, _ = make_job()
    job.handle(EVENT)

    assert storage.downloaded == [(EVENT["source_key"], "source.mp4")]
    assert storage.uploaded == [f"hls/{VIDEO_ID}/", f"thumbnails/{VIDEO_ID}/default.jpg"]
    [(topic, key, payload)] = published
    assert (topic, key) == ("video.ready", VIDEO_ID)
    assert payload["master_key"] == f"hls/{VIDEO_ID}/master.m3u8"
    assert payload["qualities"] == ["480p", "720p"]
    assert payload["renditions"][1] == {
        "quality": "720p",
        "playlist_key": f"hls/{VIDEO_ID}/720p/index.m3u8",
        "width": 1280,
        "height": 720,
        "bitrate_kbps": 2800,
    }
    assert payload["duration_sec"] == 31.25


def test_skips_when_video_cannot_be_claimed():
    job, storage, published, _ = make_job(db=FakeDb(claimable=False))
    job.handle(EVENT)
    assert storage.downloaded == [] and published == []


def test_retries_with_backoff_then_fails_to_dlq(monkeypatch):
    monkeypatch.setattr(config, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "RETRY_BACKOFF_SEC", 5)
    calls = []

    def broken(*args):
        calls.append(1)
        raise EncodeError("ffmpeg exited with 1: boom")

    job, _, published, sleeps = make_job(encode=broken)
    job.handle(EVENT)

    assert len(calls) == 3
    assert sleeps == [5, 15]
    assert [t for t, _, _ in published] == ["video.failed", "video.uploaded.dlq"]
    assert published[0][2] == {"video_id": VIDEO_ID, "error": GENERIC_FAILURE, "attempts": 3}
    assert published[1][2]["original"] == EVENT
    assert "boom" in published[1][2]["error"]


def test_invalid_source_fails_immediately_with_reason():
    def invalid(*args):
        raise InvalidSource("The file has no video stream.")

    job, _, published, sleeps = make_job(encode=invalid)
    job.handle(EVENT)
    assert sleeps == []
    assert published[0][2]["error"] == "The file has no video stream."
    assert published[0][2]["attempts"] == 1


def test_recovers_on_second_attempt():
    attempts = []

    def flaky(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise EncodeError("transient")
        return ok_encode(*args)

    job, _, published, sleeps = make_job(encode=flaky)
    job.handle(EVENT)
    assert [t for t, _, _ in published] == ["video.ready"]
    assert len(sleeps) == 1


def test_deleted_during_encode_cleans_up_and_publishes_nothing():
    job, storage, published, _ = make_job(db=FakeDb(exists=False))
    job.handle(EVENT)
    assert published == []
    assert storage.deleted == [f"hls/{VIDEO_ID}/", f"thumbnails/{VIDEO_ID}/"]


@pytest.mark.parametrize("error", [RuntimeError("kafka down")])
def test_failure_to_publish_failure_propagates(error):
    """If even video.failed can't be published, the loop must not commit (message is retried)."""

    def raising_publish(*args):
        raise error

    job = EncodeJob(FakeDb(), storage=FakeStorage(), encode=lambda *a: (_ for _ in ()).throw(InvalidSource("x")),
                    publish=raising_publish, sleep=lambda s: None)  # fmt: skip
    with pytest.raises(RuntimeError):
        job.handle(EVENT)
