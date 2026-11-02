"""Thin wrapper over boto3 so views never touch S3 directly (and tests can swap it out)."""

from functools import cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings


def _make_client(endpoint_url):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=settings.AWS_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": settings.S3_ADDRESSING_STYLE}),
    )


@cache
def client():
    return _make_client(settings.S3_ENDPOINT_URL)


@cache
def presign_client():
    # Signed URLs embed the host, so they must be generated against the endpoint the browser uses.
    return _make_client(settings.S3_PUBLIC_ENDPOINT_URL)


def presign_put(key, content_type, expires_in):
    return presign_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )


def create_multipart_upload(key, content_type):
    response = client().create_multipart_upload(Bucket=settings.S3_BUCKET, Key=key, ContentType=content_type)
    return response["UploadId"]


def presign_part(key, upload_id, part_number, expires_in):
    return presign_client().generate_presigned_url(
        "upload_part",
        Params={"Bucket": settings.S3_BUCKET, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=expires_in,
    )


def complete_multipart_upload(key, upload_id, parts):
    client().complete_multipart_upload(
        Bucket=settings.S3_BUCKET,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": p["part_number"], "ETag": p["etag"]} for p in parts]},
    )


def abort_multipart_upload(key, upload_id):
    try:
        client().abort_multipart_upload(Bucket=settings.S3_BUCKET, Key=key, UploadId=upload_id)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchUpload":
            raise


def head_object(key):
    """Object metadata, or None if it doesn't exist."""
    try:
        return client().head_object(Bucket=settings.S3_BUCKET, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def delete_object(key):
    client().delete_object(Bucket=settings.S3_BUCKET, Key=key)


def delete_prefix(prefix):
    paginator = client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            client().delete_objects(Bucket=settings.S3_BUCKET, Delete={"Objects": keys, "Quiet": True})
