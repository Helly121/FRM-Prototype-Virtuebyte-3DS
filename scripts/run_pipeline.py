"""
run_pipeline.py — Run the full offline pipeline with an embedded PostgreSQL.

Uses pgserver to spin up a local PostgreSQL instance (no admin rights
needed), creates the schema, and runs all four pipeline steps in sequence.

This is the single entry point for the offline pipeline.

Usage:
    python scripts/run_pipeline.py
"""

import os
import sys
import time
from pathlib import Path

# Ensure scripts dir is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def run_pipeline():
    print("=" * 70)
    print("  3DS Anomaly Detection — Full Offline Pipeline")
    print("=" * 70)

    # 1. Start embedded PostgreSQL via pgserver
    print("\n[1/5] Starting embedded PostgreSQL via pgserver...")
    import pgserver

    pg_data_dir = str(Path(__file__).resolve().parent.parent / ".pgdata")
    pg = pgserver.get_server(pg_data_dir)
    dsn = pg.get_uri()
    print(f"  -> PostgreSQL running. DSN: {dsn}")

    # Export DSN so all scripts pick it up
    os.environ["PG_DSN"] = dsn

    # 2. Create schema
    print("\n[2/5] Creating schema...")
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    schema_path = Path(__file__).resolve().parent.parent / "postgres" / "init.sql"
    with open(schema_path) as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.close()
    print("  -> Schema created (6 tables)")

    # 3. Generate dataset
    print("\n[3/5] Generating synthetic dataset -> synthetic_transactions...")
    from generate_dataset import generate_dataset
    t0 = time.time()
    generate_dataset()
    print(f"  -> Dataset generated in {time.time()-t0:.1f}s")

    # 4. Bootstrap profiles
    print("\n[4/5] Bootstrapping profiles -> synthetic_profiles...")
    from bootstrap_profiles import bootstrap_profiles
    t0 = time.time()
    bootstrap_profiles(load_redis=False)
    print(f"  -> Profiles bootstrapped in {time.time()-t0:.1f}s")

    # 5. Compute surprise vectors
    print("\n[5/5] Computing surprise vectors -> synthetic_surprise_vectors...")
    from compute_vectors import compute_surprise_vectors
    t0 = time.time()
    compute_surprise_vectors()
    print(f"  -> Vectors computed in {time.time()-t0:.1f}s")

    # 6. Train model
    print("\n[6/5] Training Isolation Forest...")
    from train_model import train_model
    t0 = time.time()
    train_model()
    print(f"  -> Model trained in {time.time()-t0:.1f}s")

    # Final summary
    conn = psycopg2.connect(dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM synthetic_transactions")
        txn_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM synthetic_profiles")
        profile_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM synthetic_surprise_vectors")
        vector_count = cur.fetchone()[0]
    conn.close()

    print("\n" + "=" * 70)
    print("  Pipeline Complete!")
    print("=" * 70)
    print(f"  synthetic_transactions:    {txn_count:>8} rows")
    print(f"  synthetic_profiles:        {profile_count:>8} rows")
    print(f"  synthetic_surprise_vectors:{vector_count:>8} rows")
    print(f"  Model: model/isolation_forest.pkl")
    print(f"\n  PostgreSQL data dir: {pg_data_dir}")
    print(f"  DSN: {dsn}")
    print("=" * 70)

    # Keep pgserver alive (it persists via the data dir)
    return pg


if __name__ == "__main__":
    run_pipeline()
