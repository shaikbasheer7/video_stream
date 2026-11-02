# syntax=docker/dockerfile:1
# Local data stack. Build context: data/
FROM apache/superset:6.0.0
USER root
RUN . /app/.venv/bin/activate && uv pip install --no-cache psycopg2-binary==2.9.10
COPY superset/superset_config.py /app/pythonpath/superset_config.py
COPY superset/build_assets.py superset/start.sh /app/streaming/
RUN chmod +x /app/streaming/start.sh
USER superset
HEALTHCHECK --interval=15s --timeout=5s --retries=20 --start-period=90s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8088/health', timeout=3)"
CMD ["/app/streaming/start.sh"]
