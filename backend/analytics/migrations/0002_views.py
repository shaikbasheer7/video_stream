from django.db import migrations

# Superset reads these views, not the app's tables: they add a video title and nothing else. A deleted video
# keeps its history under a placeholder title. SQLite (quick local runs and tests) accepts the same SQL.
VIDEO_STATS = """
CREATE VIEW analytics_video_stats AS
SELECT s.date, s.video_id, COALESCE(v.title, '(deleted video)') AS title, s.views, s.unique_viewers,
       s.watch_time_sec, s.avg_completion_pct, s.completions, s.buffering_events, s.buffering_ms
  FROM daily_video_stats s LEFT JOIN videos_video v ON v.id = s.video_id
"""
VIDEO_RETENTION = """
CREATE VIEW analytics_video_retention AS
SELECT r.date, r.video_id, COALESCE(v.title, '(deleted video)') AS title, r.position_pct, r.viewers
  FROM daily_video_retention r LEFT JOIN videos_video v ON v.id = r.video_id
"""


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0001_initial"),
        ("videos", "0003_video_encode_event_id"),
    ]

    operations = [
        migrations.RunSQL(VIDEO_STATS, "DROP VIEW analytics_video_stats"),
        migrations.RunSQL(VIDEO_RETENTION, "DROP VIEW analytics_video_retention"),
    ]
