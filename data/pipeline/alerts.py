"""Tell someone when the daily pipeline fails (blueprint step 58). Stdlib only."""

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def failure_message(dag_id, task_id, day, error):
    return f"Pipeline failure: {dag_id}.{task_id} for {day}: {error}"


def send(message, url=None, opener=urllib.request.urlopen):
    """Always logs. Also posts to ALERT_WEBHOOK_URL if set (Slack, Discord and similar accept this shape).

    An alert that can't be delivered must not hide the failure that caused it, so this never raises.
    """
    logger.error(message)
    url = url if url is not None else os.environ.get("ALERT_WEBHOOK_URL", "")
    if not url:
        return False
    body = json.dumps({"text": message, "content": message}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener(request, timeout=10):
            return True
    except (urllib.error.URLError, OSError) as exc:
        logger.error("could not deliver the alert: %s", exc)
        return False


def on_task_failure(context):
    """Airflow on_failure_callback."""
    send(
        failure_message(
            context["dag"].dag_id,
            context["task_instance"].task_id,
            (context.get("dag_run").conf or {}).get("date") or context.get("logical_date"),
            context.get("exception"),
        )
    )
