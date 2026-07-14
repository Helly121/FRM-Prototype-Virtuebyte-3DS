"""
weights.py — Static weights, thresholds, and scoring constants.

This module is the single configuration source for all scoring parameters.
Weights are expert-set defaults from the system design §6 table.
Once real fraud labels are available, these can be recalibrated via
constrained logistic regression over the surprise vector.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Scoring Constants
# ---------------------------------------------------------------------------

HIGH_WEIGHT = 3.0            # Direct flag for provision spikes on clean cards
VERY_HIGH_WEIGHT = 5.0       # Direct flag for suspicious activity
REGRESSION_PENALTY = 2.0     # Per-step penalty for acctInfo regression
HIGH_WEIGHT_CONSTANT = 4.0   # Unknown app package (integrity concern)
TAMPER_FLAG_WEIGHT = 5.0     # SDK Ref Number hash mismatch

LAPLACE_ALPHA = 0.5          # Smoothing constant for categorical surprise
EWMA_WINDOW = 20             # Transactions for EWMA smoothing factor
EWMA_ALPHA = 2.0 / (EWMA_WINDOW + 1)  # ~0.095

CLOCK_SKEW_THRESHOLD_S = 300  # 5 minutes — dateTime vs purchaseDate
GEO_MIN_RADIUS_KM = 2.0      # Floor for geo radius normalisation

# Cold-start shrinkage threshold
COLD_START_CONFIDENCE_THRESHOLD = 0.3

# ---------------------------------------------------------------------------
# 40-Dimensional Surprise Vector — Dimension Names & Weights
# ---------------------------------------------------------------------------

DIMENSION_NAMES = [
    "s_acct_type",               # 0
    "s_mcc",                     # 1
    "s_merchant_country",        # 2
    "s_amount",                  # 3
    "s_currency",                # 4
    "s_temporal",                # 5
    "s_cvv_status",              # 6
    "s_requestor_id",            # 7
    "s_requestor_url",           # 8
    "s_auth_ind",                # 9
    "s_auth_method",             # 10
    "s_ch_acc_age_regression",   # 11
    "s_ch_acc_change",           # 12
    "s_pw_change",               # 13
    "s_txn_vel_day",             # 14
    "s_txn_vel_year",            # 15
    "s_provision_attempts",      # 16
    "s_nb_purchase",             # 17
    "s_suspicious",              # 18
    "s_ship_name_match",         # 19
    "s_merchant_id",             # 20
    "s_acquirer_bin",            # 21
    "s_ship_indicator",          # 22
    "s_billing_addr_hash",       # 23
    "s_shipping_addr_hash",      # 24
    "s_email_hash",              # 25
    "s_phone_hash",              # 26
    "s_platform",                # 27
    "s_device_model",            # 28
    "s_os_name",                 # 29
    "s_os_version",              # 30
    "s_locale",                  # 31
    "s_timezone",                # 32
    "s_screen_res",              # 33
    "s_ip_subnet",               # 34
    "s_gps_billing_dist",        # 35
    "s_app_package",             # 36
    "s_sdk_ref_tamper",          # 37
    "s_sdk_version",             # 38
    "s_device_fp_composite",     # 39
]

# Static weights (§6 table) — used for weighted sum TotalDeviation
# These are relative importance coefficients, not probabilities.
STATIC_WEIGHTS = np.array([
    0.04,  # 0  s_acct_type
    0.06,  # 1  s_mcc
    0.05,  # 2  s_merchant_country
    0.08,  # 3  s_amount
    0.04,  # 4  s_currency
    0.04,  # 5  s_temporal
    0.05,  # 6  s_cvv_status
    0.06,  # 7  s_requestor_id
    0.08,  # 8  s_requestor_url
    0.04,  # 9  s_auth_ind
    0.05,  # 10 s_auth_method
    0.09,  # 11 s_ch_acc_age_regression
    0.06,  # 12 s_ch_acc_change
    0.06,  # 13 s_pw_change
    0.07,  # 14 s_txn_vel_day
    0.04,  # 15 s_txn_vel_year
    0.08,  # 16 s_provision_attempts
    0.04,  # 17 s_nb_purchase
    0.10,  # 18 s_suspicious
    0.05,  # 19 s_ship_name_match
    0.05,  # 20 s_merchant_id
    0.03,  # 21 s_acquirer_bin
    0.04,  # 22 s_ship_indicator
    0.09,  # 23 s_billing_addr_hash
    0.04,  # 24 s_shipping_addr_hash
    0.05,  # 25 s_email_hash
    0.04,  # 26 s_phone_hash
    0.20,  # 27 s_platform           — highest individual weight
    0.10,  # 28 s_device_model
    0.07,  # 29 s_os_name
    0.05,  # 30 s_os_version
    0.04,  # 31 s_locale
    0.04,  # 32 s_timezone
    0.03,  # 33 s_screen_res
    0.06,  # 34 s_ip_subnet
    0.10,  # 35 s_gps_billing_dist
    0.18,  # 36 s_app_package        — very high weight
    0.15,  # 37 s_sdk_ref_tamper
    0.04,  # 38 s_sdk_version
    0.14,  # 39 s_device_fp_composite
], dtype=np.float64)

NUM_DIMENSIONS = len(STATIC_WEIGHTS)  # 40

# Cross-field check names and weights (added to TotalDeviation, not part of IF vector)
CROSS_FIELD_NAMES = [
    "s_clock_skew",
    "s_platform_os_coherence",
    "s_velocity_crosscheck",
    "s_new_shipping_context",
]

CROSS_FIELD_WEIGHTS = {
    "s_clock_skew": 0.07,
    "s_platform_os_coherence": 0.08,
    "s_velocity_crosscheck": 0.05,
    "s_new_shipping_context": 0.04,
}

# ---------------------------------------------------------------------------
# Tier Thresholds
# ---------------------------------------------------------------------------
# Calibrated against synthetic data. Adjust after observing real transactions.
# TotalDeviation is the weighted sum of all surprise scores.

TIER_HIGH_DEVIATION = 2.5      # TotalDeviation >= this → HIGH
TIER_MED_DEVIATION = 1.0       # TotalDeviation >= this → MEDIUM

# Isolation Forest score boundaries (negative = more anomalous)
IF_HIGH_THRESHOLD = -0.15      # IF score <= this → force HIGH
IF_MED_THRESHOLD = -0.05       # IF score <= this → force MEDIUM

# Contribution suppression: factors contributing < this % are moved to context
CONTRIBUTION_MIN_PCT = 2.0

# ---------------------------------------------------------------------------
# Dimension-to-field mapping (for human-readable report)
# ---------------------------------------------------------------------------

DIMENSION_TO_FIELD = {
    "s_acct_type": "transaction.acctType",
    "s_mcc": "transaction.mcc",
    "s_merchant_country": "transaction.merchantCountryCode",
    "s_amount": "transaction.purchaseAmount",
    "s_currency": "transaction.purchaseCurrency",
    "s_temporal": "transaction.purchaseDate",
    "s_cvv_status": "transaction.cardSecurityCodeStatus",
    "s_requestor_id": "requestor.threeDSRequestorID",
    "s_requestor_url": "requestor.threeDSRequestorURL",
    "s_auth_ind": "requestor.threeDSRequestorAuthenticationInd",
    "s_auth_method": "requestor.threeDSReqAuthMethod",
    "s_ch_acc_age_regression": "requestor.acctInfo.chAccAgeInd",
    "s_ch_acc_change": "requestor.acctInfo.chAccChangeInd",
    "s_pw_change": "requestor.acctInfo.chAccPwChangeInd",
    "s_txn_vel_day": "requestor.acctInfo.txnActivityDay",
    "s_txn_vel_year": "requestor.acctInfo.txnActivityYear",
    "s_provision_attempts": "requestor.acctInfo.provisionAttemptsDay",
    "s_nb_purchase": "requestor.acctInfo.nbPurchaseAccount",
    "s_suspicious": "requestor.acctInfo.suspiciousAccActivity",
    "s_ship_name_match": "requestor.acctInfo.shipNameIndicator",
    "s_merchant_id": "merchant.acquirerMerchantID",
    "s_acquirer_bin": "merchant.acquirerBIN",
    "s_ship_indicator": "merchant.shipIndicator",
    "s_billing_addr_hash": "merchant.billAddr",
    "s_shipping_addr_hash": "merchant.shipAddr",
    "s_email_hash": "merchant.email",
    "s_phone_hash": "merchant.mobilePhone",
    "s_platform": "device.Platform",
    "s_device_model": "device.DeviceModel",
    "s_os_name": "device.OSName",
    "s_os_version": "device.OSVersion",
    "s_locale": "device.Locale",
    "s_timezone": "device.TimeZone",
    "s_screen_res": "device.ScreenResolution",
    "s_ip_subnet": "device.IPAddress",
    "s_gps_billing_dist": "device.geo_distance",
    "s_app_package": "device.ApplicationPackageName",
    "s_sdk_ref_tamper": "device.SDKRefNumber",
    "s_sdk_version": "device.SDKVersion",
    "s_device_fp_composite": "device.fingerprint_composite",
    "s_clock_skew": "cross_field.clock_skew",
    "s_platform_os_coherence": "cross_field.platform_os_coherence",
    "s_velocity_crosscheck": "cross_field.velocity_crosscheck",
    "s_new_shipping_context": "cross_field.shipping_context",
}

# ---------------------------------------------------------------------------
# Decay Configuration (§11)
# ---------------------------------------------------------------------------
# (section, field, half_life_days)

DECAY_CONFIG = [
    ("device",      "platform_freq",          365),
    ("device",      "device_model_freq",      180),
    ("device",      "os_name_freq",           180),
    ("device",      "os_version_freq",        120),
    ("device",      "locale_freq",            120),
    ("device",      "sdk_version_freq",       120),
    ("device",      "known_app_packages",     180),
    ("device",      "known_ip_subnets",        30),
    ("device",      "known_device_names",     180),
    ("device",      "device_fp_hashes",       180),
    ("merchant",    "billing_addr_hashes",    365),
    ("merchant",    "shipping_addr_hashes",    60),
    ("merchant",    "ship_ind_freq",           90),
    ("merchant",    "known_email_hashes",     365),
    ("merchant",    "known_phone_hashes",     365),
    ("transaction", "mcc_freq",                90),
    ("transaction", "country_freq",           180),
    ("transaction", "currency_freq",          180),
    ("transaction", "acct_type_freq",         365),
    ("requestor",   "auth_ind_freq",          180),
    ("requestor",   "auth_method_freq",       180),
    ("requestor",   "known_requestors",       180),
]

# Bounded set size limits (§1 table)
BOUNDED_SET_LIMITS = {
    "known_requestors": 10,
    "known_req_urls": 10,
    "known_merchant_ids": 15,
    "known_acquirer_bins": 10,
    "billing_addr_hashes": 3,
    "shipping_addr_hashes": 5,
    "known_email_hashes": 2,
    "known_phone_hashes": 2,
    "known_timezones": 3,
    "known_resolutions": 5,
    "known_ip_subnets": 5,
    "known_app_packages": 2,
    "known_sdk_app_ids": 3,
    "known_device_names": 5,
    "known_sdk_interfaces": 2,
    "device_fp_hashes": 5,
}
