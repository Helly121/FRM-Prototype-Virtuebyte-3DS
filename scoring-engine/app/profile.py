"""
profile.py — Profile lifecycle management.

Handles:
  - Cold-start profile creation for new cards
  - Profile update with EWMA decay, frequency increments,
    geo centroid updates, and probation management
  - Decay config from §11
"""

import math
import time
import hashlib
from copy import deepcopy
from typing import Optional

from .weights import (
    EWMA_ALPHA,
    DECAY_CONFIG,
    BOUNDED_SET_LIMITS,
    GEO_MIN_RADIUS_KM,
)
from .features import (
    sha256_str,
    compute_billing_addr_hash,
    compute_shipping_addr_hash,
    compute_device_fp_hash,
    extract_ip_subnet,
    haversine,
)


def now_ts() -> float:
    """Current UTC timestamp as float (seconds since epoch)."""
    return time.time()


# ---------------------------------------------------------------------------
# Cold-Start Profile
# ---------------------------------------------------------------------------

def new_cold_profile(card_id_hash: str) -> dict:
    """
    Create a fresh profile for a card not yet seen.
    All frequency dicts are empty; EWMA values are zero.
    Profile confidence starts at 0.0 and saturates at 50 transactions.
    """
    ts = now_ts()
    return {
        "_meta": {
            "card_id_hash": card_id_hash,
            "created_at": ts,
            "last_updated": ts,
            "history_depth_days": 0,
            "transaction_count": 0,
            "profile_confidence": 0.0,
        },
        "transaction": {
            "acct_type_freq": {},
            "mcc_freq": {},
            "country_freq": {},
            "currency_freq": {},
            "amount_ewma_log": 0.0,
            "amount_ewma_var": 0.0,
            "hour_hist": [1.0 / 24] * 24,    # Uniform prior
            "dow_hist": [1.0 / 7] * 7,       # Uniform prior
            "cvv_match_rate": 0.5,            # Neutral prior
        },
        "requestor": {
            "known_requestors": {},
            "known_req_urls": [],
            "auth_ind_freq": {},
            "auth_method_freq": {},
            "ch_acc_age_ind_last": 0,
            "ch_acc_change_ind_ewma": 0.0,
            "ch_acc_pw_change_ind_ewma": 0.0,
            "txn_activity_day_ewma": 0.0,
            "txn_activity_day_var": 1.0,
            "txn_activity_year_ewma": 0.0,
            "txn_activity_year_var": 1.0,
            "provision_attempts_ewma": 0.0,
            "provision_attempts_var": 0.0,
            "nb_purchase_ewma": 0.0,
            "nb_purchase_var": 1.0,
            "suspicious_ever": False,
            "ship_name_match_rate": 0.5,      # Neutral prior
        },
        "merchant": {
            "known_merchant_ids": {},
            "known_acquirer_bins": [],
            "ship_ind_freq": {},
            "billing_addr_hashes": [],
            "shipping_addr_hashes": [],
            "known_email_hashes": [],
            "known_phone_hashes": [],
            "billing_lat": 0.0,
            "billing_lon": 0.0,
            "billing_radius_km": GEO_MIN_RADIUS_KM,
            "shipping_lat": 0.0,
            "shipping_lon": 0.0,
            "shipping_radius_km": GEO_MIN_RADIUS_KM * 5,
        },
        "device": {
            "platform_freq": {},
            "device_model_freq": {},
            "os_name_freq": {},
            "os_version_freq": {},
            "locale_freq": {},
            "known_timezones": [],
            "known_resolutions": [],
            "known_ip_subnets": [],
            "device_fp_hashes": [],
            "known_app_packages": [],
            "known_sdk_app_ids": [],
            "sdk_version_freq": {},
            "expected_sdk_ref_hash": "",
            "known_device_names": [],
            "known_sdk_interfaces": [],
            "geo_lat": 0.0,
            "geo_lon": 0.0,
            "geo_radius_km": GEO_MIN_RADIUS_KM * 3,
            "probation": {},
        },
    }


# ---------------------------------------------------------------------------
# Profile Update
# ---------------------------------------------------------------------------

def update_profile(old_profile: dict, payload: dict) -> dict:
    """
    Update the profile to incorporate a new transaction.
    Uses EWMA decay and bounded-set management.

    This runs AFTER the HTTP response is returned (BackgroundTask).
    """
    p = deepcopy(old_profile)
    ts = now_ts()

    meta = p["_meta"]
    txn = p["transaction"]
    req = p["requestor"]
    mer = p["merchant"]
    dev = p["device"]

    n = meta["transaction_count"]

    # --- Decay all existing frequencies ---
    days_since = (ts - meta["last_updated"]) / 86400.0
    if days_since > 0:
        for section_name, field_name, half_life in DECAY_CONFIG:
            section = p.get(section_name, {})
            if field_name in section:
                decay_factor = 0.5 ** (days_since / half_life)
                _apply_decay(section, field_name, decay_factor)

    alpha = EWMA_ALPHA

    # --- Transaction fields ---
    # Amount EWMA
    amount = float(payload.get("purchaseAmount", 0) or 0)
    log_amount = math.log1p(max(amount, 0))
    if n == 0:
        txn["amount_ewma_log"] = log_amount
        txn["amount_ewma_var"] = 0.0
    else:
        old_mean = txn["amount_ewma_log"]
        txn["amount_ewma_log"] = alpha * log_amount + (1 - alpha) * old_mean
        deviation = (log_amount - old_mean) ** 2
        txn["amount_ewma_var"] = (
            alpha * deviation + (1 - alpha) * txn["amount_ewma_var"]
        )

    # Categorical frequencies
    _increment_freq(txn, "acct_type_freq", str(payload.get("acctType", "01")))
    _increment_freq(txn, "mcc_freq", str(payload.get("mcc", "")), max_keys=10)
    _increment_freq(txn, "country_freq",
                    str(payload.get("merchantCountryCode", "")), max_keys=5)
    _increment_freq(txn, "currency_freq",
                    str(payload.get("purchaseCurrency", "")), max_keys=3)

    # Temporal histograms
    from .features import parse_dt
    purchase_dt = parse_dt(payload.get("purchaseDate"))
    hour = purchase_dt.hour
    dow = purchase_dt.weekday()
    hist_alpha = 0.05  # Slower adaptation for histograms
    for i in range(24):
        target = 1.0 if i == hour else 0.0
        txn["hour_hist"][i] = (
            hist_alpha * target + (1 - hist_alpha) * txn["hour_hist"][i]
        )
    for i in range(7):
        target = 1.0 if i == dow else 0.0
        txn["dow_hist"][i] = (
            hist_alpha * target + (1 - hist_alpha) * txn["dow_hist"][i]
        )
    # Renormalise histograms
    h_sum = sum(txn["hour_hist"])
    if h_sum > 0:
        txn["hour_hist"] = [x / h_sum for x in txn["hour_hist"]]
    d_sum = sum(txn["dow_hist"])
    if d_sum > 0:
        txn["dow_hist"] = [x / d_sum for x in txn["dow_hist"]]

    # CVV match rate EWMA
    cvv_match = 1.0 if str(payload.get("cardSecurityCodeStatus", "01")) == "01" else 0.0
    txn["cvv_match_rate"] = (
        alpha * cvv_match + (1 - alpha) * txn["cvv_match_rate"]
    )

    # --- Requestor fields ---
    req_id = str(payload.get("threeDSRequestorID", ""))
    if req_id:
        known_req = req["known_requestors"]
        if req_id in known_req:
            known_req[req_id]["freq"] = known_req[req_id].get("freq", 0) + 1
            known_req[req_id]["last_seen"] = ts
        else:
            known_req[req_id] = {"freq": 1, "last_seen": ts}
        _trim_bounded_dict(known_req, BOUNDED_SET_LIMITS.get("known_requestors", 10))

    req_url = str(payload.get("threeDSRequestorURL", ""))
    if req_url:
        url_hash = sha256_str(req_url)
        _add_to_bounded_set(req, "known_req_urls", url_hash,
                            BOUNDED_SET_LIMITS.get("known_req_urls", 10))

    _increment_freq(req, "auth_ind_freq",
                    str(payload.get("threeDSRequestorAuthenticationInd", "")))
    _increment_freq(req, "auth_method_freq",
                    str(payload.get("threeDSReqAuthMethod", "")), max_keys=5)

    # acctInfo fields
    ch_age = int(payload.get("chAccAgeInd", "05") or "05")
    req["ch_acc_age_ind_last"] = max(
        req.get("ch_acc_age_ind_last", 0), ch_age
    )  # Monotonically increasing

    ch_change = float(payload.get("chAccChangeInd", "01") or "01")
    req["ch_acc_change_ind_ewma"] = (
        alpha * ch_change + (1 - alpha) * req.get("ch_acc_change_ind_ewma", ch_change)
    )

    ch_pw = float(payload.get("chAccPwChangeInd", "01") or "01")
    req["ch_acc_pw_change_ind_ewma"] = (
        alpha * ch_pw + (1 - alpha) * req.get("ch_acc_pw_change_ind_ewma", ch_pw)
    )

    # Velocity EWMA + variance (Welford online)
    for field, ewma_key, var_key in [
        ("txnActivityDay", "txn_activity_day_ewma", "txn_activity_day_var"),
        ("txnActivityYear", "txn_activity_year_ewma", "txn_activity_year_var"),
        ("nbPurchaseAccount", "nb_purchase_ewma", "nb_purchase_var"),
        ("provisionAttemptsDay", "provision_attempts_ewma", "provision_attempts_var"),
    ]:
        val = float(payload.get(field, 0) or 0)
        old_mean = req.get(ewma_key, val)
        req[ewma_key] = alpha * val + (1 - alpha) * old_mean
        deviation = (val - old_mean) ** 2
        req[var_key] = alpha * deviation + (1 - alpha) * req.get(var_key, 0.0)

    # Suspicious activity sticky flag
    if str(payload.get("suspiciousAccActivity", "02")) == "01":
        req["suspicious_ever"] = True

    # Ship name match rate
    ship_match = 1.0 if str(payload.get("shipNameIndicator", "01")) == "01" else 0.0
    req["ship_name_match_rate"] = (
        alpha * ship_match + (1 - alpha) * req.get("ship_name_match_rate", 0.5)
    )

    # --- Merchant fields ---
    mid = str(payload.get("acquirerMerchantID", ""))
    if mid:
        known_mids = mer["known_merchant_ids"]
        if mid in known_mids:
            known_mids[mid]["freq"] = known_mids[mid].get("freq", 0) + 1
            known_mids[mid]["last_seen"] = ts
        else:
            known_mids[mid] = {"freq": 1, "last_seen": ts}
        _trim_bounded_dict(known_mids, BOUNDED_SET_LIMITS.get("known_merchant_ids", 15))

    abin = str(payload.get("acquirerBIN", ""))
    if abin:
        _add_to_bounded_set(mer, "known_acquirer_bins", abin,
                            BOUNDED_SET_LIMITS.get("known_acquirer_bins", 10))

    _increment_freq(mer, "ship_ind_freq",
                    str(payload.get("shipIndicator", "")), max_keys=5)

    # Address hashes
    billing_hash = compute_billing_addr_hash(payload)
    if billing_hash:
        _add_to_bounded_set(mer, "billing_addr_hashes", billing_hash,
                            BOUNDED_SET_LIMITS.get("billing_addr_hashes", 3))

    shipping_hash = compute_shipping_addr_hash(payload)
    if shipping_hash:
        _add_to_bounded_set(mer, "shipping_addr_hashes", shipping_hash,
                            BOUNDED_SET_LIMITS.get("shipping_addr_hashes", 5))

    # Email / phone hashes
    email = str(payload.get("email", "") or "").strip().lower()
    if email:
        email_hash = sha256_str(email)
        _add_to_bounded_set(mer, "known_email_hashes", email_hash,
                            BOUNDED_SET_LIMITS.get("known_email_hashes", 2))

    phone = str(payload.get("mobilePhone", "") or "").strip()
    if phone:
        phone_hash = sha256_str(phone)
        _add_to_bounded_set(mer, "known_phone_hashes", phone_hash,
                            BOUNDED_SET_LIMITS.get("known_phone_hashes", 2))

    # --- Device fields ---
    _increment_freq(dev, "platform_freq", str(payload.get("Platform", "")))
    _increment_freq(dev, "device_model_freq",
                    str(payload.get("DeviceModel",
                                    payload.get("Device Model", ""))), max_keys=5)
    _increment_freq(dev, "os_name_freq",
                    str(payload.get("OSName", payload.get("OS Name", ""))), max_keys=3)
    _increment_freq(dev, "os_version_freq",
                    str(payload.get("OSVersion", payload.get("OS Version", ""))),
                    max_keys=3)
    _increment_freq(dev, "locale_freq",
                    str(payload.get("Locale", "")), max_keys=3)
    _increment_freq(dev, "sdk_version_freq",
                    str(payload.get("SDKVersion", payload.get("SDK Version", ""))),
                    max_keys=3)

    # Bounded sets
    tz = str(payload.get("TimeZone", payload.get("Time Zone", "")))
    if tz:
        _add_to_bounded_set(dev, "known_timezones", tz,
                            BOUNDED_SET_LIMITS.get("known_timezones", 3))

    res = str(payload.get("ScreenResolution",
                          payload.get("Screen Resolution", "")))
    if res:
        _add_to_bounded_set(dev, "known_resolutions", res,
                            BOUNDED_SET_LIMITS.get("known_resolutions", 5))

    ip = str(payload.get("IPAddress", payload.get("IP Address", "")))
    subnet = extract_ip_subnet(ip)
    if subnet:
        _add_to_bounded_set(dev, "known_ip_subnets", subnet,
                            BOUNDED_SET_LIMITS.get("known_ip_subnets", 5))

    # Device fingerprint composite
    fp_hash = compute_device_fp_hash(payload)
    if fp_hash:
        _add_to_bounded_set(dev, "device_fp_hashes", fp_hash,
                            BOUNDED_SET_LIMITS.get("device_fp_hashes", 5))

    # App package
    app_pkg = str(payload.get("ApplicationPackageName",
                              payload.get("Application Package Name", "")))
    if app_pkg:
        app_hash = sha256_str(app_pkg)
        _add_to_bounded_set(dev, "known_app_packages", app_hash,
                            BOUNDED_SET_LIMITS.get("known_app_packages", 2))

    # SDK App ID
    sdk_id = str(payload.get("SDKAppID", payload.get("SDK App ID", "")))
    if sdk_id:
        sdk_id_hash = sha256_str(sdk_id)
        _add_to_bounded_set(dev, "known_sdk_app_ids", sdk_id_hash,
                            BOUNDED_SET_LIMITS.get("known_sdk_app_ids", 3))

    # SDK Ref Number — store expected hash
    sdk_ref = str(payload.get("SDKRefNumber", payload.get("SDK Ref Number", "")))
    if sdk_ref:
        dev["expected_sdk_ref_hash"] = sha256_str(sdk_ref)

    # Device name
    dev_name = str(payload.get("DeviceName", payload.get("Device Name", "")))
    if dev_name:
        dn_hash = sha256_str(dev_name)
        _add_to_bounded_set(dev, "known_device_names", dn_hash,
                            BOUNDED_SET_LIMITS.get("known_device_names", 5))

    # SDK Interface
    sdk_iface = str(payload.get("sdkInterface", ""))
    if sdk_iface:
        _add_to_bounded_set(dev, "known_sdk_interfaces", sdk_iface,
                            BOUNDED_SET_LIMITS.get("known_sdk_interfaces", 2))

    # --- Geo centroid update (online mean) ---
    try:
        obs_lat = float(payload.get("Latitude", 0) or 0)
        obs_lon = float(payload.get("Longitude", 0) or 0)
        if obs_lat != 0 or obs_lon != 0:
            new_n = n + 1
            if n == 0:
                dev["geo_lat"] = obs_lat
                dev["geo_lon"] = obs_lon
                dev["geo_radius_km"] = GEO_MIN_RADIUS_KM * 3
            else:
                dev["geo_lat"] = (dev["geo_lat"] * n + obs_lat) / new_n
                dev["geo_lon"] = (dev["geo_lon"] * n + obs_lon) / new_n
                dist = haversine(obs_lat, obs_lon, dev["geo_lat"], dev["geo_lon"])
                # Online variance update for radius
                old_radius = dev.get("geo_radius_km", GEO_MIN_RADIUS_KM * 3)
                dev["geo_radius_km"] = math.sqrt(
                    (old_radius ** 2 * (new_n - 1) + dist ** 2) / new_n
                )
                dev["geo_radius_km"] = max(dev["geo_radius_km"], GEO_MIN_RADIUS_KM)
    except (TypeError, ValueError):
        pass

    # --- Update probation ---
    _update_probation(dev, payload)

    # --- Update metadata ---
    meta["transaction_count"] = n + 1
    meta["last_updated"] = ts
    meta["profile_confidence"] = min(1.0, (n + 1) / 50.0)
    if meta["created_at"] > 0:
        meta["history_depth_days"] = (ts - meta["created_at"]) / 86400.0

    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_decay(section: dict, field_name: str, decay_factor: float):
    """Apply exponential decay to a frequency dict or bounded set."""
    val = section.get(field_name)
    if val is None:
        return

    if isinstance(val, dict):
        # Frequency dict: decay all values
        for k in list(val.keys()):
            if isinstance(val[k], (int, float)):
                val[k] *= decay_factor
                if val[k] < 0.001:
                    del val[k]  # Prune negligible entries
            elif isinstance(val[k], dict) and "freq" in val[k]:
                val[k]["freq"] *= decay_factor
                if val[k]["freq"] < 0.001:
                    del val[k]
    # Lists (bounded sets) are not decayed — they use LRU eviction


def _increment_freq(section: dict, field_name: str,
                    value: str, max_keys: int = 20):
    """Increment a frequency dict entry, with Top-K pruning."""
    if not value:
        return
    freq = section.get(field_name, {})
    freq[value] = freq.get(value, 0.0) + 1.0

    # Prune to Top-K if needed
    if len(freq) > max_keys:
        sorted_keys = sorted(freq, key=freq.get, reverse=True)
        freq = {k: freq[k] for k in sorted_keys[:max_keys]}

    section[field_name] = freq


def _add_to_bounded_set(section: dict, field_name: str,
                        value: str, max_size: int):
    """Add a value to a bounded set (list), evicting oldest if full."""
    s = section.get(field_name, [])
    if value not in s:
        if len(s) >= max_size:
            s.pop(0)  # Evict oldest (FIFO)
        s.append(value)
    section[field_name] = s


def _trim_bounded_dict(d: dict, max_size: int):
    """Trim a bounded dict to max_size, keeping highest-freq entries."""
    if len(d) <= max_size:
        return
    sorted_keys = sorted(d, key=lambda k: d[k].get("freq", 0), reverse=True)
    for k in sorted_keys[max_size:]:
        del d[k]


def _update_probation(dev: dict, payload: dict):
    """
    Track newly seen values in probation until they reach trust_threshold.
    """
    probation = dev.get("probation", {})

    # Check key device identity fields
    probation_checks = [
        ("device.platform", str(payload.get("Platform", "")),
         dev.get("platform_freq", {}), 3),
        ("device.app_package",
         sha256_str(str(payload.get("ApplicationPackageName",
                                    payload.get("Application Package Name", "")))),
         dev.get("known_app_packages", []), 5),
    ]

    for key, value, known, threshold in probation_checks:
        if not value:
            continue
        full_key = f"{key}.{value}"

        is_known = (
            (isinstance(known, dict) and value in known) or
            (isinstance(known, list) and value in known)
        )

        if not is_known:
            if full_key not in probation:
                probation[full_key] = {
                    "count": 1,
                    "first_seen": now_ts(),
                    "trust_threshold": threshold,
                }
            else:
                probation[full_key]["count"] += 1
        else:
            # Value is now in the known set — check if it can leave probation
            if full_key in probation:
                probation[full_key]["count"] += 1
                if probation[full_key]["count"] >= probation[full_key]["trust_threshold"]:
                    del probation[full_key]

    dev["probation"] = probation
