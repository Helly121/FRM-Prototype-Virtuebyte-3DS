"""
generate_dataset.py — Synthetic 3DS Transaction Dataset Generator

Generates 100,000 synthetic 3DS authentication records for 1,000 cards:
  - 70,000 profile-establishment (normal only)
  - 20,000 scoring-phase normals
  - 10,000 scoring-phase anomalies (7 types A-G per S8.4)

Each card is assigned one of 10 archetypes that define its behavioral baseline.
All records are written directly into the PostgreSQL `synthetic_transactions`
table with one column per field.

Usage:
    python scripts/generate_dataset.py
"""

import os
import sys
import math
import random
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from db_config import (
    get_connection,
    PAYLOAD_FIELD_KEYS,
    SQL_FIELD_COLUMNS,
    payload_to_row,
    bulk_insert,
)

# ---------------------------------------------------------------------------
# Card Archetypes (S8.2 -- 10 clusters x 100 cards each)
# ---------------------------------------------------------------------------

CARD_ARCHETYPES = [
    {
        "archetype": "urban_android_shopper",
        "platform": "Android",
        "device_brands": ["Samsung Galaxy S23", "Samsung Galaxy S22"],
        "os_name": "Android",
        "os_versions": ["13", "14"],
        "locale": "en_IN",
        "timezone": "Asia/Kolkata",
        "home_geo": (18.52, 73.85),       # Pune
        "geo_jitter": 0.02,
        "top_mcc": ["5411", "5812", "5941"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 7.5,            # ~INR 1800
        "amount_std_log": 0.6,
        "peak_hours": list(range(18, 22)),
        "normal_txn_velocity_day": (0, 2),
        "normal_txn_velocity_year": (30, 80),
        "resolutions": ["1080x2340", "1080x2400"],
        "sdk_versions": ["5.2.1", "5.3.0"],
    },
    {
        "archetype": "ios_premium_user",
        "platform": "iOS",
        "device_brands": ["iPhone 15 Pro", "iPhone 14 Pro"],
        "os_name": "iOS",
        "os_versions": ["17.4", "17.5"],
        "locale": "en_IN",
        "timezone": "Asia/Kolkata",
        "home_geo": (19.07, 72.88),       # Mumbai
        "geo_jitter": 0.03,
        "top_mcc": ["5912", "5999", "7011"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 8.9,            # ~INR 7300
        "amount_std_log": 0.7,
        "peak_hours": list(range(20, 23)),
        "normal_txn_velocity_day": (0, 3),
        "normal_txn_velocity_year": (40, 100),
        "resolutions": ["1179x2556", "1290x2796"],
        "sdk_versions": ["5.3.0", "5.3.1"],
    },
    {
        "archetype": "rural_basic_android",
        "platform": "Android",
        "device_brands": ["Redmi Note 12", "Realme C55"],
        "os_name": "Android",
        "os_versions": ["12", "13"],
        "locale": "hi_IN",
        "timezone": "Asia/Kolkata",
        "home_geo": (26.85, 80.95),       # Lucknow
        "geo_jitter": 0.05,
        "top_mcc": ["5411", "5541", "5812"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 6.2,            # ~INR 500
        "amount_std_log": 0.8,
        "peak_hours": list(range(10, 14)) + list(range(18, 21)),
        "normal_txn_velocity_day": (0, 1),
        "normal_txn_velocity_year": (10, 40),
        "resolutions": ["720x1600", "1080x2400"],
        "sdk_versions": ["5.1.0", "5.2.1"],
    },
    {
        "archetype": "travel_frequent_flyer",
        "platform": "iOS",
        "device_brands": ["iPhone 15", "iPhone 14"],
        "os_name": "iOS",
        "os_versions": ["17.3", "17.5"],
        "locale": "en_US",
        "timezone": "Asia/Kolkata",
        "home_geo": (12.97, 77.59),       # Bangalore
        "geo_jitter": 0.04,
        "top_mcc": ["3000", "4511", "7011"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 9.5,            # ~INR 13000
        "amount_std_log": 1.0,
        "peak_hours": list(range(8, 22)),
        "normal_txn_velocity_day": (0, 3),
        "normal_txn_velocity_year": (50, 120),
        "resolutions": ["1179x2556"],
        "sdk_versions": ["5.3.0"],
    },
    {
        "archetype": "student_budget",
        "platform": "Android",
        "device_brands": ["Poco M5", "Samsung Galaxy M14"],
        "os_name": "Android",
        "os_versions": ["13", "14"],
        "locale": "en_IN",
        "timezone": "Asia/Kolkata",
        "home_geo": (28.61, 77.21),       # Delhi
        "geo_jitter": 0.03,
        "top_mcc": ["5814", "5812", "5942"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 5.7,            # ~INR 300
        "amount_std_log": 0.5,
        "peak_hours": list(range(12, 15)) + list(range(20, 23)),
        "normal_txn_velocity_day": (0, 2),
        "normal_txn_velocity_year": (20, 60),
        "resolutions": ["720x1600", "1080x2340"],
        "sdk_versions": ["5.2.1"],
    },
    {
        "archetype": "business_professional",
        "platform": "Android",
        "device_brands": ["Samsung Galaxy S24 Ultra", "Google Pixel 8 Pro"],
        "os_name": "Android",
        "os_versions": ["14"],
        "locale": "en_IN",
        "timezone": "Asia/Kolkata",
        "home_geo": (17.39, 78.49),       # Hyderabad
        "geo_jitter": 0.02,
        "top_mcc": ["5411", "5812", "7399", "5946"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 8.2,            # ~INR 3600
        "amount_std_log": 0.8,
        "peak_hours": list(range(9, 18)),
        "normal_txn_velocity_day": (0, 4),
        "normal_txn_velocity_year": (60, 150),
        "resolutions": ["1440x3088", "1344x2992"],
        "sdk_versions": ["5.3.0", "5.3.1"],
    },
    {
        "archetype": "weekend_shopper",
        "platform": "Android",
        "device_brands": ["OnePlus 12", "OnePlus Nord 3"],
        "os_name": "Android",
        "os_versions": ["14"],
        "locale": "en_IN",
        "timezone": "Asia/Kolkata",
        "home_geo": (13.08, 80.27),       # Chennai
        "geo_jitter": 0.03,
        "top_mcc": ["5311", "5651", "5699"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 7.8,            # ~INR 2400
        "amount_std_log": 0.9,
        "peak_hours": list(range(10, 20)),
        "normal_txn_velocity_day": (0, 2),
        "normal_txn_velocity_year": (20, 50),
        "resolutions": ["1080x2412"],
        "sdk_versions": ["5.2.1", "5.3.0"],
    },
    {
        "archetype": "senior_conservative",
        "platform": "Android",
        "device_brands": ["Samsung Galaxy A54", "Samsung Galaxy A34"],
        "os_name": "Android",
        "os_versions": ["13"],
        "locale": "en_IN",
        "timezone": "Asia/Kolkata",
        "home_geo": (22.57, 88.36),       # Kolkata
        "geo_jitter": 0.02,
        "top_mcc": ["5411", "5912"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 6.8,            # ~INR 900
        "amount_std_log": 0.4,
        "peak_hours": list(range(9, 14)),
        "normal_txn_velocity_day": (0, 1),
        "normal_txn_velocity_year": (15, 40),
        "resolutions": ["1080x2340"],
        "sdk_versions": ["5.1.0"],
    },
    {
        "archetype": "gamer_digital_goods",
        "platform": "Android",
        "device_brands": ["ASUS ROG Phone 8", "Samsung Galaxy S24"],
        "os_name": "Android",
        "os_versions": ["14"],
        "locale": "en_IN",
        "timezone": "Asia/Kolkata",
        "home_geo": (15.36, 75.12),       # Hubli
        "geo_jitter": 0.01,
        "top_mcc": ["5816", "5818", "7994"],
        "country_code": "356",
        "currency_code": "356",
        "amount_mean_log": 5.5,            # ~INR 245
        "amount_std_log": 1.2,
        "peak_hours": list(range(20, 24)) + list(range(0, 3)),
        "normal_txn_velocity_day": (0, 5),
        "normal_txn_velocity_year": (80, 200),
        "resolutions": ["1080x2340", "1080x2400"],
        "sdk_versions": ["5.3.0"],
    },
    {
        "archetype": "nri_multi_currency",
        "platform": "iOS",
        "device_brands": ["iPhone 15 Pro Max"],
        "os_name": "iOS",
        "os_versions": ["17.5"],
        "locale": "en_US",
        "timezone": "America/New_York",
        "home_geo": (40.71, -74.01),      # New York
        "geo_jitter": 0.05,
        "top_mcc": ["5411", "5812", "5944"],
        "country_code": "840",
        "currency_code": "840",
        "amount_mean_log": 4.5,            # ~$90 (USD)
        "amount_std_log": 0.8,
        "peak_hours": list(range(10, 22)),
        "normal_txn_velocity_day": (0, 3),
        "normal_txn_velocity_year": (40, 100),
        "resolutions": ["1290x2796"],
        "sdk_versions": ["5.3.1"],
    },
]

# Merchant pools
REQUESTOR_IDS = [f"REQ{i:04d}" for i in range(1, 21)]
REQUESTOR_URLS = [f"https://pay{i}.merchant.com/3ds" for i in range(1, 11)]
MERCHANT_IDS = [f"MID{i:06d}" for i in range(1, 31)]
ACQUIRER_BINS = ["411111", "422222", "433333", "444444", "455555",
                 "466666", "477777", "488888", "499999", "500000"]
APP_PACKAGES = [f"com.merchant.pay.app{i}" for i in range(1, 6)]
SDK_REF_BASE = "SDK_REF_CONSTANT_HASH_V1"

INDIAN_CITIES = ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
                 "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow"]
EMAILS_DOMAIN = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"]


# ---------------------------------------------------------------------------
# Card Class
# ---------------------------------------------------------------------------

class Card:
    """Represents a cardholder with stable identity attributes."""

    def __init__(self, card_idx: int, archetype: dict):
        self.idx = card_idx
        self.archetype = archetype
        self.hash = hashlib.sha256(
            f"card_{card_idx:06d}".encode()
        ).hexdigest()

        # Stable identity
        self.normal_device = random.choice(archetype["device_brands"])
        self.normal_os_version = random.choice(archetype["os_versions"])
        self.normal_resolution = random.choice(archetype["resolutions"])
        self.home_subnet = (
            f"{random.randint(1,223)}."
            f"{random.randint(0,255)}."
            f"{random.randint(0,255)}."
        )
        self.normal_package = random.choice(APP_PACKAGES)
        self.sdk_ref = SDK_REF_BASE
        self.sdk_version = random.choice(archetype["sdk_versions"])

        self.primary_requestor = random.choice(REQUESTOR_IDS[:5])
        self.primary_req_url = random.choice(REQUESTOR_URLS[:3])
        self.primary_merchant = random.choice(MERCHANT_IDS[:10])
        self.primary_acquirer_bin = random.choice(ACQUIRER_BINS[:3])

        self.city = random.choice(INDIAN_CITIES)
        self.email = f"user{card_idx}@{random.choice(EMAILS_DOMAIN)}"
        self.phone = f"+91{random.randint(7000000000, 9999999999)}"
        self.billing_addr = f"{random.randint(1, 999)} {self.city} Main Road"
        self.sdk_app_id = f"sdk_app_{uuid.uuid4().hex[:8]}"
        self.device_name = (
            f"{archetype['platform']}_{self.normal_device.replace(' ', '_')}"
        )
        self.txn_count = 0

    def _make_timestamp(self, base_date, hour, dow):
        days_ahead = dow - base_date.weekday()
        if days_ahead < 0:
            days_ahead += 7
        target = base_date + timedelta(days=days_ahead)
        return target.replace(
            hour=hour,
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
        )


# ---------------------------------------------------------------------------
# Normal Transaction Generator
# ---------------------------------------------------------------------------

def generate_normal_txn(card: Card, base_date: datetime) -> dict:
    arch = card.archetype
    card.txn_count += 1

    all_hours = arch["peak_hours"] + list(range(9, 18))
    hour = random.choice(all_hours)
    dow = random.randint(0, 6)
    txn_time = card._make_timestamp(base_date, hour % 24, dow)

    amount = math.expm1(
        max(0, np.random.normal(arch["amount_mean_log"], arch["amount_std_log"]))
    )

    use_primary_device = random.random() < 0.92
    device = (card.normal_device if use_primary_device
              else random.choice(arch["device_brands"]))
    os_ver = (card.normal_os_version if use_primary_device
              else random.choice(arch["os_versions"]))
    resolution = (card.normal_resolution if use_primary_device
                  else random.choice(arch["resolutions"]))

    use_primary = random.random() < 0.7
    req_id = (card.primary_requestor if use_primary
              else random.choice(REQUESTOR_IDS))
    req_url = (card.primary_req_url if use_primary
               else random.choice(REQUESTOR_URLS))
    merchant_id = (card.primary_merchant if use_primary
                   else random.choice(MERCHANT_IDS))
    acquirer_bin = (card.primary_acquirer_bin if use_primary
                    else random.choice(ACQUIRER_BINS))

    lat = arch["home_geo"][0] + np.random.normal(0, arch["geo_jitter"])
    lon = arch["home_geo"][1] + np.random.normal(0, arch["geo_jitter"])
    ip = card.home_subnet + str(random.randint(1, 254))

    return {
        "card_id_hash": card.hash,
        "acctType": random.choices(["01", "02"], weights=[0.85, 0.15])[0],
        "mcc": random.choice(arch["top_mcc"]),
        "merchantCountryCode": arch["country_code"],
        "purchaseAmount": round(amount, 2),
        "purchaseCurrency": arch["currency_code"],
        "purchaseDate": txn_time.isoformat(),
        "cardSecurityCodeStatus": random.choices(
            ["01", "02", "03"], weights=[0.95, 0.03, 0.02])[0],
        "threeDSRequestorID": req_id,
        "threeDSRequestorName": f"Merchant {req_id}",
        "threeDSRequestorURL": req_url,
        "threeDSRequestorAuthenticationInd": random.choices(
            ["01", "02", "03"], weights=[0.80, 0.15, 0.05])[0],
        "threeDSReqAuthMethod": random.choices(
            ["01", "02", "06"], weights=[0.20, 0.50, 0.30])[0],
        "chAccAgeInd": "05",
        "chAccChangeInd": random.choices(
            ["01", "02", "03", "04", "05"],
            weights=[0.05, 0.05, 0.1, 0.3, 0.5])[0],
        "chAccPwChangeInd": random.choices(
            ["01", "02", "03", "04", "05"],
            weights=[0.05, 0.05, 0.1, 0.3, 0.5])[0],
        "txnActivityDay": random.randint(*arch["normal_txn_velocity_day"]),
        "txnActivityYear": random.randint(*arch["normal_txn_velocity_year"]),
        "provisionAttemptsDay": 0,
        "nbPurchaseAccount": random.randint(10, 100),
        "suspiciousAccActivity": "02",
        "shipNameIndicator": random.choices(
            ["01", "02"], weights=[0.95, 0.05])[0],
        "acquirerMerchantID": merchant_id,
        "acquirerBIN": acquirer_bin,
        "shipIndicator": random.choices(
            ["01", "02", "03", "04"], weights=[0.6, 0.15, 0.15, 0.1])[0],
        "billAddrLine1": card.billing_addr,
        "billAddrCity": card.city,
        "billAddrCountry": arch["country_code"],
        "billAddrPostCode": f"{random.randint(100000, 999999)}",
        "email": card.email,
        "mobilePhone": card.phone,
        "shipAddrCity": (card.city if random.random() < 0.7
                         else random.choice(INDIAN_CITIES)),
        "shipAddrCountry": arch["country_code"],
        "sdkInterface": random.choices(
            ["01", "02"], weights=[0.85, 0.15])[0],
        "sdkUiType": random.choices(
            ["01", "02", "03"], weights=[0.5, 0.3, 0.2])[0],
        "Platform": arch["platform"],
        "DeviceModel": device,
        "OSName": arch["os_name"],
        "OSVersion": os_ver,
        "Locale": arch["locale"],
        "TimeZone": arch["timezone"],
        "ScreenResolution": resolution,
        "DeviceName": card.device_name,
        "IPAddress": ip,
        "Latitude": round(lat, 6),
        "Longitude": round(lon, 6),
        "ApplicationPackageName": card.normal_package,
        "SDKAppID": card.sdk_app_id,
        "SDKVersion": card.sdk_version,
        "SDKRefNumber": card.sdk_ref,
        "dateTime": (
            txn_time + timedelta(seconds=random.randint(-5, 5))
        ).isoformat(),
        "is_anomaly": False,
        "anomaly_types": [],
    }


# ---------------------------------------------------------------------------
# Anomaly Injection (S8.4 -- 7 Types)
# ---------------------------------------------------------------------------

def inject_anomaly(txn: dict, card: Card, anomaly_type: str) -> dict:
    txn = txn.copy()
    txn["is_anomaly"] = True
    txn["anomaly_types"] = [anomaly_type]

    if anomaly_type == "platform_switch":
        if card.archetype["platform"] == "Android":
            txn["Platform"] = "iOS"
            txn["OSName"] = "iOS"
            txn["OSVersion"] = "17.5"
            txn["DeviceModel"] = random.choice(
                ["iPhone 15 Pro", "iPhone 14"])
        else:
            txn["Platform"] = "Android"
            txn["OSName"] = "Android"
            txn["OSVersion"] = "14"
            txn["DeviceModel"] = random.choice(
                ["Samsung Galaxy S24", "Google Pixel 8"])
        txn["DeviceName"] = (
            f"{txn['Platform']}_{txn['DeviceModel'].replace(' ', '_')}"
        )

    elif anomaly_type == "app_package_change":
        txn["ApplicationPackageName"] = (
            f"com.unknown.app.{uuid.uuid4().hex[:6]}"
        )

    elif anomaly_type == "amount_spike":
        multiplier = random.uniform(5, 20)
        typical = math.expm1(card.archetype["amount_mean_log"])
        txn["purchaseAmount"] = round(typical * multiplier, 2)

    elif anomaly_type == "geo_shift":
        shift_lat = random.uniform(5, 30) * random.choice([-1, 1])
        shift_lon = random.uniform(5, 40) * random.choice([-1, 1])
        txn["Latitude"] = round(
            card.archetype["home_geo"][0] + shift_lat, 6)
        txn["Longitude"] = round(
            card.archetype["home_geo"][1] + shift_lon, 6)
        txn["billAddrLine1"] = (
            f"{random.randint(1, 999)} Foreign Street"
        )
        txn["billAddrCity"] = random.choice(
            ["London", "Tokyo", "Dubai", "Singapore"])
        txn["billAddrCountry"] = random.choice(
            ["826", "392", "784", "702"])

    elif anomaly_type == "acctinfo_regression":
        txn["chAccAgeInd"] = random.choice(["01", "02"])
        txn["txnActivityDay"] = random.randint(10, 25)

    elif anomaly_type == "provision_spike":
        txn["provisionAttemptsDay"] = random.randint(3, 10)

    elif anomaly_type == "multi_attribute":
        sub_types = random.sample(
            ["platform_switch", "app_package_change", "amount_spike",
             "geo_shift", "acctinfo_regression", "provision_spike"],
            k=random.randint(2, 3),
        )
        for st in sub_types:
            txn = inject_anomaly(txn, card, st)
        # Restore the multi_attribute label plus the subtypes
        txn["anomaly_types"] = ["multi_attribute"] + sub_types
        txn["is_anomaly"] = True

    return txn


# ---------------------------------------------------------------------------
# Dataset Generation Pipeline
# ---------------------------------------------------------------------------

def generate_dataset():
    """Generate the full 100k-record dataset and write to PostgreSQL."""
    np.random.seed(42)
    random.seed(42)

    print("=" * 70)
    print("3DS Synthetic Dataset Generator  (-> PostgreSQL)")
    print("=" * 70)

    # 1. Create 1,000 cards
    cards = []
    for arch_idx, archetype in enumerate(CARD_ARCHETYPES):
        for card_within in range(100):
            card_idx = arch_idx * 100 + card_within
            cards.append(Card(card_idx, archetype))
    print(f"  Created {len(cards)} cards across "
          f"{len(CARD_ARCHETYPES)} archetypes")

    # 2. Profile-establishment transactions (70 x 1000 = 70,000)
    all_transactions = []
    base_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

    print("  Generating 70,000 profile-establishment transactions...")
    for card in cards:
        for txn_idx in range(70):
            day_offset = int(txn_idx * (180 / 70)) + random.randint(0, 2)
            txn_date = base_date + timedelta(days=day_offset)
            txn = generate_normal_txn(card, txn_date)
            txn["phase"] = "establishment"
            txn["sequence_idx"] = txn_idx
            all_transactions.append(txn)

    est_count = sum(1 for t in all_transactions
                    if t["phase"] == "establishment")
    print(f"  -> {est_count} establishment records")

    # 3. Scoring-phase transactions (20 normal + 10 anomaly per card)
    anomaly_types_weighted = (
        ["platform_switch"] * 25 +
        ["app_package_change"] * 20 +
        ["amount_spike"] * 15 +
        ["geo_shift"] * 15 +
        ["acctinfo_regression"] * 10 +
        ["provision_spike"] * 10 +
        ["multi_attribute"] * 5
    )

    scoring_normals = 0
    scoring_anomalies = 0
    scoring_base = base_date + timedelta(days=190)

    print("  Generating 30,000 scoring-phase transactions...")
    for card in cards:
        card_scoring_txns = []

        for txn_idx in range(20):
            day_offset = random.randint(0, 60)
            txn_date = scoring_base + timedelta(days=day_offset)
            txn = generate_normal_txn(card, txn_date)
            txn["phase"] = "scoring"
            txn["sequence_idx"] = 70 + txn_idx
            card_scoring_txns.append(txn)
            scoring_normals += 1

        for txn_idx in range(10):
            day_offset = random.randint(0, 60)
            txn_date = scoring_base + timedelta(days=day_offset)
            txn = generate_normal_txn(card, txn_date)
            anomaly_type = random.choice(anomaly_types_weighted)
            txn = inject_anomaly(txn, card, anomaly_type)
            txn["phase"] = "scoring"
            txn["sequence_idx"] = 90 + txn_idx
            card_scoring_txns.append(txn)
            scoring_anomalies += 1

        random.shuffle(card_scoring_txns)
        all_transactions.extend(card_scoring_txns)

    print(f"  -> {scoring_normals} scoring normals + "
          f"{scoring_anomalies} scoring anomalies")
    print(f"  -> Total: {len(all_transactions)} transactions")

    # Anomaly breakdown
    anomaly_counts = {}
    for t in all_transactions:
        if t["is_anomaly"]:
            for at in t["anomaly_types"]:
                anomaly_counts[at] = anomaly_counts.get(at, 0) + 1
    print("\n  Anomaly type distribution:")
    for at, count in sorted(anomaly_counts.items(), key=lambda x: -x[1]):
        print(f"    {at}: {count} "
              f"({count / scoring_anomalies * 100:.1f}%)")

    # 4. Write to PostgreSQL
    print("\n  Connecting to PostgreSQL...")
    conn = get_connection()

    # Truncate existing data
    with conn.cursor() as cur:
        cur.execute("TRUNCATE synthetic_transactions RESTART IDENTITY CASCADE")
    conn.commit()
    print("  -> Cleared synthetic_transactions table")

    # Build rows
    all_columns = SQL_FIELD_COLUMNS + [
        "is_anomaly", "anomaly_types", "phase", "sequence_idx",
    ]
    rows = [payload_to_row(txn) for txn in all_transactions]

    print(f"  Inserting {len(rows)} rows into synthetic_transactions...")
    inserted = bulk_insert(conn, "synthetic_transactions", all_columns,
                           rows, batch_size=5000)
    print(f"  -> {inserted} rows inserted")

    # Verify count
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM synthetic_transactions")
        db_count = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM synthetic_transactions "
            "WHERE is_anomaly = TRUE"
        )
        db_anomaly = cur.fetchone()[0]
    print(f"  -> Verified: {db_count} total, {db_anomaly} anomalies in DB")

    conn.close()

    print("\n" + "=" * 70)
    print("Dataset generation complete!")
    print("=" * 70)

    return all_transactions, cards


if __name__ == "__main__":
    generate_dataset()
