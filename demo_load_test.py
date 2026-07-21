import asyncio
import httpx
import asyncpg
import random
import time
import json
from datetime import datetime, timezone

DB_DSN = "postgresql://postgres:password@127.0.0.1:5432/postgres"
API_URL = "http://127.0.0.1:8000/internal/score"

def extract_top_key(freq_dict: dict, default: str) -> str:
    if not freq_dict: return default
    return max(freq_dict.items(), key=lambda x: x[1])[0]

def build_payload(card_id: str, profile: dict, tx_type: str) -> dict:
    """Builds a transaction payload based on the user's actual ML profile."""
    # Base perfectly normal payload derived from their own history
    txn = profile.get("transaction", {})
    dev = profile.get("device", {})
    req = profile.get("requestor", {})
    
    amount = float(txn.get("amount_ewma", 1000.0))
    if amount < 10: amount = 1000.0
    
    payload = {
        "simulate_only": True,
        "card_id_hash": card_id,
        "acctType": extract_top_key(txn.get("acct_type_freq", {}), "01"),
        "mcc": extract_top_key(txn.get("mcc_freq", {}), "5411"),
        "merchantCountryCode": extract_top_key(txn.get("country_freq", {}), "356"),
        "purchaseAmount": round(amount, 2),
        "purchaseCurrency": extract_top_key(txn.get("currency_freq", {}), "356"),
        "purchaseDate": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "Platform": extract_top_key(dev.get("platform_freq", {}), "Android"),
        "DeviceModel": extract_top_key(dev.get("device_model_freq", {}), "Samsung Galaxy A34"),
        "OSName": extract_top_key(dev.get("os_name_freq", {}), "Android"),
        # Fill in defaults to prevent IF model flagging as anomalous
        "threeDSRequestorID": "REQ0001",
        "threeDSRequestorAuthenticationInd": "01",
        "threeDSReqAuthMethod": "02",
        "chAccAgeInd": "05",
        "chAccChangeInd": "05",
        "chAccPwChangeInd": "05",
        "txnActivityDay": 1,
        "txnActivityYear": 50,
        "nbPurchaseAccount": 10,
        "shipIndicator": "01",
        "cardSecurityCodeStatus": "01",
        "IPAddress": "192.168.1.100",
        "Latitude": 18.52,
        "Longitude": 73.85,
    }
    
    # Mutate based on requested type
    if tx_type == "suspicious":
        # Slight deviations: Unusually high amount for them, different MCC
        payload["purchaseAmount"] = round(amount * 4.5, 2)
        payload["mcc"] = "5999" # Misc
        
    elif tx_type == "abnormal":
        # Huge deviations: 20x amount, foreign country, new device
        payload["purchaseAmount"] = round(amount * 25.0, 2)
        payload["merchantCountryCode"] = "840" # US
        payload["Platform"] = "iOS"
        payload["DeviceModel"] = "iPhone 15 Pro"
        payload["OSName"] = "iOS"
        payload["ApplicationPackageName"] = "com.fraud.app"
        payload["IPAddress"] = "192.168.99.99"
        
    return payload

async def fetch_profiles():
    print("Fetching 50 real established profiles from Postgres...")
    conn = await asyncpg.connect(DB_DSN)
    rows = await conn.fetch("SELECT card_id_hash, profile FROM card_profiles LIMIT 50")
    await conn.close()
    return rows

async def send_transaction(client: httpx.AsyncClient, payload: dict, tx_type: str):
    start = time.time()
    try:
        resp = await client.post(API_URL, json=payload, timeout=5.0)
        resp.raise_for_status()
        latency = (time.time() - start) * 1000
        report = resp.json()
        return {
            "card_id": payload["card_id_hash"][:8],
            "type": tx_type,
            "tier": report["deviation_tier"],
            "score": report["total_deviation"],
            "latency": latency
        }
    except Exception as e:
        return {"error": str(e)}

async def main():
    rows = await fetch_profiles()
    if not rows:
        print("No profiles found. Did you run the data ingestion?")
        return
        
    # Generate varied transactions
    payloads = []
    types = []
    
    for i, row in enumerate(rows):
        card_id = row["card_id_hash"]
        profile = json.loads(row["profile"]) if isinstance(row["profile"], str) else row["profile"]
        
        # 60% normal, 20% suspicious, 20% abnormal
        if i % 5 == 0:
            tx_type = "abnormal"
        elif i % 5 == 1:
            tx_type = "suspicious"
        else:
            tx_type = "normal"
            
        payload = build_payload(card_id, profile, tx_type)
        payloads.append((payload, tx_type))
        
    print(f"\n--- Firing {len(payloads)} concurrent mixed transactions to the Scoring Engine ---\n")
    
    start_total = time.time()
    async with httpx.AsyncClient() as client:
        tasks = [send_transaction(client, p, t) for p, t in payloads]
        results = await asyncio.gather(*tasks)
    total_time = time.time() - start_total
    
    # Print beautiful results
    print(f"{'CARD ID':<10} | {'TX TYPE':<12} | {'RISK TIER':<8} | {'DEVIATION':<10} | {'LATENCY':<10}")
    print("-" * 60)
    
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "ERROR": 0}
    for res in results:
        if "error" in res:
            print(f"Error: {res['error']}")
            counts["ERROR"] += 1
            continue
            
        tier = res["tier"]
        counts[tier] += 1
        
        # Terminal colors
        color = "\033[92m" if tier == "LOW" else ("\033[93m" if tier == "MEDIUM" else "\033[91m")
        reset = "\033[0m"
        
        print(f"{res['card_id']:<10} | {res['type']:<12} | {color}{tier:<8}{reset} | {res['score']:<10.2f} | {res['latency']:<6.1f} ms")

    print("\n" + "="*60)
    print(f"[*] Load Test Completed in {total_time:.3f} seconds")
    print(f"[*] Results Breakdown: {counts['LOW']} Normal, {counts['MEDIUM']} Suspicious, {counts['HIGH']} Blocked")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
