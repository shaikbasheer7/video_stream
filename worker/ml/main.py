"""ML worker: consumes video.ready, writes subtitles to S3 and transcript and tags to Postgres.

Best effort by design: a video is already playable when this starts, and stays so if analysis fails. A video that
keeps failing goes to the DLQ and has no subtitles or tags; playback, browsing and title search are unaffected.
"""

import logging
import tempfile
import time
from pathlib import Path, PurePosixPath

from encoder import logs, messaging, storage
from encoder.main import consume

from . import config, media, tagging, transcribe
from .db import AnalysisDatabase, VideoGone

logger = logging.getLogger("ml")

VIDEO_READY_DLQ = "video.ready.ml.dlq"  # same name as backend/common/kafka.py, which creates the topic
NO_SPEECH = transcribe.Transcript("", ())


class AnalysisJob:
    """Handles one video.ready event. Collaborators are injectable for tests."""

    def __init__(
        self,
        db,
        storage=storage,
        media=media,
        transcribe=transcribe.transcribe,
        analyse_frames=tagging.analyse_frames,
        publish=messaging.publish,
        sleep=time.sleep,
    ):
        self.db = db
        self.storage = storage
        self.media = media
        self.transcribe = transcribe
        self.analyse_frames = analyse_frames
        self.publish = publish
        self.sleep = sleep

    def handle(self, event):
        video_id, event_id = event["video_id"], event.get("event_id", "")
        if self.db.already_analysed(video_id, event_id):
            logger.info("video %s: duplicate, already analysed; skipping", video_id)
            return
        if not self.db.exists(video_id):
            logger.info("video %s: deleted; skipping", video_id)
            return

        error = None
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            try:
                self.process(event)
                return
            except Exception as exc:
                error = exc
                logger.exception("video %s: analysis attempt %d/%d failed", video_id, attempt, config.MAX_ATTEMPTS)
                if attempt < config.MAX_ATTEMPTS:
                    self.sleep(config.RETRY_BACKOFF_SEC)

        self.publish(
            VIDEO_READY_DLQ,
            video_id,
            {
                "video_id": video_id,
                "original": event,
                "error": f"{type(error).__name__}: {error}",
                "attempts": config.MAX_ATTEMPTS,
            },
        )
        logger.error("video %s: analysis failed, sent to DLQ", video_id)

    def process(self, event):
        video_id, event_id = event["video_id"], event.get("event_id", "")
        # The smallest rendition: audio is the same in all of them and CLIP scales frames down to 224 pixels anyway.
        rendition = min(event["renditions"], key=lambda r: r["height"])
        playlist_key = PurePosixPath(rendition["playlist_key"])
        duration = event.get("duration_sec") or 0

        with tempfile.TemporaryDirectory(prefix=f"ml-{video_id}-") as tmp:
            work = Path(tmp)
            self.storage.download_prefix(f"{playlist_key.parent}/", work / "hls")
            playlist = work / "hls" / playlist_key.name

            transcript = NO_SPEECH
            if self.media.has_audio(playlist):
                audio = self.media.extract_audio(playlist, work / "audio.wav", config.MAX_TRANSCRIBE_SEC)
                transcript = self.transcribe(audio)
                if duration > config.MAX_TRANSCRIBE_SEC:
                    logger.warning("video %s: only the first %ds transcribed", video_id, config.MAX_TRANSCRIBE_SEC)
            frames = self.media.extract_frames(playlist, work / "frames", duration, config.FRAMES_PER_VIDEO)
            analysis = self.analyse_frames(frames)
            tags = analysis.tags

            subtitles_key = ""
            if transcript.cues:
                subtitles_key = f"hls/{video_id}/subtitles/{transcript.language}.vtt"
                vtt = work / f"{transcript.language}.vtt"
                vtt.write_text(transcribe.to_webvtt(transcript.cues), encoding="utf-8")
                self.storage.upload_file(vtt, subtitles_key)
            if analysis.thumbnail:
                # The key the video already points at. Before the save, so a delete can't leave one behind.
                self.storage.upload_file(analysis.thumbnail, f"thumbnails/{video_id}/default.jpg")

        try:
            self.db.save(video_id, event_id, transcript, subtitles_key, tags)
        except VideoGone:
            logger.info("video %s: deleted during analysis, removing outputs", video_id)
            self.storage.delete_prefix(f"hls/{video_id}/subtitles/")
            self.storage.delete_prefix(f"thumbnails/{video_id}/")
            return
        logger.info(
            "video %s: analysed (language=%s, %d cues, tags=%s, new thumbnail=%s)",
            video_id, transcript.language or "none", len(transcript.cues), [f"{t.kind}:{t.tag}" for t in tags],
            bool(analysis.thumbnail),
        )  # fmt: skip


def main():
    logs.configure()
    consume(messaging.VIDEO_READY, config.GROUP_ID, AnalysisJob(AnalysisDatabase()).handle)


if __name__ == "__main__":
    main()
