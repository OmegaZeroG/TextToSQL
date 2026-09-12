FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY data ./data

# Bake the seeded demo database into the image at build time so the
# container is self-contained and doesn't depend on persistent disk.
RUN python data/seed.py

ENV DB_PATH=/app/data/sample.duckdb
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
