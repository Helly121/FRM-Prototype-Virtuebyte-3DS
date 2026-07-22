# 3DS Anomaly Detection MVP

This project is a high-performance **EMV 3-D Secure Anomaly Detection Scoring Engine** designed to evaluate incoming authentication requests against a cardholder's established behavioral profile in real-time. It focuses on the **SDK channel**, scoring 50 vital fields across five 3DS parameter categories to generate a comprehensive risk deviation report.

## Core Features & Methodology

- **50 Vital Fields Analysis**: Evaluates 50 distinct SDK payload fields spanning Transaction Details, Requestor Details, Merchant Details, and Device Details.
- **Categorical Surprise Scoring**: Uses Laplace-smoothed self-information, Z-scores, and temporal histogram density to compute a 40-dimensional surprise vector for every transaction.
- **Cross-Field Consistency Checks**: Validates logical coherence across fields, such as detecting clock skew, Platform ↔ OS Name mismatches, and GPS vs. billing centroid haversine distances.
- **Machine Learning Ensemble**: Feeds the 40-dimensional surprise vector into a pre-trained **Isolation Forest** model to detect complex, multi-dimensional anomalies that simple linear weighting might miss.
- **Stateless & Async Architecture**: The FastAPI scoring engine is entirely stateless per request, fetching card profiles instantly from memory and offloading profile updates and PostgreSQL audit logs to background tasks to ensure sub-millisecond response latencies.

## Architecture

The system follows a lean microservices architecture powered by **Uvicorn** for high-performance ASGI serving:

```mermaid
flowchart TB
    DS["3DS Directory Server\nAReq payload"]

    subgraph GW["API Gateway — Node.js / Express"]
        V["JSON Schema Validation"]
        H["SHA-256 acctNumber hash"]
        RL["Rate Limiting"]
        P["Proxy to FastAPI"]
    end

    subgraph SE["Scoring Engine — Python / FastAPI (Uvicorn)"]
        direction TB
        ST["Startup: load IF.pkl into RAM\nopen Postgres pools"]
        RF["Fetch profile from DB/Cache"]
        FE2["Feature Extraction\n50 fields → preprocessing"]
        SC2["Compute 40-dim Surprise Vector\n(all §6 formulas)"]
        IF2["Isolation Forest inference\nIF.pkl already in RAM"]
        WS["Weighted sum → TotalDeviation"]
        EX["Explanation Generator\ntemplate-fill, rank, tier"]
        BG["BackgroundTasks (post-response)\n• update_profile\n• write_audit → Postgres"]
    end

    PG[("PostgreSQL\nProfile & Audit Log")]

    DS --> GW
    GW --> SE
    SE --> RF --> PG
    RF --> FE2 --> SC2
    SC2 --> IF2
    SC2 --> WS
    IF2 --> EX
    WS --> EX
    EX --> RESP["DeviationReport JSON"]
    RESP --> BG
    BG --> PG
```

1. **API Gateway (Node.js/Express)**: Handles payload validation, authentication, rate limiting, and hashing of sensitive fields (e.g., PANs) before routing to the scoring engine.
2. **Scoring Engine (Python/FastAPI via Uvicorn)**: The core intelligence. It extracts features, calculates Total Deviation using expert-set static weights, runs the Isolation Forest inference, and determines the final risk tier (`LOW`, `MEDIUM`, `HIGH`).
3. **Database (PostgreSQL)**: Serves as a persistent store for historical transaction profiles (via the `synthetic_profiles` table) and an audit log for all scored transactions.
4. **Presentation Dashboard**: A beautifully designed, interactive Vanilla JS + HTML web interface directly served by the FastAPI engine, allowing you to test and visualize "Normal" vs. "Anomalous" transactions in real-time.

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

The easiest way to start the entire stack is via Docker Compose:
```bash
docker-compose up --build
```
This single command spins up PostgreSQL, the Node.js API Gateway, and the FastAPI Scoring Engine.

### Running Locally (Without Docker)
If you prefer to run the components natively on your machine, we have provided an automated pipeline to handle database creation, dataset generation, and model training:

1. **Start the Embedded PostgreSQL Server**:
   ```bash
   python start_db.py
   ```
   *Keep this terminal window open! It runs a localized instance of PostgreSQL using `pgserver` so you don't need system-wide installations.*

2. **Open a NEW Terminal and Set the Database URL**:
   For example, in PowerShell:
   ```powershell
   $env:PG_DSN="postgresql://postgres:@127.0.0.1:5432/postgres"
   ```

3. **Run the Full Offline Pipeline**:
   If this is your first time starting the project, you need to generate the synthetic dataset, bootstrap the profiles, and train the Machine Learning model:
   ```bash
   python scripts/run_pipeline.py
   ```
   *(This sequentially runs the dataset generation, profile bootstrapping, surprise vector computation, and model training.)*

4. **Start the FastAPI Scoring Engine**:
   ```bash
   python -m uvicorn scoring-engine.app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

## Presentation Dashboard

Once the FastAPI server is running, navigate to `http://127.0.0.1:8000/` in your browser to access the **3DS Risk Intelligence Console**, a highly polished, interactive dashboard with three core views:

1. **Transaction Simulator**: Test exact JSON payloads against the scoring engine. You can click **"Normal Txn"** to see how a typical transaction perfectly matches a card's baseline, yielding a `LOW` risk tier, or **"Anomalous Txn"** to simulate an integrity threat (e.g., unknown app package, massive purchase amount, mismatched OS) triggering a `HIGH` risk tier. *Scoring transactions here will dynamically update the historical profile baseline in real-time!*
2. **Dynamic Dataset Load Simulator**: Trigger a concurrent simulation of 50 synthetic transactions instantly. The simulator splits traffic into Normal (80%), Suspicious (15%), and Abnormal (5%) buckets, scoring them live. You can click on any generated row to open an interactive modal revealing the full raw payload and the precise mathematical factors that drove the engine's tier decision.
3. **Profile Explorer**: A direct view into the PostgreSQL `synthetic_profiles` table. View the exact learning state of each card hash, including Profile Maturity (transaction count and model confidence percentage), Trust State (Normal, Probation, or Elevated Scrutiny), and a dynamically updating `last_updated` timestamp. You can click on any profile to see the raw multi-dimensional mathematical frequency dictionaries the engine is building under the hood.
