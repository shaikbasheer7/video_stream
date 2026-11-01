import mongomock
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from common import mongo
from videos import playback


@pytest.fixture(autouse=True)
def mongo_db(monkeypatch, settings):
    """Every test gets a fresh in-memory MongoDB with the real indexes (unique keys behave as in production)."""
    client = mongomock.MongoClient(tz_aware=True)
    monkeypatch.setattr(mongo, "client", lambda: client)
    database = client[settings.MONGO_DB]
    mongo.ensure_indexes(database)
    return database


@pytest.fixture(scope="session")
def _cdn_private_key_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


@pytest.fixture(autouse=True)
def cdn_signing_key(settings, _cdn_private_key_pem):
    """Opening a ready video signs CDN cookies, so every test needs a key."""
    settings.CLOUDFRONT_PRIVATE_KEY = _cdn_private_key_pem
    settings.CLOUDFRONT_KEY_PAIR_ID = "K-TEST"
    playback._private_key.cache_clear()
    yield
    playback._private_key.cache_clear()
