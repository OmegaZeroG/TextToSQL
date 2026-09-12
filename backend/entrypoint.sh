#!/bin/sh
set -e

python - <<'PYEOF'
import os
import sys
import time

from sqlalchemy import create_engine

url = os.environ.get("DATABASE_URL")
engine = create_engine(url)

for attempt in range(30):
    try:
        engine.connect().close()
        break
    except Exception:
        time.sleep(1)
else:
    sys.exit("Could not reach the database after 30s")
PYEOF

python data/seed.py

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
