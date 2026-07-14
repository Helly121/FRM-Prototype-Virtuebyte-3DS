"""
compute_vectors.py — Compute 40-dim surprise vectors for all transactions.

Reads transactions from `synthetic_transactions` and profiles from
`synthetic_profiles` in PostgreSQL.  For each transaction, computes
the 40-dimensional surprise vector using the shared features.py module
and writes the result into the `synthetic_surprise_vectors` table.

There are no .npy files anywhere in the pipeline.

Usage:
    python scripts/compute_vectors.py
"""

import sys
import json
from pathlib import Path

import numpy as np

# Add parent directory so we can import scoring-engine modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring-engine"))

from app.features import extract_and_score
from app.profile import new_cold_profile
from app.weights import NUM_DIMENSIONS, DIMENSION_NAMES
from db_config import get_connection, SQL_TO_PAYLOAD, bulk_insert


def _row_to_payload(row_dict: dict) -> dict:
    """Convert a SQL row dict to a payload dict with original key names."""
    payload = {}
    for sql_col, val in row_dict.items():
        payload_key = SQL_TO_PAYLOAD.get(sql_col, sql_col)
        payload[payload_key] = val
    return payload


def compute_surprise_vectors():
    """
    Compute surprise vectors for all transactions and write them
    to the synthetic_surprise_vectors table.
    """
    print("=" * 70)
    print("Surprise Vector Computation  (PostgreSQL -> synthetic_surprise_vectors)")
    print("=" * 70)

    conn = get_connection()

    # 1. Load profiles from synthetic_profiles
    print("  Loading profiles from synthetic_profiles...")
    profiles = {}
    with conn.cursor() as cur:
        cur.execute("SELECT card_id_hash, profile_data FROM synthetic_profiles")
        for card_id_hash, profile_data in cur.fetchall():
            profiles[card_id_hash] = (
                json.loads(profile_data) if isinstance(profile_data, str)
                else profile_data
            )
    print(f"  -> {len(profiles)} profiles loaded")

    # 2. Fetch all transactions (with their row id for FK reference)
    print("  Loading transactions from synthetic_transactions...")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM synthetic_transactions ORDER BY id"
        )
        col_names = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    n = len(rows)
    print(f"  -> {n} transactions loaded")

    # 3. Compute surprise vectors
    vectors = np.zeros((n, NUM_DIMENSIONS), dtype=np.float64)
    labels = np.zeros(n, dtype=np.int32)
    insert_rows = []
    missing_profiles = 0

    print(f"\n  Computing {n} surprise vectors...")

    for i, raw_row in enumerate(rows):
        row_dict = dict(zip(col_names, raw_row))
        txn_id = row_dict["id"]               # synthetic_transactions.id
        card_id = row_dict["card_id_hash"]
        is_anomaly = bool(row_dict.get("is_anomaly", False))
        anomaly_types = row_dict.get("anomaly_types") or []

        # Convert SQL row to payload dict for scoring engine
        payload = _row_to_payload(row_dict)

        # Get profile
        profile = profiles.get(card_id)
        if profile is None:
            missing_profiles += 1
            profile = new_cold_profile(card_id)

        # Compute surprise vector
        surprise_vector, _contributions, _cf = extract_and_score(
            payload, profile
        )

        vectors[i] = surprise_vector
        labels[i] = 1 if is_anomaly else 0

        # Build row for synthetic_surprise_vectors
        insert_rows.append((
            card_id,
            txn_id,
            surprise_vector.tolist(),  # Native Python floats for psycopg2
            is_anomaly,
            anomaly_types,
        ))

        if (i + 1) % 10000 == 0:
            pct = (i + 1) / n * 100
            anomaly_pct = np.mean(labels[:i + 1]) * 100
            print(f"    ... {i+1}/{n} ({pct:.0f}%) -- "
                  f"anomaly rate so far: {anomaly_pct:.1f}%")

    if missing_profiles > 0:
        print(f"  !! {missing_profiles} transactions had no profile "
              "(used cold-start)")

    # 4. Statistics
    print(f"\n  Vector statistics:")
    print(f"    Shape: ({n}, {NUM_DIMENSIONS})")
    print(f"    Total anomalies: {labels.sum()} "
          f"({labels.mean()*100:.1f}%)")
    print(f"    Total normals:   {int((1 - labels).sum())}")

    print(f"\n  Per-dimension mean surprise (anomalies vs normals):")
    print(f"    {'Dimension':<30} {'Normal':>8} {'Anomaly':>8} "
          f"{'Ratio':>8}")
    print(f"    {'-'*56}")

    normal_mask = labels == 0
    anomaly_mask = labels == 1
    for dim_idx in range(NUM_DIMENSIONS):
        normal_mean = vectors[normal_mask, dim_idx].mean()
        anomaly_mean = vectors[anomaly_mask, dim_idx].mean()
        ratio = anomaly_mean / max(normal_mean, 1e-9)
        if anomaly_mean > normal_mean * 1.5:
            print(f"    {DIMENSION_NAMES[dim_idx]:<30} "
                  f"{normal_mean:>8.3f} {anomaly_mean:>8.3f} "
                  f"{ratio:>8.1f}x")

    # 5. Write to synthetic_surprise_vectors
    print(f"\n  Writing {len(insert_rows)} vectors to "
          "synthetic_surprise_vectors...")
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE synthetic_surprise_vectors RESTART IDENTITY"
        )
    conn.commit()

    sv_columns = [
        "card_id_hash", "transaction_id", "surprise_vector",
        "is_anomaly", "anomaly_types",
    ]
    inserted = bulk_insert(conn, "synthetic_surprise_vectors",
                           sv_columns, insert_rows, batch_size=5000)
    print(f"  -> {inserted} rows inserted")

    # Verify
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM synthetic_surprise_vectors")
        db_count = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM synthetic_surprise_vectors "
            "WHERE is_anomaly = TRUE"
        )
        db_anomaly = cur.fetchone()[0]
    print(f"  -> Verified: {db_count} vectors, {db_anomaly} anomalies in DB")

    conn.close()

    print("\n" + "=" * 70)
    print("Vector computation complete!")
    print("=" * 70)


if __name__ == "__main__":
    compute_surprise_vectors()
