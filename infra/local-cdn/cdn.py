"""Local stand-in for CloudFront (development only).

Behaves like the distribution in infra/terraform:
- It is the only reader of the private bucket (like Origin Access Control).
- /hls/*        requires valid CloudFront signed cookies (trusted key group).
- /thumbnails/* is public.
- anything else is 403 (the bucket policy only lets CloudFront read hls/ and thumbnails/).

Cookie verification follows the CloudFront spec independently of the signer in Django, so the
two check each other: custom policy, CloudFront-safe base64, RSA-SHA1, wildcard Resource, DateLessThan.
"""

import base64
import json
import logging
import os
import re
import time
from functools import cache
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger("local-cdn")

PUBLIC_BASE_URL = os.environ.get("CDN_BASE_URL", "http://localhost:8080/cdn").rstrip("/")
KEY_PAIR_ID = os.environ.get("CLOUDFRONT_KEY_PAIR_ID", "")
PUBLIC_KEY_PATH = os.environ.get("CLOUDFRONT_PUBLIC_KEY_PATH", "/var/cdn-keys/public.pem")
BUCKET = os.environ.get("S3_BUCKET", "streaming-media")


class AccessDeniedError(Exception):
    pass


def b64decode_cloudfront(value):
    return base64.b64decode(value.replace("-", "+").replace("_", "=").replace("~", "/"), validate=True)


def resource_matches(pattern, url):
    """CloudFront wildcards: * matches zero or more characters (including /), ? matches exactly one."""
    regex = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.fullmatch(regex, url) is not None


@cache
def public_key():
    return serialization.load_pem_public_key(Path(PUBLIC_KEY_PATH).read_bytes())


def verify_signed_cookies(cookie_header, url, now=None, key=None, key_pair_id=None):
    """Raise AccessDeniedError unless the request carries cookies that grant access to `url`."""
    jar = cookies.SimpleCookie()
    jar.load(cookie_header or "")
    values = {name: morsel.value for name, morsel in jar.items()}
    if "CloudFront-Policy" not in values:
        raise AccessDeniedError("missing CloudFront-Policy cookie (only custom policies are supported)")
    if values.get("CloudFront-Key-Pair-Id") != (key_pair_id or KEY_PAIR_ID):
        raise AccessDeniedError("unknown key pair id")
    try:
        policy_bytes = b64decode_cloudfront(values["CloudFront-Policy"])
        signature = b64decode_cloudfront(values.get("CloudFront-Signature", ""))
    except ValueError as exc:
        raise AccessDeniedError("malformed cookie encoding") from exc
    try:
        (key or public_key()).verify(signature, policy_bytes, padding.PKCS1v15(), hashes.SHA1())
    except InvalidSignature as exc:
        raise AccessDeniedError("bad signature") from exc

    statement = json.loads(policy_bytes)["Statement"][0]
    if not resource_matches(statement.get("Resource", ""), url):
        raise AccessDeniedError("policy does not cover this URL")
    conditions = statement.get("Condition", {})
    now = now or time.time()
    if now >= conditions.get("DateLessThan", {}).get("AWS:EpochTime", 0):
        raise AccessDeniedError("expired")
    if now < conditions.get("DateGreaterThan", {}).get("AWS:EpochTime", 0):
        raise AccessDeniedError("not yet valid")


@cache
def s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": os.environ.get("S3_ADDRESSING_STYLE", "auto")}),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "local-cdn"

    def do_GET(self):  # noqa: N802
        self.serve(body=True)

    def do_HEAD(self):  # noqa: N802
        self.serve(body=False)

    def serve(self, body):
        key = self.path.split("?", 1)[0].lstrip("/")
        if key == "healthz":
            return self.error(200, "ok")
        url = f"{PUBLIC_BASE_URL}/{key}"
        if key.startswith("hls/"):
            try:
                verify_signed_cookies(self.headers.get("Cookie"), url)
            except AccessDeniedError as exc:
                return self.error(403, f"Access denied: {exc}")
        elif not key.startswith("thumbnails/"):
            return self.error(403, "Access denied")

        try:
            obj = s3().get_object(Bucket=BUCKET, Key=key)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            return self.error(404 if code in ("NoSuchKey", "404") else 502, code)

        self.send_response(200)
        self.send_header("Content-Type", obj.get("ContentType", "application/octet-stream"))
        self.send_header("Content-Length", str(obj["ContentLength"]))
        if obj.get("CacheControl"):
            self.send_header("Cache-Control", obj["CacheControl"])
        self.send_header("ETag", obj["ETag"])
        self.end_headers()
        if body:
            for chunk in obj["Body"].iter_chunks(64 * 1024):
                self.wfile.write(chunk)

    def error(self, status, message):
        payload = message.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def log_message(self, fmt, *args):
        logger.info("%s %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    port = int(os.environ.get("PORT", 8090))
    logger.info("local CDN on :%d for %s (bucket %s)", port, PUBLIC_BASE_URL, BUCKET)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
