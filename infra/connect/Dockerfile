# Kafka Connect with the S3 sink (Confluent Community License: free to use, but not open source).
FROM confluentinc/cp-kafka-connect:7.9.2
ENV CONNECT_PLUGIN_PATH=/usr/share/confluent-hub-components
RUN confluent-hub install --no-prompt confluentinc/kafka-connect-s3:10.6.7
COPY lake-sink.json start.sh /etc/lake/
CMD ["sh", "/etc/lake/start.sh"]
HEALTHCHECK --interval=15s --timeout=5s --retries=8 --start-period=90s \
  CMD curl -fsS localhost:8083/connectors/lake-sink/status | grep -q '"state":"RUNNING"' || exit 1
