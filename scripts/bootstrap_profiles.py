"""
bootstrap_profiles.py — Build per-card profiles from establishment records.

Reads the 70,000 establishment-phase transactions from the PostgreSQL
`synthetic_transactions` table, computes a profile for each card using
the production update_profile() logic, and writes the resulting profiles
into the `synthetic_profiles` table.  Optionally also loads them into Redis.

Usage:
    python scripts/bootstrap_profiles.py [--redis]
"""

import os
import sys
import json
import argparse
from pathlib import Path

import psycopg2.extras

# Add parent directory so we can import scoring-engine modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring-engine"))

from app.profile import new_cold_profile, update_profile
from db_config import get_connection, SQL_TO_PAYLOAD


def _rows_to_payloads(rows, col_names):
    """Convert a list of DB rows into payload dicts with original key names."""
    payloads = []
    for row in rows:
        row_dict = dict(zip(col_names, row))
        payload = {}
        for sql_col, val in row_dict.items():
            payload_key = SQL_TO_PAYLOAD.get(sql_col, sql_col)
            payload[payload_key] = val
        payloads.append(payload)
    return payloads


def bootstrap_profiles(load_redis: bool = False):
    """
    Build profiles from establishment-phase transactions stored in PostgreSQL.

    Steps:
      1. SELECT establishment-phase rows from synthetic_transactions
      2. Group by card_id_hash
      3. For each card, sequentially apply update_profile()
      4. INSERT each profile into synthetic_profiles
      5. Optionally load into Redis
    """
    print("=" * 70)
    print("Profile Bootstrap  (PostgreSQL -> synthetic_profiles)")
    print("=" * 70)

    conn = get_connection()

    # 1. Fetch establishment-phase transactions
    print("  Reading establishment transactions from PostgreSQL...")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM synthetic_transactions "
            "WHERE phase = 'establishment' "
            "ORDER BY card_id_hash, sequence_idx"
        )
        col_names = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    print(f"  -> {len(rows)} establishment rows fetched")

    # 2. Convert to payload dicts and group by card
    payloads = _rows_to_payloads(rows, col_names)

    card_txns = {}
    for p in payloads:
        cid = p["card_id_hash"]
        if cid not in card_txns:
            card_txns[cid] = []
        card_txns[cid].append(p)

    print(f"  -> {len(card_txns)} unique cards")

    # 3. Build profiles
    profiles = {}
    print("  Building profiles...")
    for i, (card_id_hash, txns) in enumerate(card_txns.items()):
        profile = new_cold_profile(card_id_hash)
        for txn in txns:
            profile = update_profile(profile, txn)
        profiles[card_id_hash] = profile

        if (i + 1) % 200 == 0:
            print(f"    ... {i + 1}/{len(card_txns)} profiles built")

    print(f"  -> {len(profiles)} profiles built")

    # Profile statistics
    conf_vals = [p["_meta"]["profile_confidence"] for p in profiles.values()]
    txn_counts = [p["_meta"]["transaction_count"] for p in profiles.values()]
    print(f"\n  Profile statistics:")
    print(f"    Avg confidence:  {sum(conf_vals)/len(conf_vals):.3f}")
    print(f"    Min confidence:  {min(conf_vals):.3f}")
    print(f"    Max confidence:  {max(conf_vals):.3f}")
    print(f"    Avg txn count:   {sum(txn_counts)/len(txn_counts):.1f}")

    # 4. Write to synthetic_profiles table
    print("\n  Writing profiles to synthetic_profiles table...")
    with conn.cursor() as cur:
        cur.execute("TRUNCATE synthetic_profiles")
        for card_id_hash, profile in profiles.items():
            cur.execute(
                "INSERT INTO synthetic_profiles "
                "(card_id_hash, profile_data, txn_count, confidence) "
                "VALUES (%s, %s, %s, %s)",
                (
                    card_id_hash,
                    json.dumps(profile, default=str),
                    profile["_meta"]["transaction_count"],
                    profile["_meta"]["profile_confidence"],
                ),
            )
    conn.commit()
    print(f"  -> {len(profiles)} profiles written to synthetic_profiles")

    # Verify
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM synthetic_profiles")
        db_count = cur.fetchone()[0]
    print(f"  -> Verified: {db_count} profiles in DB")

    # 5. Optionally load into Redis
    if load_redis:
        try:
            import redis
            r = redis.Redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379"),
                decode_responses=True,
            )
            r.ping()
            print("\n  Loading profiles into Redis...")
            pipe = r.pipeline()
            for card_id_hash, profile in profiles.items():
                pipe.set(
                    f"profile:{card_id_hash}",
                    json.dumps(profile, default=str),
                    ex=7776000,
                )
            pipe.execute()
            print(f"  -> {len(profiles)} profiles loaded into Redis")
        except Exception as e:
            print(f"  !! Redis load failed: {e}")
            print("     Profiles are still in the synthetic_profiles table.")

    conn.close()

    print("\n" + "=" * 70)
    print("Bootstrap complete!")
    print("=" * 70)

    return profiles


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap card profiles")
    parser.add_argument("--redis", action="store_true",
                        help="Also load profiles into Redis")
    args = parser.parse_args()
    bootstrap_profiles(load_redis=args.redis)
