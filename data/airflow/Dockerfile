# syntax=docker/dockerfile:1
# Local data stack. Build context: data/
FROM apache/airflow:3.1.8
USER root
# Java for Spark.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/spark-jars /opt/spark-checkpoints \
    && chown airflow /opt/spark-jars /opt/spark-checkpoints
USER airflow
COPY requirements.txt requirements-spark.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-spark.txt
ENV FASTEMBED_CACHE_PATH=/opt/airflow/models SPARK_JARS_DIR=/opt/spark-jars
# Download the embedding model at build time, so nightly runs don't depend on Hugging Face being reachable.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')"
# Spark's connectors for S3 and Kafka, at the versions matching this PySpark, also fetched at build time.
COPY airflow/fetch_spark_jars.py /tmp/fetch_spark_jars.py
RUN python /tmp/fetch_spark_jars.py /opt/spark-jars
# Last, so changing the code doesn't download everything above again.
COPY airflow/dags /opt/airflow/dags
COPY pipeline /opt/airflow/src/pipeline
ENV PYTHONPATH=/opt/airflow/src
