FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies (for geopandas stack if wheels need build tooling)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt flask gunicorn numpy

# Application code
COPY . .

# Flask app entrypoint: 3_VISUALIZE/app.py -> app:app
WORKDIR /app/3_VISUALIZE
CMD ["gunicorn", "-b", "0.0.0.0:8000", "app:app", "--workers=2", "--threads=4", "--timeout=120"]
