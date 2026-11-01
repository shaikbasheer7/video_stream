class EncodeError(Exception):
    """Something went wrong while encoding. Retried by default."""

    retryable = True


class InvalidSource(EncodeError):
    """The upload itself is unusable (not a video, too long...). Retrying won't help."""

    retryable = False
