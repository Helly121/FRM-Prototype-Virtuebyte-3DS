"""
report.py — Deviation report builder with reason templates.

Handles:
  - Tier assignment (TotalDeviation + IF score → LOW/MEDIUM/HIGH)
  - Contribution ranking and percentage calculation
  - Human-readable reason template-fill
  - Non-contributing context generation
"""

import uuid
from datetime import datetime, timezone
from typing import List

from .weights import (
    STATIC_WEIGHTS,
    CROSS_FIELD_WEIGHTS,
    DIMENSION_NAMES,
    DIMENSION_TO_FIELD,
    TIER_HIGH_DEVIATION,
    TIER_MED_DEVIATION,
    IF_HIGH_THRESHOLD,
    IF_MED_THRESHOLD,
    CONTRIBUTION_MIN_PCT,
    NUM_DIMENSIONS,
)
from .schemas import ContributingFactor, DeviationReport


# ---------------------------------------------------------------------------
# Reason Templates
# ---------------------------------------------------------------------------

REASON_TEMPLATES = {
    "s_acct_type": (
        "Account type is '{observed}', but this card has historically used "
        "'{expected}' in {pct:.0f}% of transactions."
    ),
    "s_mcc": (
        "Merchant category code '{observed}' is unusual for this card. "
        "Most common category: '{expected}'."
    ),
    "s_merchant_country": (
        "Transaction from country '{observed}' is uncommon. "
        "This card primarily transacts in '{expected}'."
    ),
    "s_amount": (
        "Transaction amount {observed} deviates significantly from this card's "
        "historical spending range (z-score: {score:.1f})."
    ),
    "s_currency": (
        "Currency '{observed}' is unusual for this card. "
        "Most common currency: '{expected}'."
    ),
    "s_temporal": (
        "Transaction at {observed} is outside this card's typical activity window."
    ),
    "s_cvv_status": (
        "Card security code status '{observed}' deviates from historical match rate "
        "of {expected}."
    ),
    "s_requestor_id": (
        "3DS Requestor '{observed}' is not in this card's known requestor set."
    ),
    "s_requestor_url": (
        "Requestor URL '{observed}' is not recognised for this card."
    ),
    "s_auth_ind": (
        "Authentication indicator '{observed}' is unusual. "
        "Most common: '{expected}'."
    ),
    "s_auth_method": (
        "Authentication method '{observed}' is unusual. "
        "Most common: '{expected}'."
    ),
    "s_ch_acc_age_regression": (
        "Account age indicator has decreased from '{expected}' to '{observed}'. "
        "Account age should only increase monotonically; a decrease suggests "
        "a data inconsistency or different account context."
    ),
    "s_ch_acc_change": (
        "Account change indicator '{observed}' shows a sudden change "
        "compared to historical EWMA of {expected}."
    ),
    "s_pw_change": (
        "Password change indicator '{observed}' shows a sudden change "
        "compared to historical EWMA of {expected}."
    ),
    "s_txn_vel_day": (
        "Daily transaction velocity ({observed}) is significantly above "
        "this card's historical average."
    ),
    "s_txn_vel_year": (
        "Yearly transaction count ({observed}) deviates from "
        "this card's historical average."
    ),
    "s_provision_attempts": (
        "{observed} payment account provisioning attempts today. "
        "This card has {expected} history of same-day provisioning activity."
    ),
    "s_nb_purchase": (
        "Purchase count ({observed}) deviates from this card's "
        "historical average."
    ),
    "s_suspicious": (
        "Merchant has flagged suspicious account activity for this card. "
        "This is a direct high-weight signal."
    ),
    "s_ship_name_match": (
        "Shipping name match indicator '{observed}' deviates from "
        "historical match rate of {expected}."
    ),
    "s_merchant_id": (
        "Merchant '{observed}' is not in this card's known merchant set."
    ),
    "s_acquirer_bin": (
        "Acquirer BIN '{observed}' is not in this card's known set."
    ),
    "s_ship_indicator": (
        "Shipping indicator '{observed}' is unusual. "
        "Most common: '{expected}'."
    ),
    "s_billing_addr_hash": (
        "Billing address has changed. New address hash ({observed}) "
        "is not among the {expected}."
    ),
    "s_shipping_addr_hash": (
        "Shipping address ({observed}) is new and not in the "
        "{expected}."
    ),
    "s_email_hash": (
        "Email address is new. Not among the {expected}."
    ),
    "s_phone_hash": (
        "Phone number (ending {observed}) is new. "
        "Not among the {expected}."
    ),
    "s_platform": (
        "Platform changed to '{observed}'. This card has historically used "
        "'{expected}' for authentication."
    ),
    "s_device_model": (
        "Device model '{observed}' is unusual for this card. "
        "Most common: '{expected}'."
    ),
    "s_os_name": (
        "OS '{observed}' is unusual for this card. "
        "Most common: '{expected}'."
    ),
    "s_os_version": (
        "OS version '{observed}' is unusual. Most common: '{expected}'. "
        "Version downgrades are penalised more heavily."
    ),
    "s_locale": (
        "Locale '{observed}' is unusual for this card. "
        "Most common: '{expected}'."
    ),
    "s_timezone": (
        "Time zone '{observed}' is not in this card's known set ({expected})."
    ),
    "s_screen_res": (
        "Screen resolution '{observed}' is not in this card's known set ({expected})."
    ),
    "s_ip_subnet": (
        "IP subnet '{observed}' is not in this card's known set ({expected})."
    ),
    "s_gps_billing_dist": (
        "Device GPS location is {observed}, far from the historical "
        "centroid ({expected})."
    ),
    "s_app_package": (
        "The application performing 3DS authentication ({observed}) is not "
        "the package previously associated with this card ({expected}). "
        "This may indicate the SDK is embedded in a different or tampered application."
    ),
    "s_sdk_ref_tamper": (
        "SDK Reference Number hash ({observed}) does not match the expected "
        "hash. This is a potential tampering indicator."
    ),
    "s_sdk_version": (
        "SDK version '{observed}' is not in this card's known set. "
        "Most common: '{expected}'."
    ),
    "s_device_fp_composite": (
        "Device fingerprint ({observed}) is new. "
        "Not among {expected}."
    ),
    "s_clock_skew": (
        "Device-reported time and purchase timestamp differ by more than 5 minutes. "
        "This may indicate clock manipulation or replay."
    ),
    "s_platform_os_coherence": (
        "Platform and OS Name are incoherent — the reported platform does not "
        "match the OS. This is a strong spoofing indicator."
    ),
    "s_velocity_crosscheck": (
        "Daily transaction velocity is disproportionately high relative to "
        "yearly activity. This may indicate a burst of fraudulent activity."
    ),
    "s_new_shipping_context": (
        "Shipping address is new and not seen in this card's history."
    ),
}

# Non-contributing context templates
NON_CONTRIBUTING_TEMPLATES = {
    "s_requestor_id": "3DS Requestor is a known and trusted entity for this card.",
    "s_merchant_country": "Merchant country code is within this card's established usage.",
    "s_temporal": "Transaction timestamp is within normal hours for this card.",
    "s_amount": "Transaction amount is within the expected range for this card.",
    "s_platform": "Device platform matches this card's historical pattern.",
    "s_app_package": "Application package is recognised for this card.",
    "s_gps_billing_dist": "Device location is within the expected geographic area.",
    "s_billing_addr_hash": "Billing address matches a known address for this card.",
    "s_email_hash": "Email address is recognised for this card.",
    "s_cvv_status": "Card security code verification is consistent with history.",
}


# ---------------------------------------------------------------------------
# Tier Assignment
# ---------------------------------------------------------------------------

def assign_tier(total_deviation: float, if_score: float) -> str:
    """
    Assign deviation tier based on TotalDeviation and IF score.
    Either signal alone can escalate the tier.
    """
    if total_deviation >= TIER_HIGH_DEVIATION or if_score <= IF_HIGH_THRESHOLD:
        return "HIGH"
    if total_deviation >= TIER_MED_DEVIATION or if_score <= IF_MED_THRESHOLD:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Report Builder
# ---------------------------------------------------------------------------

def build_report(
    payload: dict,
    surprise_vector,
    contributions: dict,
    cross_field_scores: dict,
    if_score: float,
    profile: dict,
    scoring_start_ms: float,
) -> DeviationReport:
    """
    Build the full DeviationReport from scoring results.

    Steps:
      1. Compute TotalDeviation as weighted sum
      2. Add cross-field weighted contributions
      3. Assign tier
      4. Rank contributions by W_i × s_i descending
      5. Suppress factors below CONTRIBUTION_MIN_PCT
      6. Template-fill human-readable reasons
    """
    import time
    import numpy as np

    meta = profile.get("_meta", {})

    # 1. Weighted sum of 40-dim vector
    weighted_scores = {}
    for i, dim_name in enumerate(DIMENSION_NAMES):
        w = float(STATIC_WEIGHTS[i])
        s = float(surprise_vector[i])
        weighted_scores[dim_name] = w * s

    # 2. Add cross-field weighted contributions
    for cf_name, cf_data in cross_field_scores.items():
        w = CROSS_FIELD_WEIGHTS.get(cf_name, 0.0)
        if isinstance(cf_data, dict):
            raw_score = float(cf_data.get("score", 0.0))
            contributions[cf_name] = cf_data
        else:
            raw_score = float(cf_data)
        weighted_scores[cf_name] = w * raw_score

    total_deviation = sum(weighted_scores.values())

    # 3. Tier assignment
    tier = assign_tier(total_deviation, if_score)

    # 4. Rank contributions
    sorted_contribs = sorted(
        weighted_scores.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )

    # 5. Build contributing factors and non-contributing context
    contributing_factors: List[ContributingFactor] = []
    non_contributing_context: List[str] = []
    num_contributing = 0

    for dim_name, weighted_val in sorted_contribs:
        # Calculate contribution percentage
        pct = (weighted_val / max(total_deviation, 1e-9)) * 100.0

        if weighted_val > 0 and pct >= CONTRIBUTION_MIN_PCT:
            num_contributing += 1
            # Get observed/expected from contributions dict
            detail = contributions.get(dim_name, {})
            observed = detail.get("observed", "")
            expected = detail.get("expected", "")
            raw_score = detail.get("score", 0.0)

            # Template-fill reason
            template = REASON_TEMPLATES.get(dim_name, f"{dim_name} deviates from profile.")
            try:
                reason = template.format(
                    observed=observed,
                    expected=expected,
                    score=raw_score,
                    pct=pct,
                )
            except (KeyError, IndexError):
                reason = f"{dim_name}: observed={observed}, expected={expected}"

            raw_observed = detail.get("raw_observed")

            contributing_factors.append(ContributingFactor(
                field=DIMENSION_TO_FIELD.get(dim_name, dim_name),
                dimension=dim_name,
                observed=str(observed),
                raw_observed=str(raw_observed) if raw_observed is not None else None,
                expected=str(expected),
                contribution_pct=round(pct, 1),
                reason=reason,
            ))
        else:
            # Non-contributing — add context if we have a template
            ctx = NON_CONTRIBUTING_TEMPLATES.get(dim_name)
            if ctx and weighted_val <= 0:
                non_contributing_context.append(ctx)

    # Limit non-contributing context to most relevant
    non_contributing_context = non_contributing_context[:5]

    # Summary
    summary = (
        f"{num_contributing} of {NUM_DIMENSIONS} scored attribute dimensions "
        f"deviate from this card's established behavior."
    )

    scoring_latency_ms = round((time.time() * 1000) - scoring_start_ms, 1)

    return DeviationReport(
        transaction_id=f"txn_{uuid.uuid4().hex[:8]}",
        card_id=payload.get("card_id_hash", "unknown"),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        channel="SDK",
        deviation_tier=tier,
        profile_confidence=round(meta.get("profile_confidence", 0.0), 2),
        total_deviation=round(total_deviation, 4),
        if_score=round(if_score, 4),
        summary=summary,
        contributing_factors=contributing_factors,
        non_contributing_context=non_contributing_context,
        metadata={
            "profile_history_depth_days": round(
                meta.get("history_depth_days", 0), 1
            ),
            "total_historical_authentications": meta.get("transaction_count", 0),
            "scoring_latency_ms": scoring_latency_ms,
            "weight_set_version": "v1.0-static",
            "model_version": "isolation_forest_v1",
            "profile_confidence": round(meta.get("profile_confidence", 0.0), 2),
        },
    )
