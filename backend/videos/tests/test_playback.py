import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from rest_framework.test import APIClient

from accounts.models import User
from videos import playback
from videos.models import Video


def cloudfront_b64decode(value):
    return base64.b64decode(value.replace("-", "+").replace("_", "=").replace("~", "/"))


@pytest.fixture
def signing_key(settings):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings.CLOUDFRONT_PRIVATE_KEY = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    settings.CLOUDFRONT_KEY_PAIR_ID = "K2TESTKEY"
    settings.CDN_BASE_URL = "https://cdn.example.com"
    settings.CDN_COOKIE_DOMAIN = ".example.com"
    settings.CDN_COOKIE_SECURE = True
    playback._private_key.cache_clear()
    yield key.public_key()
    playback._private_key.cache_clear()


@pytest.fixture
def owner():
    return User.objects.create_user(email="owner@example.com", password="pw-123456789")


def make_video(owner, status=Video.Status.READY):
    video = Video.objects.create(
        owner=owner, title="Clip", original_filename="c.mp4", content_type="video/mp4", size_bytes=1,
        source_key="raw/x/source.mp4", status=status, duration_sec=600,
    )  # fmt: skip
    video.master_playlist_key = f"hls/{video.id}/master.m3u8"
    video.save()
    return video


@pytest.mark.django_db
def test_ready_video_sets_cloudfront_cookies_any_viewer_can_use(signing_key, owner):
    video = make_video(owner)
    response = APIClient().get(f"/api/videos/{video.id}/")  # anonymous viewer

    assert response.status_code == 200
    assert response.data["playback"]["hls_url"] == f"https://cdn.example.com/hls/{video.id}/master.m3u8"

    cookies = response.cookies
    assert cookies["CloudFront-Key-Pair-Id"].value == "K2TESTKEY"
    for name in ("CloudFront-Policy", "CloudFront-Signature", "CloudFront-Key-Pair-Id"):
        assert cookies[name]["path"] == f"/hls/{video.id}/"
        assert cookies[name]["domain"] == ".example.com"
        assert cookies[name]["httponly"] and cookies[name]["secure"]
        assert not set(cookies[name].value) & set("+=/")  # CloudFront-safe alphabet only

    policy_bytes = cloudfront_b64decode(cookies["CloudFront-Policy"].value)
    statement = json.loads(policy_bytes)["Statement"][0]
    assert statement["Resource"] == f"https://cdn.example.com/hls/{video.id}/*"
    expires = statement["Condition"]["DateLessThan"]["AWS:EpochTime"]
    assert 600 + 2 * 3600 - 5 <= expires - time.time() <= 600 + 2 * 3600 + 5  # duration + 2 h

    # What CloudFront does: verify RSA-SHA1 over the exact policy bytes with the key group's public key.
    signing_key.verify(
        cloudfront_b64decode(cookies["CloudFront-Signature"].value), policy_bytes, padding.PKCS1v15(), hashes.SHA1()
    )


@pytest.mark.django_db
def test_not_ready_video_gets_no_cookies_and_is_owner_only(signing_key, owner):
    video = make_video(owner, status=Video.Status.PROCESSING)
    assert APIClient().get(f"/api/videos/{video.id}/").status_code == 404

    client = APIClient()
    client.force_authenticate(owner)
    response = client.get(f"/api/videos/{video.id}/")
    assert response.status_code == 200
    assert "playback" not in response.data
    assert "CloudFront-Policy" not in response.cookies


@pytest.mark.django_db
def test_public_browse_but_mine_and_upload_need_login(owner):
    make_video(owner)
    make_video(owner, status=Video.Status.FAILED)
    anon = APIClient()
    assert [v["status"] for v in anon.get("/api/videos/").data["results"]] == ["ready"]
    assert anon.get("/api/videos/?mine=true").status_code == 401
    assert anon.post("/api/videos/", {}, format="json").status_code == 401
    assert anon.get("/api/videos/not-a-uuid/").status_code == 404


def test_playback_ttl_is_capped(settings, signing_key):
    class Long:
        id = "abc"
        duration_sec = 100 * 3600
        master_playlist_key = "hls/abc/master.m3u8"

    from rest_framework.response import Response

    response = Response()
    info = playback.grant_playback(response, Long())
    policy = json.loads(cloudfront_b64decode(response.cookies["CloudFront-Policy"].value))
    expires = policy["Statement"][0]["Condition"]["DateLessThan"]["AWS:EpochTime"]
    assert expires - time.time() <= settings.PLAYBACK_MAX_TTL_SEC + 5
    assert info["expires_at"].startswith(time.strftime("%Y", time.gmtime(expires)))
