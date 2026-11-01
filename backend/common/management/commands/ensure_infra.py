"""Create the S3 bucket and Kafka topics if missing. Idempotent; used locally and in CI.

In AWS the bucket and topics should come from infrastructure-as-code, but this is still safe to run.
"""

from pathlib import Path

from botocore.exceptions import ClientError
from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.core.management.base import BaseCommand

from common import kafka, mongo, storage


class Command(BaseCommand):
    help = "Create the S3 bucket (with CORS and lifecycle rules) and the Kafka topics."

    def add_arguments(self, parser):
        parser.add_argument("--skip-s3", action="store_true")
        parser.add_argument("--skip-kafka", action="store_true")
        parser.add_argument("--skip-mongo", action="store_true")

    def handle(self, *args, **options):
        if not options["skip_s3"]:
            self.ensure_bucket()
        if not options["skip_kafka"]:
            self.ensure_topics()
        if not options["skip_mongo"]:
            mongo.ensure_indexes()
            self.stdout.write("mongo indexes: ensured")
        self.ensure_dev_cdn_key()

    def ensure_dev_cdn_key(self):
        """Local stack only: a signing key pair shared with infra/local-cdn through a Docker volume.

        In AWS the public key is uploaded to a CloudFront key group and the private key lives in
        Secrets Manager (see infra/terraform).
        """
        path = settings.CLOUDFRONT_PRIVATE_KEY_PATH
        if not path or Path(path).exists():
            return
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        Path(path).write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        Path(path).with_name("public.pem").write_bytes(
            key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        )
        self.stdout.write(self.style.SUCCESS(f"cdn signing key: generated at {path}"))

    def ensure_bucket(self):
        s3 = storage.client()
        bucket = settings.S3_BUCKET
        try:
            s3.head_bucket(Bucket=bucket)
            self.stdout.write(f"bucket {bucket}: exists")
        except ClientError:
            s3.create_bucket(Bucket=bucket)
            self.stdout.write(self.style.SUCCESS(f"bucket {bucket}: created"))

        if settings.S3_CORS_ORIGINS:
            self.try_apply(
                "CORS",
                lambda: s3.put_bucket_cors(
                    Bucket=bucket,
                    CORSConfiguration={
                        "CORSRules": [
                            {
                                "AllowedOrigins": settings.S3_CORS_ORIGINS,
                                "AllowedMethods": ["PUT", "GET", "HEAD"],
                                "AllowedHeaders": ["*"],
                                "ExposeHeaders": ["ETag"],  # the browser needs part ETags for multipart
                                "MaxAgeSeconds": 3000,
                            }
                        ]
                    },
                ),
            )

        self.try_apply(
            "lifecycle",
            lambda: s3.put_bucket_lifecycle_configuration(
                Bucket=bucket,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "ID": "abort-incomplete-multipart",
                            "Filter": {"Prefix": ""},
                            "Status": "Enabled",
                            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
                        },
                        {
                            "ID": "raw-to-glacier",
                            "Filter": {"Prefix": "raw/"},
                            "Status": "Enabled",
                            "Transitions": [{"Days": 30, "StorageClass": "GLACIER_IR"}],
                        },
                    ]
                },
            ),
        )

    def try_apply(self, name, fn):
        # Local S3 replacements don't support every bucket feature; that must not block startup.
        try:
            fn()
            self.stdout.write(f"bucket {name}: applied")
        except ClientError as exc:
            self.stdout.write(
                self.style.WARNING(f"bucket {name}: not supported here ({exc.response['Error']['Code']})")
            )

    def ensure_topics(self):
        admin = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
        topics = [
            NewTopic(
                name,
                num_partitions=settings.KAFKA_TOPIC_PARTITIONS,
                replication_factor=settings.KAFKA_REPLICATION_FACTOR,
            )
            for name in kafka.ALL_TOPICS
        ]
        for name, future in admin.create_topics(topics, request_timeout=15).items():
            try:
                future.result()
                self.stdout.write(self.style.SUCCESS(f"topic {name}: created"))
            except KafkaException as exc:
                if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                    raise
                self.stdout.write(f"topic {name}: exists")
