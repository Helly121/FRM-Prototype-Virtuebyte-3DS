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

from .schemas import AReqPayload, DeviationReport, FeedbackPayload
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
redis_client = None

# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global IF_MODEL, pg_pool, redis_client

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

    # --- Redis connection ---
    try:
        import redis.asyncio as redis
        redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}). Falling back to in-memory cache.")
        redis_client = None

    yield

    # Shutdown
    if pg_pool:
        await pg_pool.close()
    if redis_client:
        await redis_client.aclose()
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

async def get_profile(card_id_hash: str) -> tuple[dict | None, int]:
    """
    Fetch profile from Redis, falling back to PostgreSQL.
    Returns (profile_dict, expected_version).
    If not found anywhere, returns (None, 0).
    """
    # 1. Try Redis cache
    if redis_client:
        try:
            cached = await redis_client.get(f"profile:{card_id_hash}")
            if cached:
                data = json.loads(cached)
                # We store { "profile": {...}, "version": int } in Redis
                return data["profile"], data["version"]
        except Exception as e:
            logger.error(f"Redis GET error: {e}")

    # 2. Cache miss -> Try PostgreSQL
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile, version FROM card_profiles WHERE card_id_hash = $1",
                    card_id_hash
                )
                if row:
                    data = row["profile"]
                    profile = json.loads(data) if isinstance(data, str) else data
                    version = row["version"]
                    
                    # Repopulate Redis cache
                    if redis_client:
                        try:
                            await redis_client.setex(
                                f"profile:{card_id_hash}", 
                                86400, 
                                json.dumps({"profile": profile, "version": version})
                            )
                        except Exception:
                            pass
                            
                    return profile, version
        except Exception as e:
            logger.error(f"PostgreSQL GET profile error: {e}")

    # 3. Fallback to in-memory cache if DB completely unavailable
    if card_id_hash in _profile_cache:
        cached = _profile_cache[card_id_hash]
        return cached["profile"], cached["version"]

    return None, 0


async def save_profile(card_id_hash: str, profile: dict, expected_version: int) -> int:
    """
    Save profile to PostgreSQL with optimistic locking.
    Returns the new version number if successful, or raises an exception on conflict.
    """
    new_version = expected_version + 1
    
    if pg_pool:
        profile_json = json.dumps(profile)
        txn_count = profile.get("_meta", {}).get("transaction_count", 0)
        confidence = profile.get("_meta", {}).get("profile_confidence", 0.0)
        
        async with pg_pool.acquire() as conn:
            if expected_version == 0:
                result = await conn.execute(
                    """
                    INSERT INTO card_profiles (card_id_hash, profile, version, transaction_count, profile_confidence)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (card_id_hash) DO NOTHING
                    """,
                    card_id_hash, profile_json, new_version, txn_count, confidence
                )
                if result != "INSERT 0 1":
                    raise RuntimeError("Profile conflict: already exists")
            else:
                result = await conn.execute(
                    """
                    UPDATE card_profiles SET
                        profile = $1,
                        version = $2,
                        transaction_count = $3,
                        profile_confidence = $4,
                        updated_at = NOW()
                    WHERE card_id_hash = $5 AND version = $6
                    """,
                    profile_json, new_version, txn_count, confidence, card_id_hash, expected_version
                )
                if result != "UPDATE 1":
                    raise RuntimeError("Profile conflict: version mismatch")

    # Update caches
    if redis_client:
        try:
            await redis_client.setex(
                f"profile:{card_id_hash}", 
                86400, 
                json.dumps({"profile": profile, "version": new_version})
            )
        except Exception:
            pass
            
    _profile_cache[card_id_hash] = {"profile": profile, "version": new_version}
    return new_version


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
                                     old_profile: dict,
                                     expected_version: int,
                                     max_retries: int = 3):
    """Background task: update and save profile after response is sent."""
    current_profile = old_profile
    current_version = expected_version
    
    for attempt in range(max_retries):
        try:
            updated = update_profile(current_profile, payload_dict)
            await save_profile(card_id_hash, updated, current_version)
            logger.debug(f"Profile updated for {card_id_hash[:12]}...")
            return
        except RuntimeError as e:
            if "conflict" in str(e).lower() and attempt < max_retries - 1:
                logger.warning(f"Version conflict for {card_id_hash}. Retrying...")
                # Re-fetch latest from DB
                current_profile, current_version = await get_profile(card_id_hash)
                if not current_profile:
                    break
            else:
                logger.error(f"Profile update failed after {max_retries} attempts: {e}")
                return
        except Exception as e:
            logger.error(f"Profile update error: {e}")
            return


async def background_write_audit(report: DeviationReport):
    """Background task: write audit log after response is sent."""
    await write_audit(report)


# ---------------------------------------------------------------------------
# Scoring Endpoint
# ---------------------------------------------------------------------------

async def check_global_blocklist(payload_dict: dict) -> list:
    """Check payload against global blocklist in PostgreSQL/Redis."""
    hits = []
    if not pg_pool:
        return hits
        
    # We check fields that were identified as contributing factors in past fraud
    # For now, we hash all top-level string values from the payload to check.
    from .features import sha256_str
    
    check_values = []
    for k, v in payload_dict.items():
        if isinstance(v, str) and v:
            check_values.append(sha256_str(v))
            
    if not check_values:
        return hits
        
    try:
        async with pg_pool.acquire() as conn:
            # Check if any hashes exist in the blocklist
            rows = await conn.fetch(
                "SELECT field FROM global_blocklist WHERE value_hash = ANY($1::text[])",
                check_values
            )
            hits = [row["field"] for row in rows]
    except Exception as e:
        logger.error(f"Blocklist check error: {e}")
        
    return list(set(hits))


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
    profile, expected_version = await get_profile(card_id_hash)
    if profile is None:
        profile = new_cold_profile(card_id_hash)
        expected_version = 0
        logger.info(f"Cold-start profile for {card_id_hash[:12]}...")

    # 1.5. Check blocklist
    blocklist_hits = await check_global_blocklist(payload_dict)

    # 2. Feature extraction → 40-dim surprise vector
    surprise_vector, contributions, cross_field_scores = extract_and_score(
        payload_dict, profile, blocklist_hits
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
    if not payload.simulate_only and (report.deviation_tier == "LOW" or payload.force_profile_update):
        background_tasks.add_task(
            background_update_profile,
            card_id_hash,
            payload_dict,
            profile,
            expected_version,
        )
    # Always audit, regardless of simulate_only or tier
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

@app.get("/internal/db-explorer", summary="Fetch database profiles")
async def get_db_explorer(limit: int = 50, offset: int = 0, search: str | None = None):
    """Fetch raw profiles from PostgreSQL for database explorer."""
    if not pg_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    try:
        async with pg_pool.acquire() as conn:
            if search and search.strip():
                query = """
                SELECT card_id_hash, profile, created_at, updated_at, version
                FROM card_profiles
                WHERE card_id_hash ILIKE $1
                ORDER BY updated_at DESC
                LIMIT $2 OFFSET $3
                """
                rows = await conn.fetch(query, f"%{search.strip()}%", limit, offset)
            else:
                query = """
                SELECT card_id_hash, profile, created_at, updated_at, version
                FROM card_profiles
                ORDER BY updated_at DESC
                LIMIT $1 OFFSET $2
                """
                rows = await conn.fetch(query, limit, offset)
            
            import json
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d['profile'], str):
                    d['profile'] = json.loads(d['profile'])
                results.append(d)
            return results
    except Exception as e:
        logger.error(f"DB Explorer fetch error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch DB rows")

# ---------------------------------------------------------------------------
# Feedback API
# ---------------------------------------------------------------------------

async def background_process_feedback(payload: FeedbackPayload):
    """Process ground-truth feedback asynchronously."""
    if not pg_pool:
        return
        
    try:
        async with pg_pool.acquire() as conn:
            # 1. Fetch the scored transaction
            row = await conn.fetchrow(
                "SELECT card_id_hash, full_report FROM scored_transactions WHERE txn_id = $1",
                payload.txn_id
            )
            if not row:
                logger.warning(f"Feedback received for unknown txn_id: {payload.txn_id}")
                return
                
            card_id_hash = row["card_id_hash"]
            full_report_str = row["full_report"]
            report_dict = json.loads(full_report_str) if isinstance(full_report_str, str) else full_report_str
            
            # Update the transaction's outcome label
            await conn.execute(
                "UPDATE scored_transactions SET outcome_label = $1 WHERE txn_id = $2",
                payload.outcome, payload.txn_id
            )

        # 2. Fetch the profile
        profile, expected_version = await get_profile(card_id_hash)
        if not profile:
            logger.warning(f"Profile not found for feedback on card {card_id_hash}")
            return

        # 3. Apply Feedback Logic
        if payload.outcome == "confirmed_legit":
            # Reinforce Profile: Promote contributing anomaly vectors to "known" sets
            profile["_meta"]["trust_state"] = "normal"
            
            import time
            now_ts = time.time()
            for factor in report_dict.get("contributing_factors", []):
                dim = factor.get("dimension")
                
                # Use raw_observed if it exists, otherwise fall back to observed
                raw_obs = factor.get("raw_observed")
                obs = factor.get("observed")
                
                # The true underlying value we want to inject
                val = raw_obs if raw_obs is not None else obs
                
                if not dim or not val or val == "empty":
                    continue
                
                # Promote to known sets based on dimension (Using correct profile keys)
                if dim == "s_merchant_id":
                    profile.setdefault("merchant", {}).setdefault("known_merchant_ids", {})[val] = {"freq": 1, "last_seen": now_ts}
                elif dim == "s_acquirer_bin":
                    profile.setdefault("merchant", {}).setdefault("known_acquirer_bins", {})[val] = {"freq": 1, "last_seen": now_ts}
                elif dim == "s_ip_subnet":
                    profile.setdefault("device", {}).setdefault("known_ip_subnets", {})[val] = {"freq": 1, "last_seen": now_ts}
                elif dim == "s_device_model":
                    dfreq = profile.setdefault("device", {}).setdefault("device_model_freq", {})
                    dfreq[val] = dfreq.get(val, 0) + 10  # categorical frequency boost
                elif dim == "s_app_package":
                    profile.setdefault("device", {}).setdefault("known_app_packages", {})[val] = {"freq": 1, "last_seen": now_ts}
                elif dim == "s_platform":
                    pfreq = profile.setdefault("device", {}).setdefault("platform_freq", {})
                    pfreq[val] = pfreq.get(val, 0) + 10  # categorical frequency boost
                elif dim == "s_merchant_country":
                    cfreq = profile.setdefault("transaction", {}).setdefault("country_freq", {})
                    cfreq[val] = cfreq.get(val, 0) + 10  # categorical frequency boost
                elif dim == "s_mcc":
                    mfreq = profile.setdefault("transaction", {}).setdefault("mcc_freq", {})
                    mfreq[val] = mfreq.get(val, 0) + 10
                elif dim == "s_currency":
                    curfreq = profile.setdefault("transaction", {}).setdefault("currency_freq", {})
                    curfreq[val] = curfreq.get(val, 0) + 10
                elif dim == "s_os_name":
                    ofreq = profile.setdefault("device", {}).setdefault("os_name_freq", {})
                    ofreq[val] = ofreq.get(val, 0) + 10
                elif dim == "s_os_version":
                    ovfreq = profile.setdefault("device", {}).setdefault("os_version_freq", {})
                    ovfreq[val] = ovfreq.get(val, 0) + 10
                elif dim == "s_screen_res":
                    sfreq = profile.setdefault("device", {}).setdefault("screen_res_freq", {})
                    sfreq[val] = sfreq.get(val, 0) + 10
                elif dim == "s_amount":
                    import math
                    try:
                        amt = float(val)
                        profile.setdefault("transaction", {})["amount_ewma_log"] = math.log1p(max(amt, 0))
                        profile.setdefault("transaction", {})["amount_ewma_var"] = max(profile.get("transaction", {}).get("amount_ewma_var", 1.0), 0.5)
                    except ValueError:
                        pass
                elif dim == "s_temporal":
                    import re
                    m = re.search(r"hour=(\d+),\s*dow=(\d+)", val)
                    if m:
                        hour, dow = int(m.group(1)), int(m.group(2))
                        h_hist = profile.setdefault("transaction", {}).setdefault("hour_hist", [1.0/24]*24)
                        if len(h_hist) == 24:
                            h_hist[hour] += 0.5
                            s_sum = sum(h_hist)
                            profile["transaction"]["hour_hist"] = [x/s_sum for x in h_hist]
                        d_hist = profile.setdefault("transaction", {}).setdefault("dow_hist", [1.0/7]*7)
                        if len(d_hist) == 7:
                            d_hist[dow] += 0.5
                            s_sum = sum(d_hist)
                            profile["transaction"]["dow_hist"] = [x/s_sum for x in d_hist]


            if pg_pool:
                async with pg_pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO profile_reinforcement_log (card_id_hash, reason) VALUES ($1, $2)",
                        card_id_hash, f"Confirmed legit by {payload.source}"
                    )
                    
        elif payload.outcome in ["confirmed_fraud", "chargeback"]:
            # Quarantine Profile
            profile["_meta"]["trust_state"] = "elevated_scrutiny"
            
            # Global Blocklist
            factors = report_dict.get("contributing_factors", [])
            if factors and pg_pool:
                from .features import sha256_str
                async with pg_pool.acquire() as conn:
                    for factor in factors:
                        field_name = factor.get("field")
                        observed = factor.get("observed")
                        if field_name and observed:
                            value_hash = sha256_str(str(observed))
                            await conn.execute(
                                """
                                INSERT INTO global_blocklist (field, value_hash, source_card)
                                VALUES ($1, $2, $3)
                                ON CONFLICT (field, value_hash) DO NOTHING
                                """,
                                field_name, value_hash, card_id_hash
                            )

        # 4. Save profile (retry loop if conflict)
        for attempt in range(3):
            try:
                await save_profile(card_id_hash, profile, expected_version)
                logger.info(f"Feedback processed and profile updated for {card_id_hash[:12]}")
                break
            except RuntimeError as e:
                if "conflict" in str(e).lower() and attempt < 2:
                    profile, expected_version = await get_profile(card_id_hash)
                    if not profile:
                        break
                    profile["_meta"]["trust_state"] = "normal" if payload.outcome == "confirmed_legit" else "elevated_scrutiny"
                else:
                    logger.error(f"Failed to save profile after feedback: {e}")
                    
    except Exception as e:
        logger.error(f"Feedback processing error: {e}")


@app.post("/internal/feedback", summary="Submit ground-truth feedback")
async def process_feedback(payload: FeedbackPayload, background_tasks: BackgroundTasks):
    """
    Accepts feedback on a previously scored transaction.
    - `confirmed_legit`: Reinforces the profile and clears any probation flags.
    - `confirmed_fraud` / `chargeback`: Quarantines the profile and adds contributing vectors to the global blocklist.
    """
    background_tasks.add_task(background_process_feedback, payload)
    return {"status": "accepted", "message": "Feedback queued for processing"}


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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Return an empty response for favicon requests to prevent 404 logs."""
    from fastapi.responses import Response
    return Response(content=b"", media_type="image/x-icon", status_code=204)
@app.post("/internal/demo-load-test", summary="Run dynamic dataset load simulator")
async def run_demo_load_test(background_tasks: BackgroundTasks):
    """Runs a 50-user load simulation dynamically."""
    import json, time, asyncio, random
    from datetime import datetime, timezone
    from .schemas import AReqPayload
    from fastapi import HTTPException
    
    try:
        if not pg_pool:
            raise HTTPException(status_code=503, detail="Database not connected")
        
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch("SELECT card_id_hash, profile FROM card_profiles ORDER BY random() LIMIT 50")
            
        tasks = []
        start_total = time.time()
        
        def extract_top_key(freq_dict, default):
            if not freq_dict: return default
            return max(freq_dict.items(), key=lambda x: x[1])[0]

        MCCS = ["5411", "5812", "5912", "5541", "4121", "4814", "5999", "5732"]
        COUNTRIES = ["356", "840", "826", "036", "124", "156"]
        CURRENCIES = ["356", "840", "826", "036", "124", "156"]
        DEVICES = ["Samsung Galaxy S23", "iPhone 14", "Pixel 7", "iPhone 15 Pro", "OnePlus 11"]
        PLATFORMS = ["Android", "iOS", "Windows", "macOS"]
        
        import math
        for i, row in enumerate(rows):
            card_id = row["card_id_hash"]
            profile = json.loads(row["profile"]) if isinstance(row["profile"], str) else row["profile"]
            
            txn = profile.get("transaction", {})
            dev = profile.get("device", {})
            
            amount_log = float(txn.get("amount_ewma_log", 0.0))
            if amount_log > 0:
                amount = math.exp(amount_log)
            else:
                amount = random.uniform(50.0, 2000.0)
            
            # Add very small randomness to normal amount to keep it LOW risk
            amount = amount * random.uniform(0.95, 1.05)
            
            payload_dict = {
                "simulate_only": False, # Dynamic Updating Enabled!
                "force_profile_update": True, # Force update even if MEDIUM/HIGH for demo visibility
                "card_id_hash": card_id,
                "acctType": extract_top_key(txn.get("acct_type_freq", {}), "01"),
                "mcc": extract_top_key(txn.get("mcc_freq", {}), "5411"),
                "merchantCountryCode": extract_top_key(txn.get("country_freq", {}), "356"),
                "purchaseAmount": round(amount, 2),
                "purchaseCurrency": extract_top_key(txn.get("currency_freq", {}), "356"),
                "purchaseDate": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                "Platform": extract_top_key(dev.get("platform_freq", {}), "Android"),
                "DeviceModel": extract_top_key(dev.get("device_model_freq", {}), "Samsung Galaxy A34"),
                "OSName": extract_top_key(dev.get("os_name_freq", {}), "Android"),
                "threeDSRequestorID": "REQ0001",
                "threeDSRequestorAuthenticationInd": "01",
                "threeDSReqAuthMethod": "02",
                "chAccAgeInd": "05",
                "chAccChangeInd": "05",
                "chAccPwChangeInd": "05",
                "txnActivityDay": 1,
                "txnActivityYear": 50,
                "nbPurchaseAccount": 10,
                "shipIndicator": "01",
                "cardSecurityCodeStatus": "01",
                "IPAddress": extract_top_key(dev.get("ip_subnet_freq", {}), "192.168.1.100"),
                "Latitude": 18.52,
                "Longitude": 73.85,
            }
            
            rand_val = random.random()
            if rand_val < 0.05: # 5% Abnormal (HIGH risk)
                tx_type = "abnormal"
                payload_dict["purchaseAmount"] = round(amount * 15.0, 2)
                payload_dict["merchantCountryCode"] = random.choice(COUNTRIES)
                payload_dict["Platform"] = random.choice(PLATFORMS)
                payload_dict["DeviceModel"] = random.choice(DEVICES)
                payload_dict["OSName"] = random.choice(PLATFORMS)
                payload_dict["ApplicationPackageName"] = "com.fraud.app"
                payload_dict["IPAddress"] = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
            elif rand_val < 0.20: # 15% Suspicious (MEDIUM/HIGH risk)
                tx_type = "suspicious"
                payload_dict["purchaseAmount"] = round(amount * 3.5, 2)
                payload_dict["mcc"] = random.choice(MCCS)
                payload_dict["IPAddress"] = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
            else: # 80% Normal (LOW risk)
                tx_type = "normal"
                
            payload_obj = AReqPayload(**payload_dict)
            tasks.append((tx_type, payload_obj))

        async def process_task(tx_type, payload_obj):
            t0 = time.time()
            # Pass the FastAPI background_tasks object to the scoring engine!
            report = await score(payload_obj, background_tasks)
            t1 = time.time()
            return {
                "card_id": payload_obj.card_id_hash,
                "type": tx_type,
                "tier": report.deviation_tier,
                "score": round(report.total_deviation, 2),
                "latency": round((t1 - t0) * 1000, 1)
            }
            
        coros = [process_task(t, p) for t, p in tasks]
        sim_results = await asyncio.gather(*coros)
        total_time = time.time() - start_total
        
        return {
            "total_time_sec": round(total_time, 3),
            "results": sim_results
        }
    except Exception as e:
        import traceback
        return {"error": traceback.format_exc()}
