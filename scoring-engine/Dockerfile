FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Copy trained model and required data (Bake into production image)
COPY model/ ./model/
COPY data/ ./data/
# Expose port
EXPOSE 8000

# Run with 4 Uvicorn workers (tune to 2×CPU+1)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
