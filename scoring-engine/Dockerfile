FROM python:3.11-slim

WORKDIR /app

# Install system deps needed by psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create model and data directories
RUN mkdir -p model data

# Expose port
EXPOSE 8000

# Entrypoint: run startup checks (DB init + model training), then launch app
CMD ["sh", "-c", "python -m app.startup && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
