# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS deps
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# DB-IP's free country database, CC BY 4.0: pages using its results must link to db-ip.com. To update: pick a newer
# version of @ip-location-db/dbip-country-mmdb on npm and replace the version and checksum.
FROM base AS geo
ADD --checksum=sha256:5340f28d08f4e666473e0c5dc1c40d9db457ad00603d1f725fb4d8621c624239 \
    https://registry.npmjs.org/@ip-location-db/dbip-country-mmdb/-/dbip-country-mmdb-2.3.2026060120.tgz /tmp/geo.tgz
RUN mkdir /geo && tar -xzf /tmp/geo.tgz -C /geo --strip-components=1 package/dbip-country.mmdb package/DBIP-LICENSE

FROM base AS runtime
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /var/cdn-keys && chown app:app /var/cdn-keys
COPY --from=deps /install /usr/local
COPY --from=geo /geo /opt/geo
COPY . .
# Collect with the production storage (hashed names + manifest); dev settings would skip the manifest and
# every admin page would 500 in production. The key exists only for this build step.
RUN chmod +x docker-entrypoint.sh \
    && DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_SECRET_KEY=build-only-collectstatic-key \
       python manage.py collectstatic --noinput
USER app
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
# No gunicorn access log: nginx writes one JSON line per request with the same request id.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
