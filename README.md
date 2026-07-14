# 3DS Anomaly Detection MVP

This project is an EMV 3-D Secure Anomaly Detection Scoring Engine prototype. It leverages real-time feature engineering, categorical surprise metrics, cross-field checks, and an Isolation Forest model to detect anomalous transactions.

## Architecture
- **Scoring Engine**: FastAPI application providing real-time anomaly scores.
- **API Gateway**: Node.js/Express gateway.
- **Database**: PostgreSQL for storing historical transaction profiles and anomaly features.
- **Models**: Pre-trained Isolation Forest model for ensemble scoring.
- **Dashboard**: Integrated web dashboard for presentation and real-time testing.

## Running the Project
The easiest way to start the system is via Docker Compose:
```bash
docker-compose up --build
```
This will start PostgreSQL, the API Gateway, and the FastAPI Scoring Engine. 

If running locally (without Docker):
1. Start your local PostgreSQL server (e.g., using `pg_ctl`, Windows Services, or the `pgserver` Python package if you prefer).
2. Set the `PG_DSN` environment variable to point to your database. For example (in PowerShell):
   ```powershell
   $env:PG_DSN="postgresql://postgres:password@127.0.0.1:5432/postgres"
   ```
3. Ensure you have run `generate_dataset.py` to seed profiles:
   ```bash
   python scripts/generate_dataset.py
   ```
4. Start the FastAPI server: 
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

## Presentation Dashboard
Once running, navigate to `http://127.0.0.1:8000/` to access the presentation-ready UI dashboard for testing Normal vs Anomalous transactions.
