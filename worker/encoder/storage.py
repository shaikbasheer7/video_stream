from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

import boto3
from botocore.config import Config

from . import config

CONTENT_TYPES = {".m3u8": "application/vnd.apple.mpegurl", ".ts": "video/mp2t", ".jpg": "image/jpeg"}
# Segments never change; playlists get a short TTL so a re-encode shows up quickly.
CACHE_CONTROL = {".ts": "public, max-age=31536000, immutable", ".m3u8": "public, max-age=60"}


@cache
def client():
    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL,
        region_name=config.AWS_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": config.S3_ADDRESSING_STYLE},
            max_pool_connections=16,
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


def download(key, path):
    client().download_file(config.S3_BUCKET, key, str(path))


def upload_file(path, key):
    path = Path(path)
    extra = {"ContentType": CONTENT_TYPES.get(path.suffix, "application/octet-stream")}
    if path.suffix in CACHE_CONTROL:
        extra["CacheControl"] = CACHE_CONTROL[path.suffix]
    client().upload_file(str(path), config.S3_BUCKET, key, ExtraArgs=extra)


def upload_dir(local_dir, prefix):
    """Upload every file under local_dir to prefix/<relative path>. Returns the number of files."""
    local_dir = Path(local_dir)
    files = [p for p in local_dir.rglob("*") if p.is_file()]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda p: upload_file(p, prefix + p.relative_to(local_dir).as_posix()), files))
    return len(files)


def delete_prefix(prefix):
    paginator = client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=config.S3_BUCKET, Prefix=prefix):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            client().delete_objects(Bucket=config.S3_BUCKET, Delete={"Objects": keys, "Quiet": True})
