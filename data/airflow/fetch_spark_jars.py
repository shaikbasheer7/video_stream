"""Download Spark's S3 and Kafka connectors and their dependencies, with Spark's own resolver. Runs at image build."""

import glob
import os
import shutil
import sys

from pyspark.sql import SparkSession

SPARK = "4.0.5"
HADOOP = "3.4.1"  # the version this PySpark bundles
PACKAGES = [f"org.apache.spark:spark-sql-kafka-0-10_2.13:{SPARK}", f"org.apache.hadoop:hadoop-aws:{HADOOP}"]

target = sys.argv[1]
spark = SparkSession.builder.master("local[1]").config("spark.jars.packages", ",".join(PACKAGES)).getOrCreate()
spark.stop()
jars = glob.glob(os.path.expanduser("~/.ivy2*/jars/*.jar"))
if not jars:
    sys.exit("Spark downloaded no jars")
for jar in jars:
    shutil.move(jar, target)
for cache in glob.glob(os.path.expanduser("~/.ivy2*")):
    shutil.rmtree(cache)  # a second copy of everything just moved
print(f"{len(jars)} jars in {target}")
