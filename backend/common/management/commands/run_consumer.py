import signal
from importlib import import_module

from django.core.management.base import BaseCommand, CommandError

from common import kafka

# name -> (topics, consumer group, "module.function" handler). Each runs as its own process/container.
CONSUMERS = {
    "status": ([kafka.VIDEO_READY, kafka.VIDEO_FAILED], "api-status", "videos.status.apply_event"),
    "analytics": ([kafka.EVENTS_PLAYBACK], "analytics", "events.analytics.handle_playback_event"),
    "notify": ([kafka.VIDEO_READY, kafka.VIDEO_FAILED], "notify", "notifications.handlers.handle_video_event"),
    "feed": ([kafka.VIDEO_READY], "feed", "social.feed.handle_video_ready"),
}


class Command(BaseCommand):
    help = f"Run a Kafka subscriber: {', '.join(CONSUMERS)}."

    def add_arguments(self, parser):
        parser.add_argument("name", choices=sorted(CONSUMERS))

    def handle(self, *args, name, **options):
        if name not in CONSUMERS:
            raise CommandError(f"unknown consumer {name}")
        topics, group, handler_path = CONSUMERS[name]
        module, func = handler_path.rsplit(".", 1)
        handler = getattr(import_module(module), func)

        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        kafka.run_consumer(
            topics, group_id=group, handler=handler, should_stop=lambda: stopping, heartbeat_file="/tmp/heartbeat"
        )
