"""Dependency checks for /api/health/ready/ (smoke tests, deploy gates and monitoring).

/api/health/ stays a cheap liveness check for Docker and the load balancer: a broken MongoDB must not
make the load balancer pull every API instance.
"""

import time

from confluent_kafka.admin import AdminClient
from django.conf import settings
from django.db import connection

from . import kafka, mongo, storage


def check_postgres():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def check_mongo():
    mongo.client().admin.command("ping")


def check_kafka():
    metadata = AdminClient(kafka.client_config()).list_topics(timeout=3)
    if not metadata.brokers:
        raise RuntimeError("no brokers")


def check_s3():
    storage.client().head_bucket(Bucket=settings.S3_BUCKET)


CHECKS = {"postgres": check_postgres, "mongo": check_mongo, "kafka": check_kafka, "s3": check_s3}


def run_checks(checks=None):
    results = {}
    for name, check in (checks or CHECKS).items():
        started = time.monotonic()
        try:
            check()
            results[name] = {"ok": True}
        except Exception as exc:  # report every dependency, whatever went wrong
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        results[name]["ms"] = round((time.monotonic() - started) * 1000)
    return results
