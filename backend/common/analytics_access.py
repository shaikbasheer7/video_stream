"""Databases and least-privilege roles for the data stack (Airflow, Superset).

- analytics_etl: the pipeline. Reads video metadata, writes the analytics tables.
- analytics_ro:  Superset. Reads analytics tables and views only, so a BI user can never query accounts_user
  (emails, password hashes). The views run with their owner's rights, so they can show video titles.
"""

import logging

from django.conf import settings
from django.db import connection
from psycopg import sql

logger = logging.getLogger(__name__)

TABLES = ["daily_video_stats", "daily_video_retention", "daily_streaming_quality", "daily_platform_stats"]
VIEWS = ["analytics_video_stats", "analytics_video_retention"]
# Written only by the pipeline. Superset doesn't get these: per-user recommendations aren't BI data.
RECOMMENDATION_TABLES = ["video_embeddings", "ranked_videos", "similar_videos", "recommendations"]
ML_TABLES = ["video_tags", "video_transcripts"]
METADATA_DATABASES = ["airflow", "superset"]


def _ensure_role(cursor, name, password):
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name])
    verb = "ALTER" if cursor.fetchone() else "CREATE"
    statement = sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(name), sql.Literal(password))
    cursor.execute(statement.as_string(connection.connection))


def _grant(cursor, privileges, objects, role):
    for name in objects:
        statement = sql.SQL("GRANT " + privileges + " ON {} TO {}").format(sql.Identifier(name), sql.Identifier(role))
        cursor.execute(statement.as_string(connection.connection))


def ensure_analytics_access():
    """Idempotent. Returns False when the data stack isn't configured here (no passwords set)."""
    if not (settings.ANALYTICS_ETL_PASSWORD and settings.ANALYTICS_RO_PASSWORD):
        return False
    with connection.cursor() as cursor:
        for database in METADATA_DATABASES:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [database])
            if not cursor.fetchone():
                statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
                cursor.execute(statement.as_string(connection.connection))
                logger.info("created database %s", database)

        _ensure_role(cursor, "analytics_etl", settings.ANALYTICS_ETL_PASSWORD)
        _grant(cursor, "SELECT, INSERT, DELETE", TABLES + RECOMMENDATION_TABLES, "analytics_etl")
        _grant(cursor, "SELECT", ["videos_video"], "analytics_etl")

        # The embeddings include tags and transcripts.
        _grant(cursor, "SELECT", ML_TABLES, "analytics_etl")

        _ensure_role(cursor, "analytics_ro", settings.ANALYTICS_RO_PASSWORD)
        _grant(cursor, "SELECT", TABLES + VIEWS, "analytics_ro")

        if settings.ML_WORKER_DB_PASSWORD:
            _ensure_role(cursor, "ml_worker", settings.ML_WORKER_DB_PASSWORD)
            _grant(cursor, "SELECT, INSERT, DELETE", ML_TABLES, "ml_worker")
            _grant(cursor, "SELECT", ["videos_video"], "ml_worker")
    return True
