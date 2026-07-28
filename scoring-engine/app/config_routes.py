"""
config_routes.py — REST endpoints for Model Configuration (Issue #3).

Endpoints
---------
GET  /internal/config/weights          — return all 44 weights + metadata
PUT  /internal/config/weights          — update weights, invalidate cache
GET  /internal/config/weights/history  — last N weight change log entries
POST /internal/config/weights/reset    — reset to defaults

The router is mounted in main.py with:
    app.include_router(config_router)
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional

from .config_service import (
    get_all_weights,
    get_weight_metadata,
    save_weights,
    reset_to_defaults,
    ALL_DEFAULT_WEIGHTS,
    ALL_VECTOR_NAMES,
)

config_router = APIRouter(tags=["Model Configuration"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WeightsPayload(BaseModel):
    """
    Full weight map for PUT /internal/config/weights.
    All 44 vector names must be present; values must be in [0.0, 1.0].
    """
    weights: dict[str, float] = Field(
        ...,
        description="Map of vector_name → weight (0.0–1.0) for all 44 vectors",
    )
    updated_by: Optional[str] = Field(
        "analyst",
        description="Identifier of the user or system making this change",
        max_length=128,
    )


class WeightResetRequest(BaseModel):
    updated_by: Optional[str] = Field("analyst", max_length=128)
    confirm: bool = Field(
        False,
        description="Must be true to execute the reset",
    )


# ---------------------------------------------------------------------------
# GET /internal/config/weights
# ---------------------------------------------------------------------------

@config_router.get(
    "/internal/config/weights",
    summary="Get current surprise vector weights",
    description="""
Returns all 44 configurable weight values (40 surprise-vector dimensions +
4 cross-field checks) along with metadata for the configuration dashboard.

The scoring engine reads these weights on every transaction. Changes take
effect immediately after a successful PUT call — no restart required.
    """,
)
async def get_weights(request: Request):
    pool = request.app.state.pg_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    weights = await get_all_weights(pool)
    metadata = await get_weight_metadata(pool)
    defaults = ALL_DEFAULT_WEIGHTS

    return {
        "weights": {k: round(v, 6) for k, v in weights.items()},
        "defaults": {k: round(v, 6) for k, v in defaults.items()},
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# PUT /internal/config/weights
# ---------------------------------------------------------------------------

@config_router.put(
    "/internal/config/weights",
    summary="Update surprise vector weights",
    description="""
Updates all 44 weight values in PostgreSQL and immediately invalidates the
in-memory weight cache. The scoring engine will use the new weights on the
next transaction scored — no restart required.

Validation:
- All 44 vector names must be present
- Each weight must be in the range [0.0, 1.0]
- Unknown vector names are rejected with 422
    """,
)
async def update_weights(payload: WeightsPayload, request: Request):
    pool = request.app.state.pg_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    try:
        result = await save_weights(
            pool,
            payload.weights,
            updated_by=payload.updated_by or "analyst",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save weights: {e}")

    return result


# ---------------------------------------------------------------------------
# POST /internal/config/weights/reset
# ---------------------------------------------------------------------------

@config_router.post(
    "/internal/config/weights/reset",
    summary="Reset weights to factory defaults",
    description="""
Restores all 44 weights to the original expert-calibrated defaults
defined in weights.py. A confirmation flag is required.
    """,
)
async def reset_weights(payload: WeightResetRequest, request: Request):
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set 'confirm: true' to execute the reset",
        )

    pool = request.app.state.pg_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    try:
        result = await reset_to_defaults(
            pool,
            updated_by=payload.updated_by or "analyst",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")

    return result


# ---------------------------------------------------------------------------
# GET /internal/config/weights/history
# ---------------------------------------------------------------------------

@config_router.get(
    "/internal/config/weights/history",
    summary="Weight change audit trail",
    description="""
Returns the N most recent weight configuration changes with before/after
snapshots. Useful for auditing who changed what and when.
    """,
)
async def get_weight_history(request: Request, limit: int = 20):
    pool = request.app.state.pg_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, changed_at, changed_by, delta_summary
                FROM weight_change_log
                ORDER BY changed_at DESC
                LIMIT $1
                """,
                min(limit, 100),
            )
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History query failed: {e}")
