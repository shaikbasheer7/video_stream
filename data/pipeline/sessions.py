"""Reconstruct what was actually watched in one playback session from its ordered events (pure functions).

Events only mark moments, so the time between two of them counts as watched when the player was playing and
the position moved forward. Everything downstream (watch time, completion, retention) builds on these segments.
"""

from dataclasses import dataclass, field

# A forward jump larger than this with no seek event means events went missing (progress fires every 10 s):
# counting it would invent watch time.
MAX_SEGMENT_SEC = 60.0
MOMENT_EVENTS = {"progress", "buffering", "quality_change", "complete"}


@dataclass
class Segment:
    start: float
    end: float
    quality: str

    @property
    def seconds(self):
        return self.end - self.start


@dataclass
class SessionSummary:
    segments: list = field(default_factory=list)
    played: bool = False  # had a play event: this session counts as a view
    completed: bool = False
    buffering_events: int = 0  # stalls once playback was under way
    buffering_ms: int = 0
    startup_events: int = 0  # waiting before anything had been watched
    startup_ms: int = 0
    quality_changes: int = 0

    @property
    def watch_time_sec(self):
        return sum(s.seconds for s in self.segments)


def _quality(event, fallback="unknown"):
    return event.get("quality") or fallback


def _number(event, key):
    value = event.get(key)
    return None if value is None or value != value else float(value)  # NaN from a pandas row counts as missing


def summarize_session(events):
    """events: dicts for one session, oldest first."""
    summary = SessionSummary()
    position = None
    playing = False
    quality = "unknown"

    def watched_until(end, end_quality):
        if playing and position is not None and end is not None and 0 < end - position <= MAX_SEGMENT_SEC:
            summary.segments.append(Segment(position, end, end_quality))

    for event in events:
        kind = event.get("type")
        at = _number(event, "position_sec")
        quality = _quality(event, quality)

        if kind == "play":
            position, playing = at, True
            summary.played = True
        elif kind == "pause":
            watched_until(at, quality)
            position, playing = at, False
        elif kind == "seek":
            watched_until(_number(event, "from_sec"), quality)
            position = _number(event, "to_sec")
        elif kind in MOMENT_EVENTS:
            if position is None:  # the session started before this day's window: it was already playing
                playing = True
            watched_until(at, quality)
            if at is not None:  # an event without a position must not lose track of where playback is
                position = at

        if kind == "buffering":
            duration = int(_number(event, "duration_ms") or 0)
            if summary.segments:
                summary.buffering_events += 1
                summary.buffering_ms += duration
            else:
                summary.startup_events += 1
                summary.startup_ms += duration
        elif kind == "quality_change":
            summary.quality_changes += 1
        elif kind == "complete":
            summary.completed = True
    return summary


def covered_seconds(segments):
    """Length of the union of the segments: rewatching a part doesn't count towards completion twice."""
    total, reach = 0.0, None
    for segment in sorted(segments, key=lambda s: s.start):
        if reach is None or segment.start > reach:
            total += segment.seconds
            reach = segment.end
        elif segment.end > reach:
            total += segment.end - reach
            reach = segment.end
    return total


def retention_slices(segments, duration, slices=20):
    """Indexes of the slices of the video this session watched (at least half of the slice)."""
    size = duration / slices
    watched = set()
    for index in range(slices):
        low, high = index * size, (index + 1) * size
        overlap = covered_seconds(
            [
                Segment(max(s.start, low), min(s.end, high), s.quality)
                for s in segments
                if s.start < high and s.end > low
            ]
        )
        if overlap >= size / 2:
            watched.add(index)
    return watched
