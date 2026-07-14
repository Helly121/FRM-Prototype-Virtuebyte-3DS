"""
db_config.py — Shared database configuration and field mapping for offline scripts.

Provides:
  - PostgreSQL connection helper (psycopg2)
  - Bidirectional mapping between payload dict keys (camelCase/PascalCase)
    and SQL column names (snake_case)
  - Bulk insert helper using execute_values
"""

import os
import psycopg2
import psycopg2.extras


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_pg_dsn() -> str:
    """Return the PostgreSQL DSN from env or default."""
    return os.getenv(
        "PG_DSN",
        "postgresql://postgres:postgres@localhost:5432/anomaly_db",
    )


def get_connection():
    """Open a psycopg2 connection to PostgreSQL."""
    return psycopg2.connect(get_pg_dsn())


# ---------------------------------------------------------------------------
# Field Mapping — payload key  ↔  SQL column name
# ---------------------------------------------------------------------------
# The generate_dataset.py script produces dicts with mixed-case keys that
# match the 3DS spec and the scoring-engine's expectations.  The SQL schema
# uses snake_case columns.  This mapping is the single source of truth for
# that translation.

PAYLOAD_TO_SQL = {
    # -- Transaction Details --
    "card_id_hash":                       "card_id_hash",
    "acctType":                           "acct_type",
    "mcc":                                "mcc",
    "merchantCountryCode":                "merchant_country_code",
    "purchaseAmount":                     "purchase_amount",
    "purchaseCurrency":                   "purchase_currency",
    "purchaseDate":                       "purchase_date",
    "cardSecurityCodeStatus":             "card_security_code_status",
    # -- 3DS Requestor --
    "threeDSRequestorID":                 "three_ds_requestor_id",
    "threeDSRequestorName":               "three_ds_requestor_name",
    "threeDSRequestorURL":                "three_ds_requestor_url",
    "threeDSRequestorAuthenticationInd":  "three_ds_requestor_authentication_ind",
    "threeDSReqAuthMethod":               "three_ds_req_auth_method",
    # -- acctInfo --
    "chAccAgeInd":                        "ch_acc_age_ind",
    "chAccChangeInd":                     "ch_acc_change_ind",
    "chAccPwChangeInd":                   "ch_acc_pw_change_ind",
    "txnActivityDay":                     "txn_activity_day",
    "txnActivityYear":                    "txn_activity_year",
    "provisionAttemptsDay":               "provision_attempts_day",
    "nbPurchaseAccount":                  "nb_purchase_account",
    "suspiciousAccActivity":              "suspicious_acc_activity",
    "shipNameIndicator":                  "ship_name_indicator",
    # -- Merchant Details --
    "acquirerMerchantID":                 "acquirer_merchant_id",
    "acquirerBIN":                        "acquirer_bin",
    "shipIndicator":                      "ship_indicator",
    "billAddrLine1":                      "bill_addr_line1",
    "billAddrCity":                       "bill_addr_city",
    "billAddrCountry":                    "bill_addr_country",
    "billAddrPostCode":                   "bill_addr_post_code",
    "email":                              "email",
    "mobilePhone":                        "mobile_phone",
    "shipAddrCity":                       "ship_addr_city",
    "shipAddrCountry":                    "ship_addr_country",
    # -- Device Details (SDK) --
    "sdkInterface":                       "sdk_interface",
    "sdkUiType":                          "sdk_ui_type",
    "Platform":                           "platform",
    "DeviceModel":                        "device_model",
    "OSName":                             "os_name",
    "OSVersion":                          "os_version",
    "Locale":                             "locale",
    "TimeZone":                           "time_zone",
    "ScreenResolution":                   "screen_resolution",
    "DeviceName":                         "device_name",
    "IPAddress":                          "ip_address",
    "Latitude":                           "latitude",
    "Longitude":                          "longitude",
    "ApplicationPackageName":             "application_package_name",
    "SDKAppID":                           "sdk_app_id",
    "SDKVersion":                         "sdk_version",
    "SDKRefNumber":                       "sdk_ref_number",
    "dateTime":                           "date_time",
}

# Reverse mapping: SQL column → payload key
SQL_TO_PAYLOAD = {v: k for k, v in PAYLOAD_TO_SQL.items()}

# Ordered list of the 50-field SQL columns (excludes labels / metadata)
SQL_FIELD_COLUMNS = list(PAYLOAD_TO_SQL.values())

# Ordered list of the corresponding payload keys
PAYLOAD_FIELD_KEYS = list(PAYLOAD_TO_SQL.keys())


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def payload_to_row(txn: dict) -> tuple:
    """
    Convert a payload dict to a tuple of values in SQL_FIELD_COLUMNS order,
    followed by (is_anomaly, anomaly_types, phase, sequence_idx).
    """
    values = []
    for payload_key in PAYLOAD_FIELD_KEYS:
        v = txn.get(payload_key)
        # Ensure correct Python types for psycopg2
        if isinstance(v, float) and payload_key not in ("purchaseAmount", "Latitude", "Longitude"):
            v = str(v) if v else None
        values.append(v)

    # Append label / metadata columns
    values.append(bool(txn.get("is_anomaly", False)))
    values.append(txn.get("anomaly_types", []) or [])
    values.append(txn.get("phase", ""))
    values.append(txn.get("sequence_idx", 0))
    return tuple(values)


def row_to_payload(row: dict) -> dict:
    """
    Convert a row dict (SQL column names) back to a payload dict
    (original camelCase/PascalCase keys) for use with the scoring engine.
    """
    payload = {}
    for sql_col, payload_key in SQL_TO_PAYLOAD.items():
        if sql_col in row:
            payload[payload_key] = row[sql_col]
    return payload


# ---------------------------------------------------------------------------
# Bulk insert helper
# ---------------------------------------------------------------------------

def build_insert_sql(table: str, columns: list) -> str:
    """Build a parameterised INSERT statement."""
    cols = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    return f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"


def bulk_insert(conn, table: str, columns: list, rows: list,
                batch_size: int = 5000):
    """
    Bulk-insert rows using execute_values for performance.
    Returns the number of rows inserted.
    """
    template = "(" + ", ".join(["%s"] * len(columns)) + ")"
    cols = ", ".join(columns)
    sql = f"INSERT INTO {table} ({cols}) VALUES %s"

    inserted = 0
    with conn.cursor() as cur:
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            psycopg2.extras.execute_values(
                cur, sql, batch, template=template, page_size=batch_size,
            )
            inserted += len(batch)
    conn.commit()
    return inserted
