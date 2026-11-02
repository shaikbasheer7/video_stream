# syntax=docker/dockerfile:1
# Local data stack. Build context: data/
FROM apache/airflow:3.1.8
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY airflow/dags /opt/airflow/dags
COPY pipeline /opt/airflow/src/pipeline
ENV PYTHONPATH=/opt/airflow/src FASTEMBED_CACHE_PATH=/opt/airflow/models
# Download the embedding model at build time, so nightly runs don't depend on Hugging Face being reachable.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')"
