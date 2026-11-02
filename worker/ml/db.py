"""The ML worker's results. It connects as the ml_worker role, which can write these two tables and nothing else."""

from datetime import UTC, datetime

import psycopg

from encoder.db import Database

from . import config


class VideoGone(Exception):
    """The owner deleted the video while it was being analysed."""


class AnalysisDatabase(Database):
    def already_analysed(self, video_id, event_id):
        sql = "SELECT 1 FROM video_transcripts WHERE video_id = %s AND event_id = %s"
        return self._execute(sql, (video_id, event_id)) is not None

    def save(self, video_id, event_id, transcript, subtitles_key, tags):
        """Replaces earlier results in one transaction. A tag someone set by hand is kept."""
        try:
            with self._connection().transaction() as tx:
                cur = tx.connection.cursor()
                cur.execute("DELETE FROM video_transcripts WHERE video_id = %s", (video_id,))
                cur.execute("DELETE FROM video_tags WHERE video_id = %s AND source = 'clip'", (video_id,))
                cur.execute(
                    """INSERT INTO video_transcripts
                         (video_id, language, text, subtitles_key, model, event_id, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        video_id,
                        transcript.language,
                        transcript.text,
                        subtitles_key,
                        config.WHISPER_MODEL,
                        event_id,
                        datetime.now(UTC),
                    ),
                )
                cur.executemany(
                    """INSERT INTO video_tags (video_id, tag, kind, confidence, source)
                       VALUES (%s, %s, %s, %s, 'clip')
                       ON CONFLICT (video_id, tag, kind) DO NOTHING""",
                    [(video_id, tag.tag, tag.kind, tag.confidence) for tag in tags],
                )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise VideoGone(video_id) from exc
