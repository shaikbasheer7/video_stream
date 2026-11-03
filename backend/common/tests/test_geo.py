import pytest

from common import geo


class FakeReader:
    def get(self, ip):
        if ip == "not-an-ip":
            raise ValueError(ip)
        return {"8.8.8.8": {"country_code": "US"}}.get(ip)


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setattr(geo, "_reader", FakeReader)


def test_looks_up_a_public_address(reader):
    assert geo.country_for_ip("8.8.8.8") == "US"


@pytest.mark.parametrize("ip", ["10.0.0.1", "not-an-ip", "", None])
def test_unknown_private_or_invalid_addresses_have_no_country(reader, ip):
    assert geo.country_for_ip(ip) is None


def test_a_missing_database_means_no_country_rather_than_an_error(settings, tmp_path):
    settings.COUNTRY_DB_PATH = str(tmp_path / "missing.mmdb")
    geo._reader.cache_clear()
    assert geo.country_for_ip("8.8.8.8") is None
    geo._reader.cache_clear()
