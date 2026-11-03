"""Country of an IP address, from the DB-IP Lite database built into the image (no network calls)."""

import logging
from functools import cache
from pathlib import Path

import maxminddb
from django.conf import settings

logger = logging.getLogger(__name__)


@cache
def _reader():
    path = Path(settings.COUNTRY_DB_PATH)
    if not path.is_file():
        logger.warning("no country database at %s: playback events will have no country", path)
        return None
    return maxminddb.open_database(path)


def country_for_ip(ip):
    """ISO country code, or None for an unknown or private address. Never raises: analytics must not break intake."""
    reader = _reader()
    if reader is None or not ip:
        return None
    try:
        record = reader.get(ip)
    except ValueError:  # not an IP address
        return None
    return record.get("country_code") if record else None
