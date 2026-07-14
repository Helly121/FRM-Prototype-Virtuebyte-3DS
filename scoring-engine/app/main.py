"""
main.py — FastAPI Scoring Engine application.

Startup:
  - Load Isolation Forest model from model/isolation_forest.pkl
  - Initialise PostgreSQL connection pool (graceful fallback)

Per-request endpoint: POST /internal/score
  - Fetch profile from PostgreSQL (cold-start if missing)
  - Compute 40-dim surprise vector
  - Run IF inference
  - Build deviation report
  - Fire background tasks (profile update + audit log)
"""

import os
import json
import time
import logging

import numpy as np
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import pathlib

from .schemas import AReqPayload, DeviationReport
from .features import extract_and_score
from .profile import new_cold_profile, update_profile
from .report import build_report

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_PATH = os.getenv("MODEL_PATH", "model/isolation_forest.pkl")
PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/anomaly_db")

logger = logging.getLogger("scoring-engine")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# Global state — set during startup
IF_MODEL = None
pg_pool = None


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global IF_MODEL, pg_pool

    # --- Load Isolation Forest model ---
    try:
        import joblib
        IF_MODEL = joblib.load(MODEL_PATH)
        logger.info(f"Loaded IF model from {MODEL_PATH}")
    except FileNotFoundError:
        logger.warning(
            f"IF model not found at {MODEL_PATH}. "
            "Scoring will use weighted sum only (no ensemble signal)."
        )
        IF_MODEL = None
    except Exception as e:
        logger.error(f"Error loading IF model: {e}")
        IF_MODEL = None



    # --- PostgreSQL connection pool ---
    try:
        import asyncpg
        pg_pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=2, max_size=10)
        logger.info("PostgreSQL connected")
    except Exception as e:
        logger.warning(f"PostgreSQL unavailable ({e}). Audit logging disabled.")
        pg_pool = None

    yield

    # Shutdown
    if pg_pool:
        await pg_pool.close()
    logger.info("Scoring engine shutdown complete")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="3DS Anomaly Detection MVP - Scoring Engine",
    version="1.0.0",
    description="""
### Real-Time Anomaly Scoring for EMV 3-D Secure Transactions

This API receives raw Authentication Request (AReq) payloads and scores them in real-time.
- **Profiles**: Automatically builds and retrieves historical behavioral profiles for every card (`card_id_hash`).
- **Features**: Computes 40-dimensional Surprise Vectors, measuring the statistical deviation of the current transaction against the card's history.
- **Scoring**: Uses an offline-trained **Isolation Forest** model to detect complex, multi-attribute fraud (e.g. slight device change + location shift + new app package).
- **Audit**: All transactions and their full deviation reports are stored in PostgreSQL for auditing.
""",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory profile cache (fallback when PostgreSQL is unavailable)
_profile_cache: dict = {}


# ---------------------------------------------------------------------------
# Profile I/O
# ---------------------------------------------------------------------------

async def get_profile(card_id_hash: str) -> dict:
    """Fetch profile from PostgreSQL or in-memory cache."""

    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM synthetic_profiles WHERE card_id_hash = $1",
                    card_id_hash
                )
                if row:
                    data = row["profile_data"]
                    return json.loads(data) if isinstance(data, str) else data
        except Exception as e:
            logger.error(f"PostgreSQL GET profile error: {e}")

    # Fallback to in-memory cache
    if card_id_hash in _profile_cache:
        return _profile_cache[card_id_hash]

    return None


async def save_profile(card_id_hash: str, profile: dict):
    """Save profile to PostgreSQL and in-memory cache."""

    if pg_pool:
        try:
            profile_json = json.dumps(profile)
            txn_count = profile.get("_meta", {}).get("transaction_count", 0)
            confidence = profile.get("_meta", {}).get("profile_confidence", 0.0)
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO synthetic_profiles (card_id_hash, profile_data, txn_count, confidence)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (card_id_hash) DO UPDATE SET
                        profile_data = EXCLUDED.profile_data,
                        txn_count = EXCLUDED.txn_count,
                        confidence = EXCLUDED.confidence
                    """,
                    card_id_hash, profile_json, txn_count, confidence
                )
        except Exception as e:
            logger.error(f"PostgreSQL SAVE profile error: {e}")

    # Always update in-memory cache
    _profile_cache[card_id_hash] = profile


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

async def write_audit(report: DeviationReport):
    """Write scored transaction to PostgreSQL audit log."""
    if not pg_pool:
        return

    try:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO scored_transactions
                    (txn_id, card_id_hash, deviation_tier, total_deviation,
                     if_score, profile_confidence, channel,
                     contributing_factors, full_report)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (txn_id) DO NOTHING
                """,
                report.transaction_id,
                report.card_id,
                report.deviation_tier,
                report.total_deviation,
                report.if_score,
                report.profile_confidence,
                report.channel,
                json.dumps([f.model_dump() for f in report.contributing_factors]),
                json.dumps(report.model_dump()),
            )
    except Exception as e:
        logger.error(f"Audit log write error: {e}")


# ---------------------------------------------------------------------------
# Background Tasks
# ---------------------------------------------------------------------------

async def background_update_profile(card_id_hash: str,
                                     payload_dict: dict,
                                     old_profile: dict):
    """Background task: update and save profile after response is sent."""
    try:
        updated = update_profile(old_profile, payload_dict)
        await save_profile(card_id_hash, updated)
        logger.debug(f"Profile updated for {card_id_hash[:12]}...")
    except Exception as e:
        logger.error(f"Profile update error: {e}")


async def background_write_audit(report: DeviationReport):
    """Background task: write audit log after response is sent."""
    await write_audit(report)


# ---------------------------------------------------------------------------
# Scoring Endpoint
# ---------------------------------------------------------------------------

@app.post(
    "/internal/score", 
    response_model=DeviationReport,
    summary="Evaluate an AReq payload for Anomalies",
    description="""
Receives a JSON payload representing a 3DS transaction. 
The engine will:
1. Identify the card and fetch its historical behavioral profile from PostgreSQL.
2. Compare the payload to the profile and compute a mathematical "surprise vector".
3. Evaluate the transaction using the Isolation Forest ML model.
4. Return a `DeviationReport` indicating the Risk Tier (`LOW`, `MEDIUM`, `HIGH`) and detailed explanations for any anomalies found.
    """
)
async def score(payload: AReqPayload, background_tasks: BackgroundTasks):
    """
    Main scoring endpoint. Called by the Node.js API Gateway.

    Pipeline:
      1. Fetch profile from PostgreSQL (cold-start if missing)
      2. Extract features → 40-dim surprise vector
      3. IF inference (if model loaded)
      4. Build deviation report
      5. Fire background tasks (profile update + audit log)
      6. Return report
    """
    scoring_start_ms = time.time() * 1000
    card_id_hash = payload.card_id_hash
    payload_dict = payload.model_dump()

    # 1. Fetch or create profile
    profile = await get_profile(card_id_hash)
    if profile is None:
        profile = new_cold_profile(card_id_hash)
        logger.info(f"Cold-start profile for {card_id_hash[:12]}...")

    # 2. Feature extraction → 40-dim surprise vector
    surprise_vector, contributions, cross_field_scores = extract_and_score(
        payload_dict, profile
    )

    # 3. Isolation Forest inference
    if IF_MODEL is not None:
        try:
            if_score = float(
                IF_MODEL.decision_function([surprise_vector])[0]
            )
        except Exception as e:
            logger.error(f"IF inference error: {e}")
            if_score = 0.0
    else:
        if_score = 0.0  # Neutral when model not loaded

    # 4. Build report
    report = build_report(
        payload_dict,
        surprise_vector,
        contributions,
        cross_field_scores,
        if_score,
        profile,
        scoring_start_ms,
    )

    # 5. Fire background tasks
    if not payload.simulate_only:
        background_tasks.add_task(
            background_update_profile,
            card_id_hash,
            payload_dict,
            profile,
        )
    background_tasks.add_task(background_write_audit, report)

    return report


# ---------------------------------------------------------------------------
# Audit API
# ---------------------------------------------------------------------------

@app.get("/internal/audit", summary="Fetch recent scored transactions")
async def get_audit_log(limit: int = 50):
    """Fetch the latest transactions from the PostgreSQL audit log."""
    if not pg_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    try:
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT txn_id, card_id_hash, deviation_tier, total_deviation,
                       if_score, channel, scored_at
                FROM scored_transactions
                ORDER BY scored_at DESC
                LIMIT $1
                """,
                limit
            )
            # asyncpg Records can be converted to dicts directly
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Audit log fetch error: {e}")
        raise HTTPException(status_code=500, detail="Database query failed")

# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model_loaded": IF_MODEL is not None,
        "postgres_connected": pg_pool is not None,
    }


# ---------------------------------------------------------------------------
# Static Web UI
# ---------------------------------------------------------------------------

# Mount the static directory to serve the frontend UI
static_dir = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def serve_ui():
    """Serve the Presentation Dashboard UI."""
    return FileResponse(str(static_dir / "index.html"))
