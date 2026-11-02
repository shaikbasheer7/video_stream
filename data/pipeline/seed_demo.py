"""Local development only: synthetic playback events, so the dashboards have something to show.

    python -m pipeline.seed_demo --days 14        # then backfill those days with pipeline.run
    python -m pipeline.seed_demo --clear

Every generated session id starts with "demo-", so --clear removes exactly these events. Refuses to run against
MongoDB Atlas (mongodb+srv://), which is what staging and production use.
"""

import argparse
import os
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta

from . import io

PREFIX = "demo-"
DEVICES = [("desktop", 0.55), ("mobile", 0.35), ("tablet", 0.10)]
COUNTRIES = [("IN", 0.5), ("US", 0.25), ("DE", 0.15), ("BR", 0.10)]
# (rendition, chance of starting there); phones sit lower on the ladder and stall more.
QUALITIES = {
    "desktop": [("1080p", 0.6), ("720p", 0.3), ("480p", 0.1)],
    "tablet": [("1080p", 0.3), ("720p", 0.5), ("480p", 0.2)],
    "mobile": [("1080p", 0.1), ("720p", 0.4), ("480p", 0.5)],
}
STALL_CHANCE = {"desktop": 0.01, "tablet": 0.02, "mobile": 0.05}  # per 10 s of playback
LADDER = ["480p", "720p", "1080p"]


def pick(rng, weighted):
    return rng.choices([v for v, _ in weighted], [w for _, w in weighted])[0]


def session_events(rng, video_id, duration, start):
    """One believable session: most viewers leave early, a few watch to the end."""
    device, country = pick(rng, DEVICES), pick(rng, COUNTRIES)
    session_id = f"{PREFIX}{uuid.uuid4().hex[:16]}"
    viewer = rng.randint(1, 400)
    identity = {"user_id": viewer} if rng.random() < 0.4 else {"anonymous_id": f"{PREFIX}{viewer}"}
    quality = pick(rng, QUALITIES[device])
    leave_at = duration if rng.random() < 0.25 else duration * rng.betavariate(1.2, 2.5)
    clock, position = start, 0.0
    events = []

    def add(kind, **extra):
        events.append(
            {
                "_id": str(uuid.uuid4()),
                "type": kind,
                "video_id": video_id,
                "session_id": session_id,
                "anonymous_id": identity.get("anonymous_id", f"{PREFIX}{session_id}"),
                "position_sec": round(position, 1),
                "quality": quality,
                "device": device,
                "country": country,
                "client_ts": clock,
                "received_at": clock + timedelta(seconds=rng.uniform(0, 15)),
                **({"user_id": identity["user_id"]} if "user_id" in identity else {}),
                **extra,
            }
        )

    add("play")
    add("buffering", duration_ms=rng.randint(150, 1800))  # startup
    while position + 10 <= leave_at:
        position += 10
        clock += timedelta(seconds=10)
        add("progress")
        if rng.random() < STALL_CHANCE[device]:
            add("buffering", duration_ms=rng.randint(300, 6000))
            clock += timedelta(seconds=2)
        if rng.random() < 0.02:
            step = rng.choice([-1, 1])
            index = LADDER.index(quality) + step
            if 0 <= index < len(LADDER):
                previous, quality = quality, LADDER[index]
                add("quality_change", from_quality=previous, to_quality=quality, auto=True)
        if position >= duration * 0.95 and not any(e["type"] == "complete" for e in events):
            add("complete", watch_time_sec=position)
    # Leaving between two progress events: the player reports the final position.
    clock += timedelta(seconds=leave_at - position)
    position = leave_at
    if position < duration * 0.95:
        add("progress")
    elif not any(e["type"] == "complete" for e in events):
        add("complete", watch_time_sec=position)
    return events


def seed(days, sessions_per_day, seed_value=7):
    rng = random.Random(seed_value)
    with io.postgres() as conn:
        videos = conn.execute(
            "SELECT id::text, duration_sec FROM videos_video WHERE status = 'ready' AND duration_sec > 0"
        ).fetchall()
    if not videos:
        sys.exit("No ready videos to generate views for: upload one first.")
    popularity = [1 / (rank + 1) for rank in range(len(videos))]  # a few videos get most of the views

    collection = io.mongo_collection()
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        batch = []
        for _ in range(int(sessions_per_day * rng.uniform(0.7, 1.3))):
            video_id, duration = rng.choices(videos, popularity)[0]
            # Stays well inside the day so a session's events aren't split across midnight.
            start = day + timedelta(hours=rng.uniform(1, 22))
            batch.extend(session_events(rng, video_id, duration, start))
        collection.insert_many(batch)
        total += len(batch)
    print(f"inserted {total} demo events over {days} days for {len(videos)} videos")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--sessions-per-day", type=int, default=120)
    parser.add_argument("--clear", action="store_true", help="delete the demo events instead")
    args = parser.parse_args()

    if os.environ["MONGO_URL"].startswith("mongodb+srv://"):
        sys.exit("Refusing to write demo data to MongoDB Atlas.")
    if args.clear:
        deleted = io.mongo_collection().delete_many({"session_id": {"$regex": f"^{PREFIX}"}}).deleted_count
        print(f"deleted {deleted} demo events (re-run pipeline.run for those days to refresh the tables)")
    else:
        seed(args.days, args.sessions_per_day)


if __name__ == "__main__":
    main()
