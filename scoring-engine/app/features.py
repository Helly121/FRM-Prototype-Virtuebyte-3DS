"""
features.py — Single source of truth for all feature computation logic.

This module is used by BOTH the offline training pipeline and the real-time
scoring engine. Any change here automatically affects both, ensuring
train/serve parity (§14 trade-off).

Implements all scoring formulas from §5 of the system design:
  §5.1 — Categorical surprise (Laplace-smoothed self-information)
  §5.2 — Amount surprise (Z-score on log-transformed amount)
  §5.3 — Temporal surprise (histogram density)
  §5.4 — Geolocation surprise (Haversine to centroid)
  §5.5 — Known/Unknown sets (identity novelty)
  §5.6 — acctInfo regression & velocity checks
  §5.7 — Cross-field consistency checks
"""

import math
import hashlib
import numpy as np
from datetime import datetime, timezone
from typing import Optional

from .weights import (
    LAPLACE_ALPHA,
    HIGH_WEIGHT,
    VERY_HIGH_WEIGHT,
    HIGH_WEIGHT_CONSTANT,
    TAMPER_FLAG_WEIGHT,
    REGRESSION_PENALTY,
    CLOCK_SKEW_THRESHOLD_S,
    GEO_MIN_RADIUS_KM,
    COLD_START_CONFIDENCE_THRESHOLD,
    STATIC_WEIGHTS,
    CROSS_FIELD_WEIGHTS,
    NUM_DIMENSIONS,
    DIMENSION_NAMES,
)


# ---------------------------------------------------------------------------
# §5.1 — Categorical Fields — Laplace-Smoothed Self-Information
# ---------------------------------------------------------------------------

def surprise_categorical(observed: str, freq_dict: dict,
                         alpha: float = LAPLACE_ALPHA) -> float:
    """
    Returns surprise in bits. 0 = perfectly expected. ~3-5 = never seen before.
    
    Applied to: acctType, mcc, merchantCountryCode, purchaseCurrency,
    threeDSRequestorAuthenticationInd, threeDSReqAuthMethod, shipIndicator,
    Platform, Device Model, OS Name, Locale.
    """
    if not freq_dict:
        return 0.0  # No history — can't compute surprise
        
    # Prevent Laplace smoothing from artificially flagging the exact baseline behavior
    if observed == max(freq_dict, key=freq_dict.get):
        return 0.0
        
    total = sum(freq_dict.values()) + alpha * max(len(freq_dict), 1)
    p_hat = (freq_dict.get(observed, 0.0) + alpha) / total
    return -math.log2(max(p_hat, 1e-12))


# ---------------------------------------------------------------------------
# §5.2 — Purchase Amount — Z-Score on Log-Transformed Amount
# ---------------------------------------------------------------------------

def surprise_amount(amount: float, ewma_log: float,
                    ewma_var: float) -> float:
    """
    Log-transform handles right-skew. Returns absolute z-score.
    Both unusually high and unusually low amounts are flagged.
    """
    if ewma_var <= 0 and ewma_log <= 0:
        return 0.0  # No history
    log_amount = math.log1p(max(amount, 0))
    std = math.sqrt(max(ewma_var, 1e-6))
    z = abs(log_amount - ewma_log) / std
    return z


# ---------------------------------------------------------------------------
# §5.3 — Temporal Histogram — Density Surprise
# ---------------------------------------------------------------------------

def surprise_temporal(purchase_dt: datetime,
                      hour_hist: list, dow_hist: list) -> float:
    """
    Surprise from hour-of-day and day-of-week histograms.
    Returns average of two temporal signals.
    """
    if not hour_hist or not dow_hist:
        return 0.0

    hour = purchase_dt.hour
    dow = purchase_dt.weekday()  # 0=Monday, 6=Sunday

    h_density = max(hour_hist[hour], 1e-4)
    d_density = max(dow_hist[dow], 1e-4)

    s_hour = -math.log2(h_density)
    s_dow = -math.log2(d_density)
    return (s_hour + s_dow) / 2.0


# ---------------------------------------------------------------------------
# §5.4 — Geolocation — Haversine to Centroid
# ---------------------------------------------------------------------------

def haversine(lat1: float, lon1: float,
              lat2: float, lon2: float) -> float:
    """
    Returns distance in kilometres between two GPS coordinates.
    Uses the Haversine formula.
    """
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def surprise_geo(obs_lat: float, obs_lon: float,
                 centroid_lat: float, centroid_lon: float,
                 typical_radius_km: float,
                 min_radius_km: float = GEO_MIN_RADIUS_KM) -> float:
    """
    Log-scaled distance surprise. z=1→0.69, z=3→1.39, z=10→2.40.
    """
    if centroid_lat == 0.0 and centroid_lon == 0.0:
        return 0.0  # No centroid established
    distance_km = haversine(obs_lat, obs_lon, centroid_lat, centroid_lon)
    radius = max(typical_radius_km, min_radius_km)
    z = distance_km / radius
    return math.log1p(z)


# ---------------------------------------------------------------------------
# §5.5 — Known / Unknown Sets — Identity Novelty
# ---------------------------------------------------------------------------

def surprise_known_unknown(observed_hash: str, known_set: list,
                           stability: Optional[float] = None) -> float:
    """
    Returns 0 if hash is known, or a stability-weighted surprise if unknown.
    A card with many known IDs is penalised less for a new one.
    """
    if not observed_hash:
        return 0.0
    if observed_hash in known_set:
        return 0.0
    if stability is None:
        stability = 1.0 / max(len(known_set), 1)
    return -math.log2(max(stability, 1e-9))


def surprise_app_package(observed_hash: str, known_packages: list) -> float:
    """
    Special case: unknown app package gets a direct HIGH_WEIGHT_CONSTANT (4.0).
    A different app performing 3DS auth is an integrity concern.
    """
    if not observed_hash:
        return 0.0
    if observed_hash in known_packages:
        return 0.0
    return HIGH_WEIGHT_CONSTANT


def surprise_sdk_ref(observed_hash: str, expected_hash: str) -> float:
    """
    Special case: SDK Ref Number tamper detection.
    Returns TAMPER_FLAG_WEIGHT (5.0) if hash doesn't match.
    """
    if not observed_hash or not expected_hash:
        return 0.0
    if observed_hash != expected_hash:
        return TAMPER_FLAG_WEIGHT
    return 0.0


# ---------------------------------------------------------------------------
# §5.6 — acctInfo — Regression and Velocity Checks
# ---------------------------------------------------------------------------

def z_score(x: float, mean: float, var: float) -> float:
    """Compute absolute z-score with variance floor."""
    return abs(x - mean) / max(math.sqrt(max(var, 0)), 0.01)


def score_acct_info(payload: dict, profile_requestor: dict) -> dict:
    """
    Computes acctInfo surprise scores:
    - Regression detection (ordered-categorical fields that should only increase)
    - Velocity Z-scores
    - Provision attempts spike detection
    - Suspicious activity sticky flag
    """
    scores = {}

    # --- Regression check (chAccAgeInd should only increase) ---
    observed_age = int(payload.get("chAccAgeInd", "05") or "05")
    last_age = int(profile_requestor.get("ch_acc_age_ind_last", observed_age))
    if observed_age < last_age:
        scores["s_ch_acc_age_regression"] = REGRESSION_PENALTY * (last_age - observed_age)
    else:
        scores["s_ch_acc_age_regression"] = 0.0

    # --- EWMA deviation for chAccChangeInd ---
    observed_change = int(payload.get("chAccChangeInd", "01") or "01")
    ewma_change = profile_requestor.get("ch_acc_change_ind_ewma", float(observed_change))
    scores["s_ch_acc_change"] = abs(observed_change - ewma_change)

    # --- EWMA deviation for chAccPwChangeInd ---
    observed_pw = int(payload.get("chAccPwChangeInd", "01") or "01")
    ewma_pw = profile_requestor.get("ch_acc_pw_change_ind_ewma", float(observed_pw))
    scores["s_pw_change"] = abs(observed_pw - ewma_pw)

    # --- Velocity Z-scores ---
    txn_day = float(payload.get("txnActivityDay", 0) or 0)
    z_day = z_score(
        txn_day,
        profile_requestor.get("txn_activity_day_ewma", 0.0),
        profile_requestor.get("txn_activity_day_var", 1.0),
    )
    scores["s_txn_vel_day"] = max(0.0, z_day - 2.0)

    txn_year = float(payload.get("txnActivityYear", 0) or 0)
    z_year = z_score(
        txn_year,
        profile_requestor.get("txn_activity_year_ewma", 0.0),
        profile_requestor.get("txn_activity_year_var", 1.0),
    )
    scores["s_txn_vel_year"] = max(0.0, z_year - 2.0)

    nb_purchase = float(payload.get("nbPurchaseAccount", 0) or 0)
    z_nb = z_score(
        nb_purchase,
        profile_requestor.get("nb_purchase_ewma", 0.0),
        profile_requestor.get("nb_purchase_var", 1.0),
    )
    scores["s_nb_purchase"] = max(0.0, z_nb - 2.0)

    # --- Provision attempts: any non-zero on a clean card is a direct flag ---
    prov = float(payload.get("provisionAttemptsDay", 0) or 0)
    if prov > 0 and profile_requestor.get("provision_attempts_ewma", 0) < 0.1:
        scores["s_provision_attempts"] = HIGH_WEIGHT
    else:
        z_prov = z_score(
            prov,
            profile_requestor.get("provision_attempts_ewma", 0.0),
            profile_requestor.get("provision_attempts_var", 0.5),
        )
        scores["s_provision_attempts"] = max(0.0, z_prov - 2.0)

    # --- Suspicious activity — sticky flag ---
    if str(payload.get("suspiciousAccActivity", "02")) == "01":
        scores["s_suspicious"] = VERY_HIGH_WEIGHT
    else:
        scores["s_suspicious"] = 0.0

    # --- Ship name match rate deviation ---
    ship_match = 1.0 if str(payload.get("shipNameIndicator", "01")) == "01" else 0.0
    hist_rate = profile_requestor.get("ship_name_match_rate", 1.0)
    scores["s_ship_name_match"] = abs(ship_match - hist_rate) * 3.0  # Scale for interpretability

    return scores


# ---------------------------------------------------------------------------
# §5.7 — Cross-Field Consistency Checks
# ---------------------------------------------------------------------------

def sha256_str(s: str) -> str:
    """SHA-256 hash of a string, returned as hex digest."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def parse_dt(dt_str) -> datetime:
    """Parse an ISO datetime string or return the datetime if already parsed."""
    if isinstance(dt_str, datetime):
        return dt_str
    if not dt_str:
        return datetime.now(timezone.utc)
    try:
        # Handle various ISO formats
        dt_str = str(dt_str).strip()
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def cross_field_checks(payload: dict, profile: dict, blocklist_hits: list = None) -> dict:
    """
    Cross-field consistency checks producing additional surprise dimensions.
    These are added to TotalDeviation but NOT included in the IF vector.
    """
    checks = {}
    
    if blocklist_hits:
        checks["s_global_blocklist"] = {
            "score": 10.0 * len(blocklist_hits), # Severe penalty
            "observed": f"Hit: {', '.join(blocklist_hits)}",
            "expected": "No global blocklist matches",
        }

    # 1. Clock skew (dateTime vs purchaseDate)
    device_dt = parse_dt(payload.get("dateTime"))
    purchase_dt = parse_dt(payload.get("purchaseDate"))
    skew_s = abs((device_dt - purchase_dt).total_seconds())
    score = 5.0 if skew_s > CLOCK_SKEW_THRESHOLD_S else 0.0
    checks["s_clock_skew"] = {
        "score": score,
        "observed": f"{skew_s:.0f}s skew",
        "expected": f"<= {CLOCK_SKEW_THRESHOLD_S}s",
    }

    # 2. Platform ↔ OS Name coherence
    platform = str(payload.get("Platform", "")).lower()
    os_name = str(payload.get("OS_Name", payload.get("OSName", ""))).lower()
    incoherent = (
        ("android" in platform and "ios" in os_name) or
        ("ios" in platform and "android" in os_name)
    )
    checks["s_platform_os_coherence"] = {
        "score": 5.0 if incoherent else 0.0,
        "observed": f"{platform} with {os_name}",
        "expected": "Matching OS and Platform",
    }

    # 3. GPS vs billing centroid distance
    try:
        obs_lat = float(payload.get("Latitude", 0) or 0)
        obs_lon = float(payload.get("Longitude", 0) or 0)
        merchant = profile.get("merchant", {})
        score = surprise_geo(
            obs_lat, obs_lon,
            merchant.get("billing_lat", 0.0),
            merchant.get("billing_lon", 0.0),
            merchant.get("billing_radius_km", GEO_MIN_RADIUS_KM),
        )
        checks["s_gps_billing_dist"] = {
            "score": score,
            "observed": f"({obs_lat}, {obs_lon})",
            "expected": f"billing_centroid=({merchant.get('billing_lat', 0.0)}, {merchant.get('billing_lon', 0.0)})",
        }
    except (TypeError, ValueError):
        checks["s_gps_billing_dist"] = {"score": 0.0, "observed": "N/A", "expected": "N/A"}

    # 4. txnActivityDay vs txnActivityYear cross-validation
    txn_year = float(payload.get("txnActivityYear", 0) or 0)
    txn_day = float(payload.get("txnActivityDay", 0) or 0)
    score = 0.0
    daily_rate = 0.0
    if txn_year > 0:
        daily_rate = txn_year / 365
        if txn_day > max(3.0, daily_rate * 3):
            score = 2.0
            
    checks["s_velocity_crosscheck"] = {
        "score": score,
        "observed": f"{txn_day} txns/day",
        "expected": f"<= max(3, {daily_rate*3:.1f}) based on yearly rate",
    }

    # 5. Shipping address hash vs billing (new-address signal)
    ship_city = str(payload.get("shipAddrCity", "") or "")
    ship_country = str(payload.get("shipAddrCountry", "") or "")
    if ship_city or ship_country:
        ship_hash = sha256_str(f"{ship_city}|{ship_country}")
        score = surprise_known_unknown(
            ship_hash,
            profile.get("merchant", {}).get("shipping_addr_hashes", []),
        )
        checks["s_new_shipping_context"] = {
            "score": score,
            "observed": "New shipping address",
            "expected": "Known shipping address",
        }
    else:
        checks["s_new_shipping_context"] = {"score": 0.0, "observed": "N/A", "expected": "N/A"}

    return checks


# ---------------------------------------------------------------------------
# CVV Status Surprise
# ---------------------------------------------------------------------------

def surprise_cvv_status(observed: str, ewma_match_rate: float) -> float:
    """
    CVV match rate deviation. '01' = match. Deviation from EWMA match rate.
    """
    is_match = 1.0 if str(observed) == "01" else 0.0
    return abs(is_match - ewma_match_rate) * 3.0  # Scale for interpretability


# ---------------------------------------------------------------------------
# Device Fingerprint Composite
# ---------------------------------------------------------------------------

def compute_device_fp_hash(payload: dict) -> str:
    """
    Composite device fingerprint = hash(Platform + DeviceModel + OSVersion + AppPackage).
    """
    parts = [
        str(payload.get("Platform", "")),
        str(payload.get("DeviceModel", payload.get("Device Model", ""))),
        str(payload.get("OSVersion", payload.get("OS Version", ""))),
        str(payload.get("ApplicationPackageName",
                        payload.get("Application Package Name", ""))),
    ]
    return sha256_str("|".join(parts))


# ---------------------------------------------------------------------------
# IP Subnet extraction
# ---------------------------------------------------------------------------

def extract_ip_subnet(ip_address: str) -> str:
    """Extract /24 subnet from an IPv4 address."""
    if not ip_address:
        return ""
    parts = ip_address.split(".")
    if len(parts) >= 3:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    return ip_address


# ---------------------------------------------------------------------------
# Billing address composite hash
# ---------------------------------------------------------------------------

def compute_billing_addr_hash(payload: dict) -> str:
    """SHA-256 of normalised billing address composite."""
    parts = [
        str(payload.get("billAddrLine1", "") or "").strip().lower(),
        str(payload.get("billAddrCity", "") or "").strip().lower(),
        str(payload.get("billAddrCountry", "") or "").strip().lower(),
        str(payload.get("billAddrPostCode", "") or "").strip().lower(),
    ]
    return sha256_str("|".join(parts))


def compute_shipping_addr_hash(payload: dict) -> str:
    """SHA-256 of normalised shipping address composite."""
    parts = [
        str(payload.get("shipAddrCity", "") or "").strip().lower(),
        str(payload.get("shipAddrCountry", "") or "").strip().lower(),
    ]
    return sha256_str("|".join(parts))


# ---------------------------------------------------------------------------
# OS Version direction check
# ---------------------------------------------------------------------------

def surprise_os_version(observed: str, freq_dict: dict) -> float:
    """
    Known/Unknown + asymmetric: downgrade penalised more than upgrade.
    """
    base_surprise = surprise_categorical(observed, freq_dict)
    if not freq_dict or observed in freq_dict:
        return base_surprise

    # Check if this is a downgrade
    try:
        obs_ver = float(observed)
        known_versions = [float(v) for v in freq_dict.keys()
                          if v.replace(".", "").isdigit()]
        if known_versions and obs_ver < max(known_versions):
            return base_surprise * 1.5  # 50% extra penalty for downgrade
    except (ValueError, TypeError):
        pass
    return base_surprise


# ---------------------------------------------------------------------------
# Main Orchestrator — Extract & Score
# ---------------------------------------------------------------------------

def extract_and_score(payload: dict, profile: dict, blocklist_hits: list = None) -> tuple:
    """
    Compute the full 40-dimensional surprise vector and per-dimension
    contribution mapping.

    Returns:
        surprise_vector: np.ndarray of shape (40,)
        contributions: dict mapping dimension name → {score, observed, expected}
        cross_field_scores: dict from cross_field_checks()
    """
    txn = profile.get("transaction", {})
    req = profile.get("requestor", {})
    mer = profile.get("merchant", {})
    dev = profile.get("device", {})
    meta = profile.get("_meta", {})

    surprise = np.zeros(NUM_DIMENSIONS, dtype=np.float64)
    contributions = {}

    # ---- Transaction Details (dims 0–6) ----

    # 0: s_acct_type
    val = str(payload.get("acctType", "01"))
    s = surprise_categorical(val, txn.get("acct_type_freq", {}))
    surprise[0] = s
    contributions["s_acct_type"] = {
        "score": s, "observed": val,
        "expected": _top_key(txn.get("acct_type_freq", {})),
    }

    # 1: s_mcc
    val = str(payload.get("mcc", ""))
    s = surprise_categorical(val, txn.get("mcc_freq", {}))
    surprise[1] = s
    contributions["s_mcc"] = {
        "score": s, "observed": val,
        "expected": _top_key(txn.get("mcc_freq", {})),
    }

    # 2: s_merchant_country
    val = str(payload.get("merchantCountryCode", ""))
    s = surprise_categorical(val, txn.get("country_freq", {}))
    surprise[2] = s
    contributions["s_merchant_country"] = {
        "score": s, "observed": val,
        "expected": _top_key(txn.get("country_freq", {})),
    }

    # 3: s_amount
    amount = float(payload.get("purchaseAmount", 0) or 0)
    s = surprise_amount(
        amount,
        txn.get("amount_ewma_log", 0.0),
        txn.get("amount_ewma_var", 1.0),
    )
    surprise[3] = s
    contributions["s_amount"] = {
        "score": s, "observed": f"{amount:.2f}",
        "expected": f"EWMA log={txn.get('amount_ewma_log', 0):.2f}",
    }

    # 4: s_currency
    val = str(payload.get("purchaseCurrency", ""))
    s = surprise_categorical(val, txn.get("currency_freq", {}))
    surprise[4] = s
    contributions["s_currency"] = {
        "score": s, "observed": val,
        "expected": _top_key(txn.get("currency_freq", {})),
    }

    # 5: s_temporal
    purchase_dt = parse_dt(payload.get("purchaseDate"))
    s = surprise_temporal(
        purchase_dt,
        txn.get("hour_hist", []),
        txn.get("dow_hist", []),
    )
    surprise[5] = s
    contributions["s_temporal"] = {
        "score": s,
        "observed": f"hour={purchase_dt.hour}, dow={purchase_dt.weekday()}",
        "expected": "histogram-based density",
    }

    # 6: s_cvv_status
    val = str(payload.get("cardSecurityCodeStatus", "01"))
    s = surprise_cvv_status(val, txn.get("cvv_match_rate", 1.0))
    surprise[6] = s
    contributions["s_cvv_status"] = {
        "score": s, "observed": val,
        "expected": f"match_rate={txn.get('cvv_match_rate', 1.0):.2f}",
    }

    # ---- Requestor Details (dims 7–10) ----

    # 7: s_requestor_id
    val = str(payload.get("threeDSRequestorID", ""))
    known_req = req.get("known_requestors", {})
    s = surprise_known_unknown(val, list(known_req.keys()))
    surprise[7] = s
    contributions["s_requestor_id"] = {
        "score": s, "observed": val,
        "expected": f"known set: {list(known_req.keys())[:3]}",
    }

    # 8: s_requestor_url
    val = str(payload.get("threeDSRequestorURL", ""))
    url_hash = sha256_str(val) if val else ""
    s = surprise_known_unknown(url_hash, req.get("known_req_urls", []))
    surprise[8] = s
    contributions["s_requestor_url"] = {
        "score": s, "observed": val[:50],
        "expected": "known URL set",
    }

    # 9: s_auth_ind
    val = str(payload.get("threeDSRequestorAuthenticationInd", "01"))
    s = surprise_categorical(val, req.get("auth_ind_freq", {}))
    surprise[9] = s
    contributions["s_auth_ind"] = {
        "score": s, "observed": val,
        "expected": _top_key(req.get("auth_ind_freq", {})),
    }

    # 10: s_auth_method
    val = str(payload.get("threeDSReqAuthMethod", ""))
    s = surprise_categorical(val, req.get("auth_method_freq", {}))
    surprise[10] = s
    contributions["s_auth_method"] = {
        "score": s, "observed": val,
        "expected": _top_key(req.get("auth_method_freq", {})),
    }

    # ---- AcctInfo (dims 11–19) ----
    acctinfo_scores = score_acct_info(payload, req)
    surprise[11] = acctinfo_scores.get("s_ch_acc_age_regression", 0.0)
    surprise[12] = acctinfo_scores.get("s_ch_acc_change", 0.0)
    surprise[13] = acctinfo_scores.get("s_pw_change", 0.0)
    surprise[14] = acctinfo_scores.get("s_txn_vel_day", 0.0)
    surprise[15] = acctinfo_scores.get("s_txn_vel_year", 0.0)
    surprise[16] = acctinfo_scores.get("s_provision_attempts", 0.0)
    surprise[17] = acctinfo_scores.get("s_nb_purchase", 0.0)
    surprise[18] = acctinfo_scores.get("s_suspicious", 0.0)
    surprise[19] = acctinfo_scores.get("s_ship_name_match", 0.0)

    contributions["s_ch_acc_age_regression"] = {
        "score": surprise[11], "observed": str(payload.get("chAccAgeInd", "")),
        "expected": f"last={req.get('ch_acc_age_ind_last', '')}",
    }
    contributions["s_ch_acc_change"] = {
        "score": surprise[12], "observed": str(payload.get("chAccChangeInd", "")),
        "expected": f"EWMA={req.get('ch_acc_change_ind_ewma', 0):.2f}",
    }
    contributions["s_pw_change"] = {
        "score": surprise[13], "observed": str(payload.get("chAccPwChangeInd", "")),
        "expected": f"EWMA={req.get('ch_acc_pw_change_ind_ewma', 0):.2f}",
    }
    contributions["s_txn_vel_day"] = {
        "score": surprise[14], "observed": str(payload.get("txnActivityDay", "")),
        "expected": f"EWMA={req.get('txn_activity_day_ewma', 0):.2f}",
    }
    contributions["s_txn_vel_year"] = {
        "score": surprise[15], "observed": str(payload.get("txnActivityYear", "")),
        "expected": f"EWMA={req.get('txn_activity_year_ewma', 0):.2f}",
    }
    contributions["s_provision_attempts"] = {
        "score": surprise[16], "observed": str(payload.get("provisionAttemptsDay", "")),
        "expected": f"EWMA={req.get('provision_attempts_ewma', 0):.2f}",
    }
    contributions["s_nb_purchase"] = {
        "score": surprise[17], "observed": str(payload.get("nbPurchaseAccount", "")),
        "expected": f"EWMA={req.get('nb_purchase_ewma', 0):.2f}",
    }
    contributions["s_suspicious"] = {
        "score": surprise[18], "observed": str(payload.get("suspiciousAccActivity", "")),
        "expected": "02 (normal)",
    }
    contributions["s_ship_name_match"] = {
        "score": surprise[19], "observed": str(payload.get("shipNameIndicator", "")),
        "expected": f"match_rate={req.get('ship_name_match_rate', 1.0):.2f}",
    }

    # ---- Merchant Details (dims 20–26) ----

    # 20: s_merchant_id
    val = str(payload.get("acquirerMerchantID", ""))
    known_mids = mer.get("known_merchant_ids", {})
    s = surprise_known_unknown(val, list(known_mids.keys()))
    surprise[20] = s
    contributions["s_merchant_id"] = {
        "score": s, "observed": val,
        "expected": f"known set: {list(known_mids.keys())[:3]}",
    }

    # 21: s_acquirer_bin
    val = str(payload.get("acquirerBIN", ""))
    bins = mer.get("known_acquirer_bins", {})
    bins_list = list(bins.keys()) if isinstance(bins, dict) else bins
    s = surprise_known_unknown(val, bins)
    surprise[21] = s
    contributions["s_acquirer_bin"] = {
        "score": s, "observed": val,
        "expected": f"known set: {bins_list[:3]}",
    }

    # 22: s_ship_indicator
    val = str(payload.get("shipIndicator", "01"))
    s = surprise_categorical(val, mer.get("ship_ind_freq", {}))
    surprise[22] = s
    contributions["s_ship_indicator"] = {
        "score": s, "observed": val,
        "expected": _top_key(mer.get("ship_ind_freq", {})),
    }

    # 23: s_billing_addr_hash
    billing_hash = compute_billing_addr_hash(payload)
    s = surprise_known_unknown(billing_hash, mer.get("billing_addr_hashes", []))
    surprise[23] = s
    contributions["s_billing_addr_hash"] = {
        "score": s, "observed": billing_hash[:12] + "...",
        "raw_observed": billing_hash,
        "expected": f"{len(mer.get('billing_addr_hashes', []))} known addresses",
    }

    # 24: s_shipping_addr_hash
    ship_hash = compute_shipping_addr_hash(payload)
    s = surprise_known_unknown(ship_hash, mer.get("shipping_addr_hashes", []))
    surprise[24] = s
    contributions["s_shipping_addr_hash"] = {
        "score": s, "observed": ship_hash[:12] + "...",
        "raw_observed": ship_hash,
        "expected": f"{len(mer.get('shipping_addr_hashes', []))} known addresses",
    }

    # 25: s_email_hash
    email = str(payload.get("email", "") or "").strip().lower()
    email_hash = sha256_str(email) if email else ""
    s = surprise_known_unknown(email_hash, mer.get("known_email_hashes", []))
    surprise[25] = s
    contributions["s_email_hash"] = {
        "score": s, "observed": email[:20] if email else "empty",
        "raw_observed": email_hash if email_hash else None,
        "expected": f"{len(mer.get('known_email_hashes', []))} known emails",
    }

    # 26: s_phone_hash
    phone = str(payload.get("mobilePhone", "") or "").strip()
    phone_hash = sha256_str(phone) if phone else ""
    s = surprise_known_unknown(phone_hash, mer.get("known_phone_hashes", []))
    surprise[26] = s
    contributions["s_phone_hash"] = {
        "score": s, "observed": phone[-4:] if phone else "empty",
        "raw_observed": phone_hash if phone_hash else None,
        "expected": f"{len(mer.get('known_phone_hashes', []))} known phones",
    }

    # ---- Device Details (dims 27–39) ----

    # 27: s_platform
    val = str(payload.get("Platform", ""))
    s = surprise_categorical(val, dev.get("platform_freq", {}))
    surprise[27] = s
    contributions["s_platform"] = {
        "score": s, "observed": val,
        "expected": _top_key(dev.get("platform_freq", {})),
    }

    # 28: s_device_model
    val = str(payload.get("DeviceModel", payload.get("Device Model", "")))
    s = surprise_categorical(val, dev.get("device_model_freq", {}))
    surprise[28] = s
    contributions["s_device_model"] = {
        "score": s, "observed": val,
        "expected": _top_key(dev.get("device_model_freq", {})),
    }

    # 29: s_os_name
    val = str(payload.get("OSName", payload.get("OS Name", "")))
    s = surprise_categorical(val, dev.get("os_name_freq", {}))
    surprise[29] = s
    contributions["s_os_name"] = {
        "score": s, "observed": val,
        "expected": _top_key(dev.get("os_name_freq", {})),
    }

    # 30: s_os_version
    val = str(payload.get("OSVersion", payload.get("OS Version", "")))
    s = surprise_os_version(val, dev.get("os_version_freq", {}))
    surprise[30] = s
    contributions["s_os_version"] = {
        "score": s, "observed": val,
        "expected": _top_key(dev.get("os_version_freq", {})),
    }

    # 31: s_locale
    val = str(payload.get("Locale", ""))
    s = surprise_categorical(val, dev.get("locale_freq", {}))
    surprise[31] = s
    contributions["s_locale"] = {
        "score": s, "observed": val,
        "expected": _top_key(dev.get("locale_freq", {})),
    }

    # 32: s_timezone
    val = str(payload.get("TimeZone", payload.get("Time Zone", "")))
    s = surprise_known_unknown(val, dev.get("known_timezones", []))
    surprise[32] = s
    tzs = dev.get("known_timezones", {})
    tzs_list = list(tzs.keys()) if isinstance(tzs, dict) else tzs
    contributions["s_timezone"] = {
        "score": s, "observed": val,
        "expected": f"known: {tzs_list[:3]}",
    }

    # 33: s_screen_res
    val = str(payload.get("ScreenResolution", payload.get("Screen Resolution", "")))
    s = surprise_known_unknown(val, dev.get("known_resolutions", []))
    surprise[33] = s
    res = dev.get("known_resolutions", {})
    res_list = list(res.keys()) if isinstance(res, dict) else res
    contributions["s_screen_res"] = {
        "score": s, "observed": val,
        "expected": f"known: {res_list[:3]}",
    }

    # 34: s_ip_subnet
    ip = str(payload.get("IPAddress", payload.get("IP Address", "")))
    subnet = extract_ip_subnet(ip)
    s = surprise_known_unknown(subnet, dev.get("known_ip_subnets", []))
    surprise[34] = s
    ips = dev.get("known_ip_subnets", {})
    ips_list = list(ips.keys()) if isinstance(ips, dict) else ips
    contributions["s_ip_subnet"] = {
        "score": s, "observed": subnet,
        "expected": f"known: {ips_list[:3]}",
    }

    # 35: s_gps_billing_dist (GPS vs device geo centroid)
    try:
        obs_lat = float(payload.get("Latitude", 0) or 0)
        obs_lon = float(payload.get("Longitude", 0) or 0)
        s = surprise_geo(
            obs_lat, obs_lon,
            dev.get("geo_lat", 0.0), dev.get("geo_lon", 0.0),
            dev.get("geo_radius_km", GEO_MIN_RADIUS_KM),
        )
    except (TypeError, ValueError):
        s = 0.0
    surprise[35] = s
    contributions["s_gps_billing_dist"] = {
        "score": s,
        "observed": f"({payload.get('Latitude', 0)}, {payload.get('Longitude', 0)})",
        "expected": f"centroid=({dev.get('geo_lat', 0):.2f}, {dev.get('geo_lon', 0):.2f}), "
                    f"radius={dev.get('geo_radius_km', 0):.1f}km",
    }

    # 36: s_app_package
    app_pkg = str(payload.get("ApplicationPackageName",
                              payload.get("Application Package Name", "")))
    app_hash = sha256_str(app_pkg) if app_pkg else ""
    s = surprise_app_package(app_hash, dev.get("known_app_packages", []))
    surprise[36] = s
    contributions["s_app_package"] = {
        "score": s, "observed": app_hash[:12] + "..." if app_hash else "empty",
        "raw_observed": app_hash if app_hash else None,
        "expected": f"{len(dev.get('known_app_packages', []))} known packages",
    }

    # 37: s_sdk_ref_tamper
    sdk_ref = str(payload.get("SDKRefNumber", payload.get("SDK Ref Number", "")))
    sdk_ref_hash = sha256_str(sdk_ref) if sdk_ref else ""
    s = surprise_sdk_ref(sdk_ref_hash, dev.get("expected_sdk_ref_hash", ""))
    surprise[37] = s
    contributions["s_sdk_ref_tamper"] = {
        "score": s, "observed": sdk_ref_hash[:12] + "..." if sdk_ref_hash else "empty",
        "expected": "matching SDK reference hash",
    }

    # 38: s_sdk_version
    val = str(payload.get("SDKVersion", payload.get("SDK Version", "")))
    s = surprise_known_unknown(val, list(dev.get("sdk_version_freq", {}).keys()))
    surprise[38] = s
    contributions["s_sdk_version"] = {
        "score": s, "observed": val,
        "expected": _top_key(dev.get("sdk_version_freq", {})),
    }

    # 39: s_device_fp_composite
    fp_hash = compute_device_fp_hash(payload)
    s = surprise_known_unknown(fp_hash, dev.get("device_fp_hashes", []))
    surprise[39] = s
    contributions["s_device_fp_composite"] = {
        "score": s, "observed": fp_hash[:12] + "...",
        "expected": f"{len(dev.get('device_fp_hashes', []))} known fingerprints",
    }

    # ---- Cold-start shrinkage ----
    confidence = meta.get("profile_confidence", 0.0)
    if confidence < COLD_START_CONFIDENCE_THRESHOLD:
        # Blend personal scores toward zero (cohort prior = 0 surprise)
        shrinkage = confidence / COLD_START_CONFIDENCE_THRESHOLD
        surprise = surprise * shrinkage

    # ---- Cross-field checks ----
    cf_scores = cross_field_checks(payload, profile, blocklist_hits)

    return surprise, contributions, cf_scores


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _top_key(freq_dict: dict) -> str:
    """Return the most frequent key from a frequency dict."""
    if not freq_dict:
        return "no history"
    return max(freq_dict, key=freq_dict.get)


def _dim_to_payload_field(dim_name: str) -> str:
    """Map dimension name back to payload field name for contribution details."""
    mapping = {
        "s_ch_acc_age_regression": "chAccAgeInd",
        "s_ch_acc_change": "chAccChangeInd",
        "s_pw_change": "chAccPwChangeInd",
        "s_txn_vel_day": "txnActivityDay",
        "s_txn_vel_year": "txnActivityYear",
        "s_provision_attempts": "provisionAttemptsDay",
        "s_nb_purchase": "nbPurchaseAccount",
        "s_suspicious": "suspiciousAccActivity",
        "s_ship_name_match": "shipNameIndicator",
    }
    return mapping.get(dim_name, dim_name)
