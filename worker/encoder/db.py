"""The worker's only direct database access: claiming a video and checking it still exists.

Everything else (ready/failed, renditions) is written by Django's status consumer from Kafka events.
"""

import psycopg

from . import config

# A video is claimable when it is 'uploaded', or 'processing' under this same event_id: that is a
# redelivery after a crash (the offset was never committed). A duplicate message has a different
# event_id and is skipped, so a video is never encoded twice at once.
CLAIM_SQL = """
    UPDATE videos_video
       SET status = 'processing', encode_event_id = %(event_id)s, error_message = '', updated_at = now()
     WHERE id = %(video_id)s
       AND (status = 'uploaded' OR (status = 'processing' AND encode_event_id = %(event_id)s))
 RETURNING source_key
"""


class Database:
    def __init__(self, params=None):
        self.params = params or config.DATABASE
        self.conn = None

    def _connection(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg.connect(**self.params, autocommit=True, connect_timeout=10)
        return self.conn

    def _execute(self, sql, args):
        try:
            return self._connection().execute(sql, args).fetchone()
        except psycopg.OperationalError:
            # Stale connection (DB restart, idle timeout): reconnect once.
            self.conn = None
            return self._connection().execute(sql, args).fetchone()

    def claim(self, video_id, event_id):
        """Mark the video processing. Returns its source key, or None if it should be skipped."""
        row = self._execute(CLAIM_SQL, {"video_id": video_id, "event_id": event_id})
        return row[0] if row else None

    def exists(self, video_id):
        return self._execute("SELECT 1 FROM videos_video WHERE id = %s", (video_id,)) is not None
