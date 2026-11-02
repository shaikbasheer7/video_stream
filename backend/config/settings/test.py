from .dev import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {"auth": "1000/min", "upload": "1000/min", "events": "1000/min"}  # noqa: F405
