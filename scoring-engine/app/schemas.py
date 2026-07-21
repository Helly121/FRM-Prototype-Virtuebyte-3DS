"""
schemas.py — Pydantic models for API request/response contracts.

Defines:
  - AReqPayload: 50-field input from the API Gateway
  - ContributingFactor: Per-field deviation detail
  - DeviationReport: Output contract (§12)
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any
from datetime import datetime


class AReqPayload(BaseModel):
    """
    Validated AReq payload from the API Gateway.
    The raw PAN is already replaced with card_id_hash by the gateway.
    All fields are optional with defaults to handle partial payloads gracefully.
    """

    # --- Identity (from gateway) ---
    card_id_hash: str = Field(..., title="Card ID Hash", description="SHA-256 hash of the Primary Account Number (PAN). Anonymised identity set by the API Gateway.")

    # --- Simulator Control ---
    simulate_only: bool = Field(False, title="Simulate Only", description="If True, skips writing the transaction into the historical profile to prevent corrupting the baseline during demos.")

    # --- Transaction Details ---
    acctType: Optional[str] = Field("01", title="Account Type", description="Type of account: 01 = Credit, 02 = Debit, 03 = Charge")
    mcc: Optional[str] = Field("", title="Merchant Category Code", description="4-digit ISO 18245 code describing the merchant's primary business (e.g., 5411 = Grocery Stores)")
    merchantCountryCode: Optional[str] = Field("", title="Merchant Country Code", description="3-digit ISO 3166-1 numeric country code of the merchant (e.g., 356 = India)")
    purchaseAmount: Optional[float] = Field(0.0, title="Purchase Amount", description="Transaction amount in the specified currency")
    purchaseCurrency: Optional[str] = Field("", title="Purchase Currency", description="3-digit ISO 4217 numeric currency code (e.g., 356 = INR)")
    purchaseDate: Optional[str] = Field("", title="Purchase Date", description="Date and time of the transaction, formatted as YYYYMMDDHHMMSS or ISO-8601")
    cardSecurityCodeStatus: Optional[str] = Field("01", title="CVV Status", description="Result of the CVV/CVC verification: 01 = Match, 02 = Mismatch, 03 = Not processed")

    # --- 3DS Requestor Details ---
    threeDSRequestorID: Optional[str] = Field("", title="3DS Requestor ID", description="Unique identifier assigned by the Directory Server (DS) to the 3DS Requestor")
    threeDSRequestorName: Optional[str] = Field("", title="3DS Requestor Name", description="Name of the 3DS Requestor (e.g., Amazon India)")
    threeDSRequestorURL: Optional[str] = Field("", title="3DS Requestor URL", description="Fully qualified URL of the 3DS Requestor website")
    threeDSRequestorAuthenticationInd: Optional[str] = Field("01", title="Authentication Indicator", description="Indicates the type of authentication requested: 01 = Payment, 02 = Recurring, 03 = Installment")
    threeDSReqAuthMethod: Optional[str] = Field("", title="Requestor Auth Method", description="Mechanism used by the Cardholder to authenticate to the 3DS Requestor: 01 = Static Password, 02 = Biometrics, 03 = FIDO")

    # --- Cardholder Account Information (acctInfo) ---
    chAccAgeInd: Optional[str] = Field("05", title="Account Age Indicator", description="Length of time the cardholder has had the account: 01 = No account, 02 = Created during txn, 03 = < 30 days, 04 = 30-60 days, 05 = > 60 days")
    chAccChangeInd: Optional[str] = Field("01", title="Account Change Indicator", description="Length of time since the account information was last changed: 01-04 (similar to age indicator)")
    chAccPwChangeInd: Optional[str] = Field("01", title="Password Change Indicator", description="Length of time since the account password was last changed: 01-05")
    txnActivityDay: Optional[int] = Field(0, title="Daily Transaction Activity", description="Number of transactions (successful and abandoned) for this cardholder account across all payment accounts in the previous 24 hours")
    txnActivityYear: Optional[int] = Field(0, title="Yearly Transaction Activity", description="Number of transactions for this cardholder account in the previous year")
    provisionAttemptsDay: Optional[int] = Field(0, title="Daily Provision Attempts", description="Number of Add Card attempts in the last 24 hours")
    nbPurchaseAccount: Optional[int] = Field(0, title="Number of Purchases", description="Number of purchases with this cardholder account during the previous six months")
    suspiciousAccActivity: Optional[str] = Field("02", title="Suspicious Activity", description="Indicates if the requestor has observed suspicious activity: 01 = Yes, 02 = No")
    shipNameIndicator: Optional[str] = Field("01", title="Shipping Name Indicator", description="Indicates if the Cardholder Name matches the Shipping Name: 01 = Match, 02 = Mismatch")

    # --- Merchant & Acquirer Details ---
    acquirerMerchantID: Optional[str] = Field("", title="Acquirer Merchant ID", description="Acquirer-assigned merchant identifier")
    acquirerBIN: Optional[str] = Field("", title="Acquirer BIN", description="Acquirer routing BIN")
    shipIndicator: Optional[str] = Field("01", title="Shipping Indicator", description="Type of shipping: 01 = Ship to billing address, 02 = Ship to verified address, 03 = Ship to different address")
    billAddrLine1: Optional[str] = Field("", title="Billing Address Line 1", description="First line of the billing address")
    billAddrCity: Optional[str] = Field("", title="Billing City", description="City of the billing address")
    billAddrCountry: Optional[str] = Field("", title="Billing Country", description="ISO 3166-1 numeric country code of the billing address")
    billAddrPostCode: Optional[str] = Field("", title="Billing Post/Zip Code", description="Zip or postal code of the billing address")
    email: Optional[str] = Field("", title="Cardholder Email", description="Email address of the cardholder")
    mobilePhone: Optional[str] = Field("", title="Cardholder Mobile", description="Mobile phone number of the cardholder (E.164 format preferred)")
    shipAddrCity: Optional[str] = Field("", title="Shipping City", description="City of the shipping address")
    shipAddrCountry: Optional[str] = Field("", title="Shipping Country", description="ISO 3166-1 numeric country code of the shipping address")

    # --- Device Details (App-based SDK channel) ---
    sdkInterface: Optional[str] = Field("", title="SDK Interface", description="SDK interface types supported: 01 = Native, 02 = HTML, 03 = Both")
    sdkUiType: Optional[str] = Field("", title="SDK UI Type", description="UI types supported by the SDK: 01 = Text, 02 = Single Select, 03 = Multi Select, 04 = OOB, 05 = HTML Other")
    Platform: Optional[str] = Field("", title="Device Platform", description="Operating system platform (e.g., Android, iOS)")
    DeviceModel: Optional[str] = Field("", title="Device Model", description="Manufacturer's model name/number (e.g., iPhone 15 Pro, Samsung Galaxy S23)")
    OSName: Optional[str] = Field("", title="OS Name", description="Name of the operating system")
    OSVersion: Optional[str] = Field("", title="OS Version", description="Version of the operating system")
    Locale: Optional[str] = Field("", title="Device Locale", description="Language and country locale configured on the device (e.g., en_IN)")
    TimeZone: Optional[str] = Field("", title="Device Timezone", description="IANA timezone string configured on the device (e.g., Asia/Kolkata)")
    ScreenResolution: Optional[str] = Field("", title="Screen Resolution", description="Resolution of the device screen (e.g., 1080x2340)")
    DeviceName: Optional[str] = Field("", title="Device Name", description="User-assigned name of the device (if accessible)")
    IPAddress: Optional[str] = Field("", title="Device IP Address", description="Public IP address of the device")
    Latitude: Optional[float] = Field(0.0, title="GPS Latitude", description="Latitude coordinate obtained via device GPS")
    Longitude: Optional[float] = Field(0.0, title="GPS Longitude", description="Longitude coordinate obtained via device GPS")
    ApplicationPackageName: Optional[str] = Field("", title="App Package Name", description="Package name of the merchant app embedding the 3DS SDK (e.g., com.merchant.app)")
    SDKAppID: Optional[str] = Field("", title="SDK App ID", description="Universally Unique ID created by the 3DS SDK for this app installation")
    SDKVersion: Optional[str] = Field("", title="SDK Version", description="Version of the EMV 3DS SDK installed")
    SDKRefNumber: Optional[str] = Field("", title="SDK Reference Number", description="EMVCo-assigned unique reference number for the SDK")
    dateTime: Optional[str] = Field("", title="Device Datetime", description="Current datetime as reported by the device clock")

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "card_id_hash": "my_test_card_999",
                    "acctType": "01",
                    "mcc": "5411",
                    "merchantCountryCode": "356",
                    "purchaseAmount": 1500.0,
                    "purchaseCurrency": "356",
                    "purchaseDate": "2026-06-27T14:30:00+05:30",
                    "cardSecurityCodeStatus": "01",
                    "threeDSRequestorID": "REQ0001",
                    "threeDSRequestorName": "Amazon India",
                    "threeDSRequestorURL": "https://amazon.in",
                    "threeDSRequestorAuthenticationInd": "01",
                    "threeDSReqAuthMethod": "02",
                    "chAccAgeInd": "05",
                    "chAccChangeInd": "05",
                    "chAccPwChangeInd": "05",
                    "txnActivityDay": 1,
                    "txnActivityYear": 50,
                    "provisionAttemptsDay": 0,
                    "nbPurchaseAccount": 50,
                    "suspiciousAccActivity": "02",
                    "shipNameIndicator": "01",
                    "acquirerMerchantID": "MID000001",
                    "acquirerBIN": "411111",
                    "shipIndicator": "01",
                    "billAddrLine1": "123 Main Road",
                    "billAddrCity": "Mumbai",
                    "billAddrCountry": "356",
                    "billAddrPostCode": "400001",
                    "email": "user0@gmail.com",
                    "mobilePhone": "+919876543210",
                    "shipAddrCity": "Mumbai",
                    "shipAddrCountry": "356",
                    "sdkInterface": "03",
                    "sdkUiType": "01",
                    "Platform": "Android",
                    "DeviceModel": "Samsung Galaxy S23",
                    "OSName": "Android",
                    "OSVersion": "14",
                    "Locale": "en_IN",
                    "TimeZone": "Asia/Kolkata",
                    "ScreenResolution": "1080x2340",
                    "DeviceName": "Android_Samsung_Galaxy_S23",
                    "IPAddress": "192.168.1.100",
                    "Latitude": 18.52,
                    "Longitude": 73.85,
                    "ApplicationPackageName": "com.merchant.pay.app1",
                    "SDKAppID": "sdk_app_test",
                    "SDKVersion": "5.3.0",
                    "SDKRefNumber": "SDK_REF_CONSTANT_HASH_V1",
                    "dateTime": "2026-06-27T14:30:03+05:30"
                }
            ]
        }
    )


class ContributingFactor(BaseModel):
    """Details on why a specific dimension flagged as anomalous."""
    field: str = Field(..., description="Dotted field path (e.g., device.Platform)")
    dimension: str = Field(..., description="Surprise dimension name (e.g., s_platform)")
    observed: Any = Field(..., description="Observed value in this transaction")
    raw_observed: Optional[str] = Field(None, description="Untruncated value used internally for feedback loops")
    expected: str = Field(..., description="Expected value/range from profile history")
    contribution_pct: float = Field(..., description="Percentage of TotalDeviation")
    reason: str = Field(..., description="Human-readable explanation")


class DeviationReport(BaseModel):
    """
    Output contract (§12). Returned to the API Gateway and logged to PostgreSQL.
    """
    transaction_id: str
    card_id: str
    evaluated_at: str
    channel: str = "SDK"
    deviation_tier: str = Field(..., description="LOW / MEDIUM / HIGH")
    profile_confidence: float
    total_deviation: float
    if_score: float
    summary: str
    contributing_factors: List[ContributingFactor]
    non_contributing_context: List[str]
    metadata: dict

    class Config:
        json_encoders = {
            float: lambda v: round(v, 4),
        }


class FeedbackPayload(BaseModel):
    """
    Payload for ground-truth feedback (OTP success, chargeback, analyst review).
    """
    txn_id: str = Field(..., description="The transaction ID that was previously scored")
    outcome: str = Field(..., description="'confirmed_legit', 'confirmed_fraud', or 'chargeback'")
    source: str = Field(..., description="'otp_success', 'analyst_review', or 'chargeback_file'")
