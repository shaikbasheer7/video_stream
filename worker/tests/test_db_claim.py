"""CLAIM_SQL against a real PostgreSQL (skipped unless POSTGRES_HOST is set).

Uses a throwaway schema with a minimal videos_video table, so it never touches app data.
"""

import os
import uuid

import psycopg
import pytest

from encoder import config
from encoder.db import Database

pytestmark = pytest.mark.skipif(not os.environ.get("POSTGRES_HOST"), reason="needs PostgreSQL")


@pytest.fixture
def db():
    schema = f"claimtest_{uuid.uuid4().hex[:8]}"
    admin = psycopg.connect(**config.DATABASE, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    admin.execute(
        f"""CREATE TABLE {schema}.videos_video (
                id uuid PRIMARY KEY, status varchar(20), source_key varchar(512),
                encode_event_id varchar(64) DEFAULT '', error_message text DEFAULT '', updated_at timestamptz)"""
    )
    database = Database({**config.DATABASE, "options": f"-c search_path={schema}"})
    database.insert = lambda status, event_id="": admin.execute(
        f"INSERT INTO {schema}.videos_video (id, status, source_key, encode_event_id) VALUES (%s, %s, 'raw/k', %s)"
        " RETURNING id",
        (uuid.uuid4(), status, event_id),
    ).fetchone()[0]
    database.status = lambda vid: admin.execute(
        f"SELECT status, encode_event_id FROM {schema}.videos_video WHERE id = %s", (vid,)
    ).fetchone()
    yield database
    admin.execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


def test_claims_uploaded_video_once_per_event(db):
    vid = db.insert("uploaded")
    assert db.claim(vid, "event-1") == "raw/k"
    assert db.status(vid) == ("processing", "event-1")
    assert db.claim(vid, "event-2") is None  # duplicate message: skip
    assert db.claim(vid, "event-1") == "raw/k"  # redelivery after a crash: take over


@pytest.mark.parametrize("status", ["uploading", "ready", "failed"])
def test_never_claims_other_states(db, status):
    vid = db.insert(status, event_id="event-1")
    assert db.claim(vid, "event-1") is None
    assert db.status(vid)[0] == status


def test_deleted_video(db):
    assert db.claim(uuid.uuid4(), "event-1") is None
    assert db.exists(uuid.uuid4()) is False
