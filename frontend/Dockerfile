# syntax=docker/dockerfile:1
# Build context is the repo root (needs frontend/ and infra/nginx/).
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
# Optional error tracking for the browser (public DSN, baked into the bundle).
ARG VITE_SENTRY_DSN=""
ARG VITE_SENTRY_ENVIRONMENT=""
ARG GIT_SHA=""
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN VITE_SENTRY_ENVIRONMENT=$VITE_SENTRY_ENVIRONMENT VITE_RELEASE=$GIT_SHA
RUN npm run build

FROM nginx:1.30-alpine
# Pick up Alpine security fixes released after the base image was built (Trivy gates this in CI).
RUN apk upgrade --no-cache
# Content-Security-Policy origins, filled into the template at start (override per environment):
#   CSP_MEDIA_ORIGINS  the CDN, e.g. https://media.example.com
#   CSP_UPLOAD_ORIGINS where browsers PUT uploads, e.g. https://<bucket>.s3.<region>.amazonaws.com
#   CSP_CONNECT_EXTRA  anything else the app calls, e.g. the Sentry ingest host
# TRUSTED_PROXY_CIDR: where the load balancer connects from (VPC CIDR in AWS); its X-Forwarded-For is trusted.
ENV CSP_MEDIA_ORIGINS="" CSP_UPLOAD_ORIGINS="" CSP_CONNECT_EXTRA="" TRUSTED_PROXY_CIDR="127.0.0.1/32"
COPY infra/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY infra/nginx/proxy_django.conf infra/nginx/security_headers.conf /etc/nginx/
RUN mkdir -p /etc/nginx/extra && rm -f /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
