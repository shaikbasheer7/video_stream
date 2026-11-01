import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from cdn import AccessDeniedError, resource_matches, verify_signed_cookies

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
URL = "http://localhost:8080/cdn/hls/abc/720p/seg_000.ts"


def b64(data):
    return base64.b64encode(data).decode().replace("+", "-").replace("=", "_").replace("/", "~")


def cookie(resource="http://localhost:8080/cdn/hls/abc/*", expires=None, key=KEY, key_id="LOCAL", tamper=False):
    condition = {"DateLessThan": {"AWS:EpochTime": expires or time.time() + 60}}
    policy = json.dumps({"Statement": [{"Resource": resource, "Condition": condition}]}, separators=(",", ":")).encode()
    signature = key.sign(policy, padding.PKCS1v15(), hashes.SHA1())
    if tamper:
        policy = policy.replace(b"abc", b"xyz")
    return f"CloudFront-Policy={b64(policy)}; CloudFront-Signature={b64(signature)}; CloudFront-Key-Pair-Id={key_id}"


def verify(header, url=URL):
    verify_signed_cookies(header, url, key=KEY.public_key(), key_pair_id="LOCAL")


def test_valid_cookie_grants_access():
    verify(cookie())


@pytest.mark.parametrize(
    ("header", "url", "reason"),
    [
        (None, URL, "missing"),
        (cookie(), "http://localhost:8080/cdn/hls/other/master.m3u8", "does not cover"),
        (cookie(expires=time.time() - 1), URL, "expired"),
        (cookie(key_id="SOMEONE-ELSE"), URL, "unknown key"),
        (cookie(tamper=True), URL, "bad signature"),
        (cookie(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)), URL, "bad signature"),
    ],
)
def test_rejections(header, url, reason):
    with pytest.raises(AccessDeniedError, match=reason):
        verify(header, url)


def test_wildcards():
    assert resource_matches("https://cdn/hls/a/*", "https://cdn/hls/a/1080p/seg_001.ts")
    assert not resource_matches("https://cdn/hls/a/*", "https://cdn/hls/ab/master.m3u8")
    assert resource_matches("https://cdn/hls/?/x", "https://cdn/hls/a/x")
    assert not resource_matches("https://cdn/hls/a.b/*", "https://cdn/hls/aXb/x")  # dots are literal
