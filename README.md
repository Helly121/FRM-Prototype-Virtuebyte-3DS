# 3DS Anomaly Detection MVP

This project is a high-performance **EMV 3-D Secure Anomaly Detection Scoring Engine** designed to evaluate incoming authentication requests against a cardholder's established behavioral profile in real-time. It focuses on the **SDK channel**, scoring 50 vital fields across five 3DS parameter categories to generate a comprehensive risk deviation report.

## Core Features & Methodology

- **50 Vital Fields Analysis**: Evaluates 50 distinct SDK payload fields spanning Transaction Details, Requestor Details, Merchant Details, and Device Details.
- **Categorical Surprise Scoring**: Uses Laplace-smoothed self-information, Z-scores, and temporal histogram density to compute a 40-dimensional surprise vector for every transaction.
- **Cross-Field Consistency Checks**: Validates logical coherence across fields, such as detecting clock skew, Platform ↔ OS Name mismatches, and GPS vs. billing centroid haversine distances.
- **Machine Learning Ensemble**: Feeds the 40-dimensional surprise vector into a pre-trained **Isolation Forest** model to detect complex, multi-dimensional anomalies that simple linear weighting might miss.
- **Stateless & Async Architecture**: The FastAPI scoring engine is entirely stateless per request, fetching card profiles instantly from memory and offloading profile updates and PostgreSQL audit logs to background tasks to ensure sub-millisecond response latencies.

## Architecture

The system follows a lean microservices architecture powered by **Uvicorn** for high-performance ASGI serving, combining a real-time scoring engine with an offline Machine Learning pipeline and a robust PostgreSQL data tier.

```mermaid
flowchart TB
    DS["3DS Directory Server\nAReq payload"]

    subgraph SE["FastAPI Scoring Engine (Uvicorn)"]
        direction TB
        ST["Startup: load IF.pkl into RAM"]
        RF["Fetch Profile (card_profiles)"]
        FE["Feature Extraction\n(50 fields)"]
        BL["Check global_blocklist"]
        SC["Compute 40-dim Surprise Vector"]
        IF["Isolation Forest Inference"]
        WS["Weighted Sum → TotalDeviation"]
        EX["Explanation Generator"]
        BG["Background Tasks\n• update_profile()\n• write_audit()"]
    end

    subgraph OP["Offline Data Pipeline (run_pipeline.py)"]
        direction TB
        GD["1. generate_dataset.py\n(100k synthetic Txns)"]
        BP["2. bootstrap_profiles.py\n(Builds ML memory)"]
        CV["3. compute_vectors.py\n(Calculates Surprises)"]
        TM["4. train_model.py\n(Trains IF.pkl)"]
    end

    subgraph DB["PostgreSQL Database"]
        direction TB
        CP[("card_profiles\n(JSONB ML Memory)")]
        STX[("scored_transactions\n(Audit Log)")]
        GB[("global_blocklist\n(Cross-Card Fraud)")]
        OF[("outcome_feedback\n(Chargebacks/Analyst)")]
        PRL[("profile_reinforcement_log")]
    end

    DS --> SE
    SE --> RF
    RF --> FE
    FE --> BL
    BL --> SC
    SC --> IF
    SC --> WS
    IF --> EX
    WS --> EX
    EX --> RESP["DeviationReport JSON"]
    RESP --> BG
    
    BG --> |"Upsert JSONB"| CP
    BG --> |"Insert Audit"| STX
    
    OP --> CP
    
    OF -.-> |"Feedback API"| GB
    OF -.-> |"Feedback API"| PRL
    BL -.-> |"Reads"| GB
    RF -.-> |"Reads"| CP
```

1. **API Gateway (Node.js/Express)**: Handles payload validation, authentication, rate limiting, and hashing of sensitive fields (e.g., PANs) before routing to the scoring engine.
2. **Scoring Engine (Python/FastAPI via Uvicorn)**: The core intelligence. It extracts features, checks the global fraud blocklist, calculates Total Deviation, runs the Isolation Forest inference, and determines the final risk tier (`LOW`, `MEDIUM`, `HIGH`). It handles database writes asynchronously via Background Tasks to guarantee sub-millisecond response latencies.
3. **Offline Pipeline**: A sequential Python pipeline that generates synthetic transaction data, bootstraps the JSONB profile memory, computes surprise vectors, and trains the `isolation_forest.pkl` model.
4. **Database (PostgreSQL)**: Serves as a persistent store for historical transaction profiles (`card_profiles`), global fraud indicators (`global_blocklist`), and an immutable audit log (`scored_transactions`).
5. **Presentation Dashboard**: A beautifully designed, interactive Vanilla JS + HTML web interface directly served by the FastAPI engine, allowing you to test and visualize "Normal" vs. "Anomalous" transactions in real-time.

## The Scoring Pipeline

1. **Profile Fetching**: Retrieve the cardholder's established behavioral baseline.
2. **Feature Extraction**: Compare the incoming 50 fields against historical patterns.
3. **Surprise Vector**: Generate 40 individual deviation scores.
4. **Weighted Sum & IF Model**: Calculate a weighted `TotalDeviation` and an Isolation Forest decision score.
5. **Tier Assignment**: Assign `HIGH`, `MEDIUM`, or `LOW` risk.
6. **Explanation Generation**: Filter contributions >2% and map them to human-readable explanations.
7. **Background Updates**: Asynchronously update the profile and audit log.

---

## Running the Project

You must initialize the database, run the offline pipeline (to generate data and train the ML model), and start the FastAPI server. Choose the method that best fits your environment:

### Option 1: Using Docker (Highly Recommended)
The most reliable, production-accurate way to run this MVP is using Docker for the PostgreSQL database. This ensures a clean environment and avoids system-wide installations.

1. **Start the Database via Docker Compose**:
   Open a terminal in the project root (`d:\FRM Anamoly MVP`) and run:
   ```bash
   docker compose up postgres -d
   ```
   *This spins up a dedicated PostgreSQL 16 container on port 5432 and initializes the V4 schema tables automatically in the background.*

2. **Set the Database Connection String**:
   In your terminal (e.g., PowerShell), export the environment variable so the Python scripts know how to reach the Docker database:
   ```powershell
   $env:PG_DSN="postgresql://postgres:postgres@127.0.0.1:5432/anomaly_db"
   ```

3. **Run the Full Offline Pipeline**:
   You must populate the empty database with the historical dataset, bootstrap the user profiles, and train the Machine Learning model. (Run this in the same terminal where you set `PG_DSN`):
   ```bash
   python scripts/run_pipeline.py
   ```
   *(This sequentially runs dataset generation, profile bootstrapping, surprise vector computation, and model training. It will say "Using existing database from PG_DSN" at the top).*

4. **Start the FastAPI Scoring Engine**:
   Once the pipeline finishes, start the Uvicorn server:
   ```bash
   python -m uvicorn scoring-engine.app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

---

### Option 2: Fully Local (No Docker)
If you cannot use Docker, we have provided a Python script that uses `pgserver` to spin up a temporary, embedded PostgreSQL instance without requiring admin rights or a system-wide installation.

1. **Start the Embedded PostgreSQL Server**:
   Open a terminal and run:
   ```bash
   python start_db.py
   ```
   *Keep this terminal window OPEN! Closing it will shut down the database.* The script will print out a connection string that looks something like `postgresql://postgres:@127.0.0.1:XXXXX/postgres`.

2. **Open a NEW Terminal and Set the Database URL**:
   Copy the `PG_DSN` provided by the `start_db.py` terminal and set it in your new PowerShell window:
   ```powershell
   $env:PG_DSN="postgresql://postgres:@127.0.0.1:XXXXX/postgres"
   ```

3. **Run the Full Offline Pipeline**:
   ```bash
   python scripts/run_pipeline.py
   ```

4. **Start the FastAPI Scoring Engine**:
   ```bash
   python -m uvicorn scoring-engine.app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

## Presentation Dashboard

Once the FastAPI server is running, navigate to `http://127.0.0.1:8000/` in your browser to access the **3DS Risk Intelligence Console**, a highly polished, interactive dashboard with three core views:

1. **Transaction Simulator**: Test exact JSON payloads against the scoring engine. You can click **"Normal Txn"** to see how a typical transaction perfectly matches a card's baseline, yielding a `LOW` risk tier, or **"Anomalous Txn"** to simulate an integrity threat (e.g., unknown app package, massive purchase amount, mismatched OS) triggering a `HIGH` risk tier. *Scoring transactions here will dynamically update the historical profile baseline in real-time!*
2. **Dynamic Dataset Load Simulator**: Trigger a concurrent simulation of 50 historical transactions instantly. The simulator splits traffic into Normal (80%), Suspicious (15%), and Abnormal (5%) buckets, scoring them live. The results table dynamically extracts and displays the **Top Risk Factors** for each transaction. You can hover and click on any generated row to open an interactive modal revealing the full raw payload and the precise mathematical factors that drove the engine's tier decision.
3. **Profile Explorer**: A direct view into the PostgreSQL `card_profiles` table. View the exact learning state of each card hash, including Profile Maturity (transaction count and model confidence percentage), Trust State (Normal, Probation, or Elevated Scrutiny), and a dynamically updating `last_updated` timestamp. You can click on any profile to see the raw multi-dimensional mathematical frequency dictionaries the engine is building under the hood.
