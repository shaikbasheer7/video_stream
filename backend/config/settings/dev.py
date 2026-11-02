from .base import *  # noqa: F403
from .base import env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = SECRET_KEY or "dev-insecure-key-only-for-local-development-change-me"  # noqa: F405
SIMPLE_JWT["SIGNING_KEY"] = SECRET_KEY  # noqa: F405
REFRESH_COOKIE_SECURE = env_bool("REFRESH_COOKIE_SECURE", False)
CDN_COOKIE_SECURE = env_bool("CDN_COOKIE_SECURE", False)
