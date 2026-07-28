"""
startup.py — Automatic startup checks and self-healing for the scoring engine.

Runs ONCE at container startup (before uvicorn forks workers):
  1. Waits for PostgreSQL to be ready
  2. Ensures all required tables exist (card_profiles, global_blocklist, etc.)
  3. Seeds demo profiles if card_profiles is empty
  4. Trains or loads the Isolation Forest model if missing

This means `docker compose up --build` produces a fully working demo
with no manual SQL or Python commands required.
"""

import os
import sys
import json
import time
import math
import hashlib
import logging
import random

import numpy as np
import psycopg2
import psycopg2.extras
import joblib
from pathlib import Path
from sklearn.ensemble import IsolationForest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [startup] %(message)s",
)
logger = logging.getLogger("startup")

PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@postgres:5432/anomaly_db")
MODEL_PATH = os.getenv("MODEL_PATH", "/app/model/isolation_forest.pkl")
NUM_DIMENSIONS = 40


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_postgres(dsn: str, max_retries: int = 30, delay: float = 2.0):
    """Block until PostgreSQL accepts connections."""
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(dsn)
            conn.close()
            logger.info("PostgreSQL is ready")
            return True
        except psycopg2.OperationalError:
            logger.info(f"Waiting for PostgreSQL... ({attempt + 1}/{max_retries})")
            time.sleep(delay)
    logger.error("PostgreSQL did not become ready in time")
    return False


def get_conn(dsn: str):
    return psycopg2.connect(dsn)


def table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=%s)",
            (table_name,)
        )
        return cur.fetchone()[0]


def ensure_tables(conn):
    """Create any missing tables so the app never crashes on a missing relation."""
    ddl_statements = [
        # card_profiles
        """
        CREATE TABLE IF NOT EXISTS card_profiles (
            card_id_hash        TEXT PRIMARY KEY,
            profile             JSONB NOT NULL,
            version             INTEGER NOT NULL DEFAULT 1,
            transaction_count   INTEGER DEFAULT 0,
            profile_confidence  FLOAT DEFAULT 0.0,
            trust_state         TEXT NOT NULL DEFAULT 'normal'
                                CHECK (trust_state IN ('normal','elevated_scrutiny')),
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_profile_updated ON card_profiles(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_profile_gin ON card_profiles USING GIN (profile jsonb_path_ops)",

        # global_blocklist
        """
        CREATE TABLE IF NOT EXISTS global_blocklist (
            id          BIGSERIAL PRIMARY KEY,
            field       TEXT NOT NULL,
            value_hash  TEXT NOT NULL,
            flagged_at  TIMESTAMPTZ DEFAULT NOW(),
            source_card TEXT NOT NULL,
            UNIQUE (field, value_hash)
        )
        """,

        # profile_reinforcement_log
        """
        CREATE TABLE IF NOT EXISTS profile_reinforcement_log (
            id            BIGSERIAL PRIMARY KEY,
            card_id_hash  TEXT NOT NULL,
            reinforced_at TIMESTAMPTZ DEFAULT NOW(),
            reason        TEXT
        )
        """,

        # scored_transactions — add outcome_label column if missing
        """
        CREATE TABLE IF NOT EXISTS scored_transactions (
            id                   BIGSERIAL PRIMARY KEY,
            txn_id               TEXT NOT NULL UNIQUE,
            card_id_hash         TEXT NOT NULL,
            scored_at            TIMESTAMPTZ DEFAULT NOW(),
            deviation_tier       TEXT,
            total_deviation      FLOAT,
            if_score             FLOAT,
            profile_confidence   FLOAT,
            channel              TEXT DEFAULT 'SDK',
            contributing_factors JSONB,
            full_report          JSONB,
            outcome_label        TEXT DEFAULT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_card_id   ON scored_transactions(card_id_hash)",
        "CREATE INDEX IF NOT EXISTS idx_scored_at ON scored_transactions(scored_at)",
        "CREATE INDEX IF NOT EXISTS idx_tier      ON scored_transactions(deviation_tier)",

        # outcome_feedback
        """
        CREATE TABLE IF NOT EXISTS outcome_feedback (
            id          BIGSERIAL PRIMARY KEY,
            txn_id      TEXT,
            feedback_at TIMESTAMPTZ DEFAULT NOW(),
            outcome     TEXT,
            source      TEXT
        )
        """,

        # model_configuration (weight store for Issue #3)
        """
        CREATE TABLE IF NOT EXISTS model_configuration (
            id           BIGSERIAL PRIMARY KEY,
            vector_name  TEXT NOT NULL UNIQUE,
            weight       FLOAT NOT NULL,
            updated_at   TIMESTAMPTZ DEFAULT NOW(),
            updated_by   TEXT NOT NULL DEFAULT 'system'
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_mc_vector ON model_configuration(vector_name)",

        # weight_change_log — audit trail for config changes
        """
        CREATE TABLE IF NOT EXISTS weight_change_log (
            id           BIGSERIAL PRIMARY KEY,
            changed_at   TIMESTAMPTZ DEFAULT NOW(),
            changed_by   TEXT NOT NULL DEFAULT 'system',
            previous     JSONB NOT NULL,
            updated      JSONB NOT NULL,
            delta_summary TEXT
        )
        """,
    ]

    with conn.cursor() as cur:
        for stmt in ddl_statements:
            try:
                cur.execute(stmt)
            except Exception as e:
                logger.warning(f"DDL warning (non-fatal): {e}")
                conn.rollback()
                continue
    conn.commit()
    logger.info("All required tables verified/created")


# ---------------------------------------------------------------------------
# Seed profiles if the table is empty
# ---------------------------------------------------------------------------

def build_demo_profile(card_idx: int) -> dict:
    """Build a realistic demo profile for a card."""
    arch_idx = card_idx % 10
    platforms = ["Android", "Android", "Android", "Android", "iOS",
                 "iOS", "Android", "Android", "Android", "iOS"]
    device_models = [
        "Samsung Galaxy S23", "Samsung Galaxy A54", "Redmi Note 12",
        "OnePlus 12", "iPhone 15 Pro", "iPhone 14 Pro",
        "Google Pixel 8 Pro", "Realme C55", "Samsung Galaxy S24 Ultra", "iPhone 15"
    ]
    os_names = ["Android", "Android", "Android", "Android", "iOS",
                "iOS", "Android", "Android", "Android", "iOS"]
    os_versions = ["14", "13", "13", "14", "17.4", "17.5", "14", "12", "14", "17.5"]
    locales = ["en_IN"] * 9 + ["en_US"]
    timezones = ["Asia/Kolkata"] * 9 + ["America/New_York"]
    lats = [18.52, 19.07, 26.85, 12.97, 28.61, 17.39, 13.08, 22.57, 15.36, 40.71]
    lons = [73.85, 72.88, 80.95, 77.59, 77.21, 78.49, 80.27, 88.36, 75.12, -74.01]
    amounts = [1800, 7300, 500, 13000, 300, 3600, 2400, 900, 245, 90]
    txn_counts = [72, 85, 43, 91, 56, 67, 38, 81, 95, 62]

    platform = platforms[arch_idx]
    device = device_models[arch_idx]
    os_n = os_names[arch_idx]
    os_v = os_versions[arch_idx]
    locale = locales[arch_idx]
    tz = timezones[arch_idx]
    lat = lats[arch_idx]
    lon = lons[arch_idx]
    amount = amounts[arch_idx]
    txn_count = txn_counts[arch_idx]
    country = "840" if arch_idx == 9 else "356"

    card_hash = hashlib.sha256(f"card_{card_idx:06d}".encode()).hexdigest()
    ts_now = time.time()

    # Build uniform hour/dow histograms slightly peaked at business hours
    hour_hist = [1.0 / 24] * 24
    for h in range(9, 22):
        hour_hist[h] += 0.02
    total_h = sum(hour_hist)
    hour_hist = [x / total_h for x in hour_hist]

    dow_hist = [1.0 / 7] * 7
    for d in range(0, 5):  # weekdays slightly higher
        dow_hist[d] += 0.01
    total_d = sum(dow_hist)
    dow_hist = [x / total_d for x in dow_hist]

    app_package = "com.merchant.pay.app1"
    app_hash = hashlib.sha256(app_package.encode()).hexdigest()
    sdk_ref = "SDK_REF_CONSTANT_HASH_V1"
    sdk_ref_hash = hashlib.sha256(sdk_ref.encode()).hexdigest()

    # Compute billing addr hash matching what features.py produces
    billing_parts = f"123 main road|pune|{country}|400001".split("|")
    billing_hash = hashlib.sha256("|".join(billing_parts).encode()).hexdigest()

    req_url = "https://pay1.merchant.com/3ds"
    req_url_hash = hashlib.sha256(req_url.encode()).hexdigest()

    return {
        "_meta": {
            "card_id_hash": card_hash,
            "created_at": ts_now - 180 * 86400,
            "last_updated": ts_now - random.randint(0, 7 * 86400),
            "history_depth_days": 180.0,
            "transaction_count": txn_count,
            "profile_confidence": min(1.0, txn_count / 50.0),
        },
        "transaction": {
            "acct_type_freq": {"01": float(txn_count - 5), "02": 5.0},
            "mcc_freq": {"5411": float(txn_count) * 0.7, "5812": float(txn_count) * 0.2, "5999": float(txn_count) * 0.1},
            "country_freq": {country: float(txn_count) * 0.95, "840" if country == "356" else "356": float(txn_count) * 0.05},
            "currency_freq": {country: float(txn_count) * 0.95},
            "amount_ewma_log": math.log1p(amount),
            "amount_ewma_var": 0.25 + random.random() * 0.3,
            "hour_hist": hour_hist,
            "dow_hist": dow_hist,
            "cvv_match_rate": 0.97,
        },
        "requestor": {
            "known_requestors": {
                "REQ0001": {"freq": txn_count * 0.7, "last_seen": ts_now - 3600},
                "REQ0002": {"freq": txn_count * 0.3, "last_seen": ts_now - 86400},
            },
            "known_req_urls": {
                req_url_hash: {"freq": txn_count, "last_seen": ts_now - 3600},
            },
            "auth_ind_freq": {"01": txn_count * 0.85, "02": txn_count * 0.1, "03": txn_count * 0.05},
            "auth_method_freq": {"02": txn_count * 0.6, "01": txn_count * 0.2, "06": txn_count * 0.2},
            "ch_acc_age_ind_last": 5,
            "ch_acc_change_ind_ewma": 4.2,
            "ch_acc_pw_change_ind_ewma": 4.5,
            "txn_activity_day_ewma": 1.2,
            "txn_activity_day_var": 0.5,
            "txn_activity_year_ewma": 52.0,
            "txn_activity_year_var": 25.0,
            "provision_attempts_ewma": 0.0,
            "provision_attempts_var": 0.01,
            "nb_purchase_ewma": 42.0,
            "nb_purchase_var": 10.0,
            "suspicious_ever": False,
            "ship_name_match_rate": 0.96,
        },
        "merchant": {
            "known_merchant_ids": {
                "MID000001": {"freq": txn_count * 0.5, "last_seen": ts_now - 3600},
                "MID000002": {"freq": txn_count * 0.3, "last_seen": ts_now - 86400},
            },
            "known_acquirer_bins": {
                "411111": {"freq": txn_count, "last_seen": ts_now - 3600},
            },
            "ship_ind_freq": {"01": txn_count * 0.65, "02": txn_count * 0.2, "03": txn_count * 0.15},
            "billing_addr_hashes": {
                billing_hash: {"freq": txn_count, "last_seen": ts_now - 3600},
            },
            "shipping_addr_hashes": {},
            "known_email_hashes": {
                hashlib.sha256(f"user{card_idx}@gmail.com".encode()).hexdigest(): {"freq": txn_count, "last_seen": ts_now - 3600},
            },
            "known_phone_hashes": {
                hashlib.sha256(f"+919876543{card_idx:03d}".encode()).hexdigest(): {"freq": txn_count, "last_seen": ts_now - 3600},
            },
            "billing_lat": lat,
            "billing_lon": lon,
            "billing_radius_km": 5.0,
            "shipping_lat": lat,
            "shipping_lon": lon,
            "shipping_radius_km": 10.0,
        },
        "device": {
            "platform_freq": {platform: float(txn_count) * 0.97, "Other": float(txn_count) * 0.03},
            "device_model_freq": {device: float(txn_count) * 0.95, "Other": float(txn_count) * 0.05},
            "os_name_freq": {os_n: float(txn_count) * 0.98},
            "os_version_freq": {os_v: float(txn_count) * 0.95},
            "locale_freq": {locale: float(txn_count) * 0.97},
            "known_timezones": {
                tz: {"freq": float(txn_count), "last_seen": ts_now - 3600},
            },
            "known_resolutions": {
                ("1179x2556" if platform == "iOS" else "1080x2340"): {"freq": float(txn_count), "last_seen": ts_now - 3600},
            },
            "known_ip_subnets": {
                "192.168.1.0/24": {"freq": float(txn_count), "last_seen": ts_now - 3600},
            },
            "device_fp_hashes": {},
            "known_app_packages": {
                app_hash: {"freq": float(txn_count), "last_seen": ts_now - 3600},
            },
            "known_sdk_app_ids": {},
            "sdk_version_freq": {"5.3.0": float(txn_count) * 0.8, "5.2.1": float(txn_count) * 0.2},
            "expected_sdk_ref_hash": sdk_ref_hash,
            "known_device_names": {},
            "known_sdk_interfaces": {},
            "geo_lat": lat,
            "geo_lon": lon,
            "geo_radius_km": 3.0,
            "probation": {},
        },
    }


def seed_profiles_if_empty(conn):
    """Insert 100 demo profiles if card_profiles is empty."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM card_profiles")
        count = cur.fetchone()[0]

    if count > 0:
        logger.info(f"card_profiles already has {count} rows — skipping seed")
        return count

    logger.info("card_profiles is empty — seeding 100 demo profiles...")
    seeded = 0
    for i in range(100):
        profile = build_demo_profile(i)
        card_hash = profile["_meta"]["card_id_hash"]
        txn_count = profile["_meta"]["transaction_count"]
        confidence = profile["_meta"]["profile_confidence"]
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO card_profiles
                        (card_id_hash, profile, version, transaction_count,
                         profile_confidence, trust_state)
                    VALUES (%s, %s, 1, %s, %s, 'normal')
                    ON CONFLICT (card_id_hash) DO NOTHING
                    """,
                    (card_hash, json.dumps(profile), txn_count, confidence)
                )
            conn.commit()
            seeded += 1
        except Exception as e:
            logger.warning(f"Profile seed error for card {i}: {e}")
            conn.rollback()

    logger.info(f"Seeded {seeded} profiles into card_profiles")

    # Seed audit log entries too
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM scored_transactions")
            audit_count = cur.fetchone()[0]

        if audit_count == 0:
            with conn.cursor() as cur:
                cur.execute("SELECT card_id_hash FROM card_profiles LIMIT 10")
                card_hashes = [r[0] for r in cur.fetchall()]

            tiers = ["LOW", "LOW", "LOW", "MEDIUM", "HIGH"]
            scores = [0.12, 0.31, 0.52, 1.78, 3.45]
            for i in range(50):
                ch = card_hashes[i % len(card_hashes)]
                tier = tiers[i % 5]
                score = scores[i % 5]
                if_s = -0.25 if tier == "HIGH" else (-0.08 if tier == "MEDIUM" else 0.05)
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO scored_transactions
                                (txn_id, card_id_hash, deviation_tier,
                                 total_deviation, if_score, profile_confidence,
                                 channel, contributing_factors, full_report)
                            VALUES (%s, %s, %s, %s, %s, 0.85, 'SDK', '[]'::jsonb, '{}'::jsonb)
                            ON CONFLICT (txn_id) DO NOTHING
                            """,
                            (f"txn_seed_{i:08d}", ch, tier, score, if_s)
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
            logger.info("Seeded 50 audit log entries")
    except Exception as e:
        logger.warning(f"Audit seed error: {e}")

    return seeded


# ---------------------------------------------------------------------------
# Model generation
# ---------------------------------------------------------------------------

def generate_model_if_missing():
    """
    Train a lightweight IsolationForest from synthetic data if the model file
    does not exist. This ensures `IF model not found` never appears in logs.
    """
    model_path = Path(MODEL_PATH)
    if model_path.exists():
        try:
            m = joblib.load(str(model_path))
            # Quick sanity check
            test = np.zeros((1, NUM_DIMENSIONS))
            m.decision_function(test)
            logger.info(f"Existing IF model loaded successfully from {MODEL_PATH}")
            return
        except Exception as e:
            logger.warning(f"Existing model is corrupt ({e}), retraining...")
            model_path.unlink(missing_ok=True)

    logger.info("IF model not found — generating synthetic training data and training model...")

    np.random.seed(42)
    random.seed(42)

    # -------------------------------------------------------------------
    # Generate synthetic surprise vectors
    # Normal vectors: mostly near zero with small variance
    # Anomaly vectors: spikes in random dimensions with high values
    # -------------------------------------------------------------------
    N_NORMAL = 9000
    N_ANOMALY = 1000

    # Normal: low surprise (0.0 – 0.3 range, occasionally up to 1.0)
    normals = np.abs(np.random.normal(0.05, 0.15, (N_NORMAL, NUM_DIMENSIONS)))
    normals = np.clip(normals, 0.0, 1.5)

    # Anomaly vectors: inject spikes in high-weight dimensions
    # Weight dims: 18 (suspicious=0.10), 27 (platform=0.20), 36 (app_pkg=0.18),
    #              37 (sdk_ref=0.15), 39 (device_fp=0.14), 35 (geo=0.10)
    HIGH_WEIGHT_DIMS = [18, 27, 36, 37, 39, 35, 23, 3, 16]

    anomalies = np.abs(np.random.normal(0.05, 0.15, (N_ANOMALY, NUM_DIMENSIONS)))
    for i in range(N_ANOMALY):
        # Spike 2-5 high-weight dimensions
        n_spikes = random.randint(2, 5)
        dims = random.sample(HIGH_WEIGHT_DIMS, min(n_spikes, len(HIGH_WEIGHT_DIMS)))
        for d in dims:
            anomalies[i, d] = np.random.uniform(2.0, 8.0)

    X = np.vstack([normals, anomalies])
    y = np.array([0] * N_NORMAL + [1] * N_ANOMALY)

    logger.info(f"Training IsolationForest on {len(X)} synthetic vectors ({N_ANOMALY} anomalies)...")

    model = IsolationForest(
        n_estimators=200,
        contamination=0.10,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, str(model_path))

    # Quick validation
    preds = model.predict(X)
    detected_anomalies = sum(1 for i in range(N_NORMAL, len(X)) if preds[i] == -1)
    anomaly_recall = detected_anomalies / N_ANOMALY
    logger.info(
        f"Model trained. Anomaly recall on training data: "
        f"{detected_anomalies}/{N_ANOMALY} = {anomaly_recall:.1%}"
    )
    logger.info(f"Model saved to {MODEL_PATH}")


# ---------------------------------------------------------------------------
# Seed blocklist
# ---------------------------------------------------------------------------

def seed_blocklist_if_empty(conn):
    """Insert known-bad entries into global_blocklist."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM global_blocklist")
        count = cur.fetchone()[0]

    if count > 0:
        return

    entries = [
        ("device.ApplicationPackageName",
         hashlib.sha256("com.fraud.app".encode()).hexdigest(),
         "seed_demo"),
        ("device.IPAddress",
         hashlib.sha256("8.8.8.8".encode()).hexdigest(),
         "seed_demo"),
    ]
    with conn.cursor() as cur:
        for field, value_hash, source in entries:
            cur.execute(
                """
                INSERT INTO global_blocklist (field, value_hash, source_card)
                VALUES (%s, %s, %s)
                ON CONFLICT (field, value_hash) DO NOTHING
                """,
                (field, value_hash, source)
            )
    conn.commit()
    logger.info("Seeded global blocklist demo entries")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_startup_checks():
    """Run all startup checks. Called before uvicorn starts."""
    logger.info("=" * 60)
    logger.info("Running startup checks...")
    logger.info("=" * 60)

    if not wait_for_postgres(PG_DSN):
        logger.error("Cannot connect to PostgreSQL — aborting startup checks")
        return

    try:
        conn = get_conn(PG_DSN)
        conn.autocommit = False

        ensure_tables(conn)
        seed_profiles_if_empty(conn)
        seed_blocklist_if_empty(conn)

        conn.close()
    except Exception as e:
        logger.error(f"Startup DB check failed: {e}")

    generate_model_if_missing()

    logger.info("=" * 60)
    logger.info("Startup checks complete. System ready.")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_startup_checks()
