from pathlib import Path

from ml import config
from ml.db import VideoGone
from ml.main import VIDEO_READY_DLQ, AnalysisJob
from ml.tagging import FrameAnalysis, Tag
from ml.transcribe import Cue, Transcript

SPEECH = Transcript("en", (Cue(0.0, 1.5, "Hello there"),))
EVENT = {
    "event_id": "event-1",
    "video_id": "v1",
    "duration_sec": 10,
    "renditions": [
        {"quality": "720p", "height": 720, "playlist_key": "hls/v1/720p/index.m3u8"},
        {"quality": "480p", "height": 480, "playlist_key": "hls/v1/480p/index.m3u8"},
    ],
}


class FakeDb:
    def __init__(self, analysed=False, exists=True, gone=False):
        self.analysed, self._exists, self.gone = analysed, exists, gone
        self.saved = []

    def already_analysed(self, video_id, event_id):
        return self.analysed

    def exists(self, video_id):
        return self._exists

    def save(self, *args):
        if self.gone:
            raise VideoGone(args[0])
        self.saved.append(args)


class FakeStorage:
    def __init__(self):
        self.downloaded, self.uploaded, self.deleted = [], {}, []

    def download_prefix(self, prefix, path):
        self.downloaded.append(prefix)

    def upload_file(self, path, key):
        path = Path(path)
        self.uploaded[key] = path.read_text(encoding="utf-8") if path.suffix == ".vtt" else str(path)

    def delete_prefix(self, prefix):
        self.deleted.append(prefix)


class FakeMedia:
    def __init__(self, audio=True):
        self.audio = audio
        self.audio_extracted = False

    def has_audio(self, playlist):
        return self.audio

    def extract_audio(self, playlist, out, max_seconds):
        self.audio_extracted = True
        return out

    def extract_frames(self, playlist, out_dir, duration_sec, count):
        return ["frame.jpg"]


ANIMALS = (Tag("animals", "topic", 0.8),)


def make_job(db=None, transcribe=lambda audio: SPEECH, tags=ANIMALS, audio=True, thumbnail=None):
    published = []
    job = AnalysisJob(
        db or FakeDb(),
        storage=FakeStorage(),
        media=FakeMedia(audio),
        transcribe=transcribe,
        analyse_frames=lambda frames: FrameAnalysis(list(tags), thumbnail),
        publish=lambda topic, key, payload: published.append((topic, key, payload)),
        sleep=lambda _: None,
    )
    job.published = published
    return job


def test_saves_results_and_uploads_subtitles_next_to_the_hls_output():
    job = make_job()
    job.handle(EVENT)
    assert job.storage.downloaded == ["hls/v1/480p/"]  # the smallest rendition
    assert "Hello there" in job.storage.uploaded["hls/v1/subtitles/en.vtt"]
    video_id, event_id, transcript, key, tags = job.db.saved[0]
    assert (video_id, event_id, transcript, key) == ("v1", "event-1", SPEECH, "hls/v1/subtitles/en.vtt")
    assert tags == [Tag("animals", "topic", 0.8)]
    assert job.published == []


def test_a_redelivered_event_is_skipped():
    job = make_job(FakeDb(analysed=True))
    job.handle(EVENT)
    assert job.storage.downloaded == [] and job.db.saved == []


def test_a_deleted_video_is_skipped():
    job = make_job(FakeDb(exists=False))
    job.handle(EVENT)
    assert job.storage.downloaded == []


def test_a_video_without_an_audio_track_still_gets_tags_and_is_marked_done():
    job = make_job(audio=False)
    job.handle(EVENT)
    assert job.media.audio_extracted is False
    assert job.storage.uploaded == {}
    _, _, transcript, key, tags = job.db.saved[0]
    assert (transcript.text, transcript.language, key) == ("", "", "")
    assert len(tags) == 1


def test_a_video_with_no_speech_gets_no_subtitle_file():
    job = make_job(transcribe=lambda audio: Transcript("", ()))
    job.handle(EVENT)
    assert job.storage.uploaded == {}
    assert job.db.saved[0][3] == ""


def test_retries_then_recovers():
    calls = []

    def flaky(audio):
        calls.append(audio)
        if len(calls) == 1:
            raise RuntimeError("out of memory")
        return SPEECH

    job = make_job(transcribe=flaky)
    job.handle(EVENT)
    assert len(calls) == 2
    assert len(job.db.saved) == 1
    assert job.published == []


def test_lasting_failure_goes_to_the_dlq_and_does_not_block_the_queue():
    def broken(audio):
        raise RuntimeError("model file corrupt")

    job = make_job(transcribe=broken)
    job.handle(EVENT)  # does not raise: the offset gets committed
    assert job.db.saved == []
    assert len(job.published) == 1
    topic, key, payload = job.published[0]
    assert (topic, key) == (VIDEO_READY_DLQ, "v1")
    assert payload["original"] == EVENT
    assert payload["error"] == "RuntimeError: model file corrupt"
    assert payload["attempts"] == config.MAX_ATTEMPTS


def test_deleted_during_analysis_removes_its_outputs():
    job = make_job(FakeDb(gone=True), thumbnail=Path("frame.jpg"))
    job.handle(EVENT)
    assert job.storage.deleted == ["hls/v1/subtitles/", "thumbnails/v1/"]
    assert job.published == []


def test_the_chosen_frame_replaces_the_thumbnail_at_the_key_the_video_uses():
    job = make_job(thumbnail=Path("frame.jpg"))
    job.handle(EVENT)
    assert job.storage.uploaded["thumbnails/v1/default.jpg"] == "frame.jpg"


def test_without_a_chosen_frame_the_encoders_thumbnail_stays():
    job = make_job()
    job.handle(EVENT)
    assert "thumbnails/v1/default.jpg" not in job.storage.uploaded


def test_event_without_renditions_ends_in_the_dlq():
    job = make_job()
    job.handle({"event_id": "e", "video_id": "v1"})
    assert job.published[0][0] == VIDEO_READY_DLQ


def test_gives_up_after_the_configured_attempts():
    calls = []

    def broken(audio):
        calls.append(audio)
        raise RuntimeError("boom")

    make_job(transcribe=broken).handle(EVENT)
    assert len(calls) == config.MAX_ATTEMPTS
