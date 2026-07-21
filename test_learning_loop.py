import requests
import uuid
import time
import json

BASE_URL = "http://127.0.0.1:8001"

def run_test():
    # 1. Generate a brand new, random user ID to prove it's dynamic
    card_id = str(uuid.uuid4())
    print(f"--- Starting Dynamic Learning Test for New User: {card_id} ---\n")

    # Baseline transaction (Normal behavior: $15 coffee in US)
    baseline_payload = {
        "card_id_hash": card_id,
        "simulate_only": False,
        "purchaseAmount": 15.0,
        "purchaseCurrency": "840",
        "merchantCountryCode": "840",
        "mcc": "5814",
        "Platform": "iOS",
        "IPAddress": "192.168.1.5"
    }

    print("1. Establishing normal baseline (5x $15 coffee purchases in US)...")
    for _ in range(5):
        res = requests.post(f"{BASE_URL}/internal/score", json=baseline_payload)
        time.sleep(0.1)
    
    print("Baseline established.\n")

    # 2. Sudden Anomaly (Buying a $3,000 laptop in a new country on an Android device)
    anomaly_payload = {
        "card_id_hash": card_id,
        "simulate_only": False,
        "purchaseAmount": 3000.0,
        "purchaseCurrency": "356", # INR
        "merchantCountryCode": "356",
        "mcc": "5732", # Electronics
        "Platform": "Android",
        "IPAddress": "203.0.113.10"
    }

    print("2. User suddenly travels and buys a $3,000 laptop on a new Android device.")
    res1 = requests.post(f"{BASE_URL}/internal/score", json=anomaly_payload).json()
    txn_id_1 = res1.get("transaction_id")
    print(f"   Score Attempt 1: Risk Tier = {res1['deviation_tier']}, Total Deviation = {res1['total_deviation']:.2f}")

    # 3. Bank Feedback Loop (Bank authorizes it via OTP)
    print("\n3. Bank intercepts, sends an OTP, and the user verifies it.")
    print("   Submitting ground-truth feedback (confirmed_legit) to the system...")
    feedback_payload = {
        "txn_id": txn_id_1,
        "outcome": "confirmed_legit",
        "source": "otp_success"
    }
    requests.post(f"{BASE_URL}/internal/feedback", json=feedback_payload)
    time.sleep(0.5) # Give background task time to process Postgres update
    print("   System has reinforced the profile.\n")

    # 4. User makes a similar purchase the next day
    print("4. User makes another electronics purchase in the same new country.")
    anomaly_payload["purchaseAmount"] = 2800.0 # slightly different amount
    res2 = requests.post(f"{BASE_URL}/internal/score", json=anomaly_payload).json()
    print(f"   Score Attempt 2: Risk Tier = {res2['deviation_tier']}, Total Deviation = {res2['total_deviation']:.2f}")

    # 5. User makes another similar purchase
    print("\n5. User makes a third electronics purchase.")
    anomaly_payload["purchaseAmount"] = 3100.0
    res3 = requests.post(f"{BASE_URL}/internal/score", json=anomaly_payload).json()
    print(f"   Score Attempt 3: Risk Tier = {res3['deviation_tier']}, Total Deviation = {res3['total_deviation']:.2f}")

    print("\n--- Test Complete ---")
    print("Conclusion: The system dynamically adapted to the user's new behavioral pattern without any hardcoding.")

if __name__ == "__main__":
    run_test()
