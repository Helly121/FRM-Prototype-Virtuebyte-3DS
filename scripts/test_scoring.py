"""Quick end-to-end scoring test — reads profile from PostgreSQL."""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring-engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.features import extract_and_score
from app.report import build_report
from db_config import get_connection
import joblib

# Load one profile from PostgreSQL
conn = get_connection()
with conn.cursor() as cur:
    cur.execute(
        "SELECT card_id_hash, profile_data "
        "FROM synthetic_profiles LIMIT 1"
    )
    card_id, profile_data = cur.fetchone()
conn.close()

profile = json.loads(profile_data) if isinstance(profile_data, str) else profile_data
model = joblib.load("model/isolation_forest.pkl")

# Normal payload
payload = {
    "card_id_hash": card_id,
    "acctType": "01", "mcc": "5411", "merchantCountryCode": "356",
    "purchaseAmount": 1500.0, "purchaseCurrency": "356",
    "purchaseDate": "2026-06-27T14:30:00+05:30",
    "cardSecurityCodeStatus": "01",
    "threeDSRequestorID": "REQ0001",
    "threeDSRequestorURL": "https://pay1.merchant.com/3ds",
    "threeDSRequestorAuthenticationInd": "01",
    "threeDSReqAuthMethod": "02",
    "chAccAgeInd": "05", "chAccChangeInd": "05", "chAccPwChangeInd": "05",
    "txnActivityDay": 1, "txnActivityYear": 50,
    "provisionAttemptsDay": 0, "nbPurchaseAccount": 50,
    "suspiciousAccActivity": "02", "shipNameIndicator": "01",
    "acquirerMerchantID": "MID000001", "acquirerBIN": "411111",
    "shipIndicator": "01",
    "billAddrLine1": "123 Main Road", "billAddrCity": "Mumbai",
    "billAddrCountry": "356", "billAddrPostCode": "400001",
    "email": "user0@gmail.com", "mobilePhone": "+919876543210",
    "shipAddrCity": "Mumbai", "shipAddrCountry": "356",
    "Platform": "Android", "DeviceModel": "Samsung Galaxy S23",
    "OSName": "Android", "OSVersion": "14",
    "Locale": "en_IN", "TimeZone": "Asia/Kolkata",
    "ScreenResolution": "1080x2340",
    "IPAddress": "192.168.1.100", "Latitude": 18.52, "Longitude": 73.85,
    "ApplicationPackageName": "com.merchant.pay.app1",
    "SDKVersion": "5.3.0", "SDKRefNumber": "SDK_REF_CONSTANT_HASH_V1",
    "dateTime": "2026-06-27T14:30:03+05:30",
    "DeviceName": "Android_Samsung_Galaxy_S23", "SDKAppID": "sdk_app_test",
}

start = time.time() * 1000
sv, contribs, cf = extract_and_score(payload, profile)
if_score = float(model.decision_function([sv])[0])
report = build_report(payload, sv, contribs, cf, if_score, profile, start)

key = "scoring_latency_ms"
print("=== NORMAL Transaction ===")
print(f"Tier: {report.deviation_tier}")
print(f"TotalDeviation: {report.total_deviation:.4f}")
print(f"IF Score: {report.if_score:.4f}")
print(f"Factors: {len(report.contributing_factors)}")
print(f"Latency: {report.metadata[key]:.1f}ms")
print()

# ANOMALOUS payload
anom = payload.copy()
anom["Platform"] = "iOS"
anom["OSName"] = "iOS"
anom["OSVersion"] = "17.5"
anom["DeviceModel"] = "iPhone 15 Pro"
anom["purchaseAmount"] = 95000.0
anom["ApplicationPackageName"] = "com.unknown.app.xyz123"

start = time.time() * 1000
sv, contribs, cf = extract_and_score(anom, profile)
if_score = float(model.decision_function([sv])[0])
report = build_report(anom, sv, contribs, cf, if_score, profile, start)

print("=== ANOMALOUS Transaction ===")
print(f"Tier: {report.deviation_tier}")
print(f"TotalDeviation: {report.total_deviation:.4f}")
print(f"IF Score: {report.if_score:.4f}")
print(f"Factors: {len(report.contributing_factors)}")
for f in report.contributing_factors[:6]:
    reason = f.reason[:90]
    print(f"  {f.dimension}: {f.contribution_pct:.1f}% - {reason}")
print(f"Latency: {report.metadata[key]:.1f}ms")
