"""
config_service.py — Model Configuration service layer.

Provides:
  - Persistent weight storage in PostgreSQL (model_configuration table)
  - In-memory cache with async cache invalidation
  - load_current_weights() → returns live numpy arrays
  - save_weights()         → validates, persists, audits, invalidates cache
  - get_weight_metadata()  → summary stats for the UI

Architecture
------------
The scoring engine NEVER reads from weights.py STATIC_WEIGHTS at request time.
All scoring uses load_current_weights(), which:
  1. Returns the in-memory cache if it's fresh (< CACHE_TTL_SECONDS)
  2. On cache miss, reads from PostgreSQL
  3. Falls back to weights.py defaults if PostgreSQL is unavailable

Cache invalidation is immediate on PUT /internal/config/weights so scores
reflect the new configuration on the very next request — no restart needed.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import numpy as np

from .weights import (
    DIMENSION_NAMES,
    STATIC_WEIGHTS,
    CROSS_FIELD_NAMES,
    CROSS_FIELD_WEIGHTS,
    NUM_DIMENSIONS,
)

logger = logging.getLogger("config-service")

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS = 60  # re-read from DB after 60 s even without explicit invalidation

_weight_cache: Optional[dict] = None
_cache_loaded_at: float = 0.0
_cache_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Default weight snapshot (built once from weights.py at import time)
# ---------------------------------------------------------------------------

DEFAULT_DIMENSION_WEIGHTS: dict[str, float] = {
    name: float(STATIC_WEIGHTS[i]) for i, name in enumerate(DIMENSION_NAMES)
}

DEFAULT_CROSS_FIELD_WEIGHTS: dict[str, float] = dict(CROSS_FIELD_WEIGHTS)

ALL_DEFAULT_WEIGHTS: dict[str, float] = {
    **DEFAULT_DIMENSION_WEIGHTS,
    **DEFAULT_CROSS_FIELD_WEIGHTS,
}

ALL_VECTOR_NAMES: list[str] = DIMENSION_NAMES + list(CROSS_FIELD_NAMES)

# ---------------------------------------------------------------------------
# DB helpers  (these use the pg_pool injected from main.py)
# ---------------------------------------------------------------------------

async def _ensure_tables(pool) -> None:
    """Create model_configuration and weight_change_log if not present."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS model_configuration (
                id           BIGSERIAL PRIMARY KEY,
                vector_name  TEXT NOT NULL UNIQUE,
                weight       FLOAT NOT NULL,
                updated_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_by   TEXT NOT NULL DEFAULT 'system'
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mc_vector ON model_configuration(vector_name)"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS weight_change_log (
                id           BIGSERIAL PRIMARY KEY,
                changed_at   TIMESTAMPTZ DEFAULT NOW(),
                changed_by   TEXT NOT NULL DEFAULT 'system',
                previous     JSONB NOT NULL,
                updated      JSONB NOT NULL,
                delta_summary TEXT
            )
        """)
    logger.info("model_configuration and weight_change_log tables verified")


async def _load_from_db(pool) -> dict[str, float]:
    """
    Read all persisted weights from PostgreSQL.
    Returns a full weight dict (merges defaults for any missing vector).
    """
    weights: dict[str, float] = dict(ALL_DEFAULT_WEIGHTS)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT vector_name, weight FROM model_configuration"
            )
        for row in rows:
            name = row["vector_name"]
            if name in weights:
                weights[name] = float(row["weight"])
    except Exception as e:
        logger.warning(f"Weight DB read failed ({e}), using defaults")
    return weights


async def _seed_defaults_if_empty(pool) -> None:
    """
    Insert default weights into model_configuration if the table is empty.
    This runs once on first startup so the UI shows meaningful values immediately.
    """
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM model_configuration")
        if count == 0:
            rows = [
                (name, float(STATIC_WEIGHTS[i]))
                for i, name in enumerate(DIMENSION_NAMES)
            ] + [
                (name, float(CROSS_FIELD_WEIGHTS[name]))
                for name in CROSS_FIELD_NAMES
            ]
            await conn.executemany(
                """
                INSERT INTO model_configuration (vector_name, weight, updated_by)
                VALUES ($1, $2, 'system:defaults')
                ON CONFLICT (vector_name) DO NOTHING
                """,
                rows,
            )
            logger.info("Seeded default weights into model_configuration")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def initialize_config_service(pool) -> None:
    """Called once from main.py lifespan after pg_pool is ready."""
    await _ensure_tables(pool)
    await _seed_defaults_if_empty(pool)
    logger.info("Config service ready")


def invalidate_cache() -> None:
    """Immediately invalidate the in-memory weight cache."""
    global _weight_cache, _cache_loaded_at
    _weight_cache = None
    _cache_loaded_at = 0.0
    logger.info("Weight cache invalidated")


async def load_current_weights(pool=None) -> tuple[np.ndarray, dict[str, float]]:
    """
    Return (static_weights_array, cross_field_weights_dict) using live config.

    static_weights_array  — np.ndarray shape (40,) matching DIMENSION_NAMES order
    cross_field_weights   — dict { name: float } for the 4 cross-field checks

    Uses an async-safe in-memory cache.  Cache is invalidated on every
    successful PUT /internal/config/weights call.
    """
    global _weight_cache, _cache_loaded_at

    now = time.monotonic()
    if _weight_cache is not None and (now - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return _weight_cache["static"], _weight_cache["cross"]

    async with _cache_lock:
        # Double-check after acquiring lock
        now = time.monotonic()
        if _weight_cache is not None and (now - _cache_loaded_at) < CACHE_TTL_SECONDS:
            return _weight_cache["static"], _weight_cache["cross"]

        if pool is not None:
            weights = await _load_from_db(pool)
        else:
            weights = dict(ALL_DEFAULT_WEIGHTS)

        static = np.array(
            [weights.get(name, DEFAULT_DIMENSION_WEIGHTS[name]) for name in DIMENSION_NAMES],
            dtype=np.float64,
        )
        cross = {
            name: weights.get(name, DEFAULT_CROSS_FIELD_WEIGHTS[name])
            for name in CROSS_FIELD_NAMES
        }

        _weight_cache = {"static": static, "cross": cross, "raw": weights}
        _cache_loaded_at = now
        return static, cross


async def get_all_weights(pool) -> dict[str, float]:
    """Return complete weight dict (all 44 vectors) from cache/DB."""
    _, _ = await load_current_weights(pool)
    return dict(_weight_cache["raw"]) if _weight_cache else dict(ALL_DEFAULT_WEIGHTS)


async def get_weight_metadata(pool) -> dict:
    """Return summary metadata for the Config UI header card."""
    weights = await get_all_weights(pool)
    vals = list(weights.values())
    total = sum(vals)
    highest = max(weights, key=weights.get)
    lowest = min(weights, key=weights.get)

    # Fetch last-updated info from DB
    last_updated = None
    last_updated_by = "system"
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT updated_at, updated_by FROM model_configuration "
                "ORDER BY updated_at DESC LIMIT 1"
            )
            if row:
                last_updated = row["updated_at"].isoformat() if row["updated_at"] else None
                last_updated_by = row["updated_by"]
    except Exception:
        pass

    return {
        "total_vectors": len(weights),
        "weight_total": round(total, 4),
        "average_weight": round(total / max(len(vals), 1), 4),
        "highest_vector": highest,
        "highest_weight": round(weights[highest], 4),
        "lowest_vector": lowest,
        "lowest_weight": round(weights[lowest], 4),
        "last_updated": last_updated,
        "last_updated_by": last_updated_by,
        "is_default": all(
            abs(weights.get(n, 0) - ALL_DEFAULT_WEIGHTS[n]) < 1e-9
            for n in ALL_VECTOR_NAMES
        ),
    }


async def save_weights(
    pool,
    new_weights: dict[str, float],
    updated_by: str = "analyst",
) -> dict:
    """
    Validate, persist, and audit a new weight configuration.

    Validation rules:
      - All values must be in [0.0, 1.0]
      - All known vector names must be present
      - Unknown names are rejected

    Returns a summary dict on success.
    Raises ValueError on validation failure.
    """
    # --- Validate keys ---
    unknown = set(new_weights.keys()) - set(ALL_VECTOR_NAMES)
    if unknown:
        raise ValueError(f"Unknown vector names: {sorted(unknown)}")

    missing = set(ALL_VECTOR_NAMES) - set(new_weights.keys())
    if missing:
        raise ValueError(f"Missing vector names: {sorted(missing)}")

    # --- Validate values (every weight must be >= 0) ---
    for name, val in new_weights.items():
        if not isinstance(val, (int, float)):
            raise ValueError(f"Weight for '{name}' must be numeric, got {type(val)}")
        if val < 0.0:
            raise ValueError(f"Weight for '{name}' cannot be negative (got {val})")

    # --- Validate that weights sum to 1.0 (±0.001) ---
    total = sum(new_weights.values())
    if abs(total - 1.0) > 0.001:
        raise ValueError(
            f"Weights must sum to 1.000 (got {total:.6f}). "
            "Rebalance the weights in the UI before saving."
        )

    # --- Fetch current weights for audit log ---
    previous = await get_all_weights(pool)
    delta_parts = []
    for name in ALL_VECTOR_NAMES:
        old_v = previous.get(name, 0.0)
        new_v = new_weights[name]
        if abs(old_v - new_v) > 1e-6:
            delta_parts.append(f"{name}: {old_v:.4f} → {new_v:.4f}")

    delta_summary = "; ".join(delta_parts[:10])
    if len(delta_parts) > 10:
        delta_summary += f" (+{len(delta_parts)-10} more)"

    # --- Persist to PostgreSQL ---
    async with pool.acquire() as conn:
        async with conn.transaction():
            for name, val in new_weights.items():
                await conn.execute(
                    """
                    INSERT INTO model_configuration (vector_name, weight, updated_at, updated_by)
                    VALUES ($1, $2, NOW(), $3)
                    ON CONFLICT (vector_name) DO UPDATE SET
                        weight = EXCLUDED.weight,
                        updated_at = NOW(),
                        updated_by = EXCLUDED.updated_by
                    """,
                    name, float(val), updated_by,
                )

            # Write change log entry
            await conn.execute(
                """
                INSERT INTO weight_change_log
                    (changed_by, previous, updated, delta_summary)
                VALUES ($1, $2, $3, $4)
                """,
                updated_by,
                json.dumps({k: round(v, 6) for k, v in previous.items()}),
                json.dumps({k: round(v, 6) for k, v in new_weights.items()}),
                delta_summary or "no changes",
            )

    # --- Invalidate cache so scoring engine picks up new weights immediately ---
    invalidate_cache()

    logger.info(
        f"Weights updated by '{updated_by}': {len(delta_parts)} vectors changed. "
        f"{delta_summary}"
    )

    total = sum(new_weights.values())
    return {
        "saved": True,
        "total_weight": round(total, 4),
        "vectors_changed": len(delta_parts),
        "delta_summary": delta_summary or "no changes",
        "updated_by": updated_by,
    }


async def reset_to_defaults(pool, updated_by: str = "analyst") -> dict:
    """Reset all weights to the hardcoded defaults from weights.py."""
    return await save_weights(pool, ALL_DEFAULT_WEIGHTS, updated_by=updated_by + ":reset")
