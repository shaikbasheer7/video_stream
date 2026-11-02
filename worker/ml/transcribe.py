"""Speech to text with Whisper (CTranslate2 through faster-whisper, no PyTorch), and WebVTT subtitles."""

from dataclasses import dataclass
from functools import cache

from . import config

# Whisper makes up words over music and noise. Same signals its own reference code uses to discard such a segment.
MAX_NO_SPEECH_PROB = 0.6
MIN_AVG_LOGPROB = -1.0


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    language: str
    cues: tuple

    @property
    def text(self):
        return " ".join(cue.text for cue in self.cues)


@cache
def _model():
    from faster_whisper import WhisperModel

    return WhisperModel(
        config.WHISPER_MODEL,
        device="cpu",
        compute_type="int8",
        cpu_threads=config.CPU_THREADS,
        download_root=config.MODELS_DIR,
    )


def is_speech(no_speech_prob, avg_logprob):
    return not (no_speech_prob > MAX_NO_SPEECH_PROB and avg_logprob < MIN_AVG_LOGPROB)


def transcribe(audio_path):
    # The voice activity filter skips silence and music before Whisper sees them: faster, and fewer invented words.
    segments, info = _model().transcribe(str(audio_path), vad_filter=True, condition_on_previous_text=False)
    cues = tuple(
        Cue(segment.start, segment.end, segment.text.strip())
        for segment in segments  # a generator: the actual work happens here
        if segment.text.strip() and is_speech(segment.no_speech_prob, segment.avg_logprob)
    )
    return Transcript(info.language if cues else "", cues)


def _timestamp(seconds):
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _escape(text):
    # A cue's text is markup in WebVTT, and speech recognition output is untrusted. "-->" would end the cue early.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_webvtt(cues):
    blocks = [f"{_timestamp(c.start)} --> {_timestamp(c.end)}\n{_escape(c.text)}" for c in cues]
    return "\n\n".join(["WEBVTT", *blocks]) + "\n"
