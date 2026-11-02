"""CloudFront signed cookies for HLS playback.

Signed cookies rather than signed URLs because one video is hundreds of segment requests. The cookie
policy covers <CDN>/hls/<video_id>/* only, and the cookie path matches, so a viewer can fetch every
playlist and segment of that video and nothing else.
"""

import base64
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from urllib.parse import urlparse

from botocore.signers import CloudFrontSigner
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@cache
def _private_key():
    pem = settings.CLOUDFRONT_PRIVATE_KEY
    if not pem and settings.CLOUDFRONT_PRIVATE_KEY_PATH:
        pem = Path(settings.CLOUDFRONT_PRIVATE_KEY_PATH).read_text()
    if not pem or not settings.CLOUDFRONT_KEY_PAIR_ID:
        raise ImproperlyConfigured("CloudFront signing key is not configured")
    return serialization.load_pem_private_key(pem.encode(), password=None)


def _rsa_sign(message):
    # CloudFront requires RSA with SHA-1 for signed URLs and cookies.
    return _private_key().sign(message, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303


def cloudfront_b64(data):
    """Base64 with CloudFront's URL-safe substitutions: + becomes -, = becomes _, / becomes ~."""
    return base64.b64encode(data).decode().replace("+", "-").replace("=", "_").replace("/", "~")


def signed_cookie_values(resource, expires_at):
    signer = CloudFrontSigner(settings.CLOUDFRONT_KEY_PAIR_ID, _rsa_sign)
    policy = signer.build_policy(resource, expires_at).encode()
    return {
        "CloudFront-Policy": cloudfront_b64(policy),
        "CloudFront-Signature": cloudfront_b64(_rsa_sign(policy)),
        "CloudFront-Key-Pair-Id": settings.CLOUDFRONT_KEY_PAIR_ID,
    }


def cdn_url(key):
    return f"{settings.CDN_BASE_URL}/{key}"


def grant_playback(response, video):
    """Set the cookies on `response` and return what the player needs."""
    ttl = (video.duration_sec or 0) + settings.PLAYBACK_MIN_TTL_SEC
    expires_at = (datetime.now(UTC) + timedelta(seconds=min(ttl, settings.PLAYBACK_MAX_TTL_SEC))).replace(microsecond=0)
    prefix = f"hls/{video.id}/"
    cookie_path = f"{urlparse(settings.CDN_BASE_URL).path}/{prefix}"
    for name, value in signed_cookie_values(cdn_url(prefix) + "*", expires_at).items():
        response.set_cookie(
            name,
            value,
            expires=expires_at,
            path=cookie_path,
            domain=settings.CDN_COOKIE_DOMAIN,
            secure=settings.CDN_COOKIE_SECURE,
            httponly=True,
            samesite="Lax",
        )
    return {"hls_url": cdn_url(video.master_playlist_key), "expires_at": expires_at.isoformat()}
