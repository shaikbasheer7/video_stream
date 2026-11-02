from django.db import connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .health import run_checks


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Liveness: used by Docker healthchecks and the load balancer."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return Response({"status": "error", "database": "unavailable"}, status=503)
    return Response({"status": "ok"})


@api_view(["GET"])
@permission_classes([AllowAny])  # normal JWT auth, so staff can see error details
def ready(request):
    """Readiness: every dependency the API needs. Used by deploy smoke tests and monitoring."""
    checks = run_checks()
    healthy = all(c["ok"] for c in checks.values())
    # Error details only reach staff; the public just sees which component is down.
    if not (request.user and request.user.is_staff):
        checks = {name: {"ok": c["ok"]} for name, c in checks.items()}
    return Response({"status": "ok" if healthy else "degraded", "checks": checks}, status=200 if healthy else 503)
