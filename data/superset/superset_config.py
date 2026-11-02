import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = os.environ["SUPERSET_METADATA_DB_URL"]
# Dashboards only read: nobody needs to run arbitrary schema changes through SQL Lab.
PREVENT_UNSAFE_DB_CONNECTIONS = True
ROW_LIMIT = 5000
