import os
import sys
from pathlib import Path
import json

# Ensure scoring-engine is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring-engine"))

import pgserver
from fastapi.testclient import TestClient

def run_test():
    # 1. Start pgserver to get the persistent test data
    pg_data_dir = str(Path(__file__).resolve().parent.parent / ".pgdata")
    pg = pgserver.get_server(pg_data_dir)
    dsn = pg.get_uri()
    os.environ["PG_DSN"] = dsn
    print(f"PostgreSQL running at {dsn}")

    # Import app AFTER setting PG_DSN so it picks it up
    from app.main import app
    from db_config import get_connection

    # Fetch a profile and transaction from the DB
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT card_id_hash FROM synthetic_profiles LIMIT 1")
        card_id = cur.fetchone()[0]
    conn.close()

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

    # Start FastAPI TestClient (triggers lifespan events)
    print("Testing API...")
    with TestClient(app) as client:
        # Check health
        resp = client.get("/health")
        print("Health Check:", resp.json())
        assert resp.json()["postgres_connected"] == True
        assert resp.status_code == 200

        # Score normal transaction
        resp = client.post("/internal/score", json=payload)
        print("\nNormal Score HTTP Status:", resp.status_code)
        print(json.dumps(resp.json(), indent=2))
        assert resp.status_code == 200

if __name__ == "__main__":
    run_test()
