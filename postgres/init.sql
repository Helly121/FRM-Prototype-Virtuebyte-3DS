-- ============================================================
-- 3DS Anomaly Detection System — PostgreSQL Schema
-- ============================================================

-- ============================================================
-- 1. Runtime tables (audit log per §3.4)
-- ============================================================

-- Scored transactions log
CREATE TABLE IF NOT EXISTS scored_transactions (
    id                   BIGSERIAL PRIMARY KEY,
    txn_id               TEXT NOT NULL UNIQUE,
    card_id_hash         TEXT NOT NULL,
    scored_at            TIMESTAMPTZ DEFAULT NOW(),
    deviation_tier       TEXT CHECK (deviation_tier IN ('LOW', 'MEDIUM', 'HIGH')),
    total_deviation      FLOAT,
    if_score             FLOAT,
    profile_confidence   FLOAT,
    channel              TEXT DEFAULT 'SDK',
    contributing_factors JSONB,
    full_report          JSONB,
    outcome_label        TEXT DEFAULT NULL  -- populated by feedback API
);

-- Outcome feedback (chargeback, analyst review, OTP success)
CREATE TABLE IF NOT EXISTS outcome_feedback (
    id          BIGSERIAL PRIMARY KEY,
    txn_id      TEXT REFERENCES scored_transactions(txn_id),
    feedback_at TIMESTAMPTZ DEFAULT NOW(),
    outcome     TEXT CHECK (outcome IN ('confirmed_legit', 'confirmed_fraud', 'chargeback')),
    source      TEXT  -- 'chargeback_file', 'analyst_review', 'otp_success'
);

CREATE INDEX IF NOT EXISTS idx_card_id   ON scored_transactions(card_id_hash);
CREATE INDEX IF NOT EXISTS idx_scored_at ON scored_transactions(scored_at);
CREATE INDEX IF NOT EXISTS idx_tier      ON scored_transactions(deviation_tier);
CREATE INDEX IF NOT EXISTS idx_outcome   ON scored_transactions(outcome_label);

-- ============================================================
-- 2. Offline pipeline tables (synthetic data & training)
-- ============================================================

-- 100k synthetic 3DS transactions — one column per field
CREATE TABLE IF NOT EXISTS synthetic_transactions (
    id                                  SERIAL PRIMARY KEY,
    -- Transaction Details
    card_id_hash                        TEXT NOT NULL,
    acct_type                           TEXT,
    mcc                                 TEXT,
    merchant_country_code               TEXT,
    purchase_amount                     FLOAT,
    purchase_currency                   TEXT,
    purchase_date                       TEXT,
    card_security_code_status           TEXT,
    -- 3DS Requestor Details
    three_ds_requestor_id               TEXT,
    three_ds_requestor_name             TEXT,
    three_ds_requestor_url              TEXT,
    three_ds_requestor_authentication_ind TEXT,
    three_ds_req_auth_method            TEXT,
    -- acctInfo
    ch_acc_age_ind                      TEXT,
    ch_acc_change_ind                   TEXT,
    ch_acc_pw_change_ind                TEXT,
    txn_activity_day                    INTEGER,
    txn_activity_year                   INTEGER,
    provision_attempts_day              INTEGER,
    nb_purchase_account                 INTEGER,
    suspicious_acc_activity             TEXT,
    ship_name_indicator                 TEXT,
    -- Merchant Details
    acquirer_merchant_id                TEXT,
    acquirer_bin                        TEXT,
    ship_indicator                      TEXT,
    bill_addr_line1                     TEXT,
    bill_addr_city                      TEXT,
    bill_addr_country                   TEXT,
    bill_addr_post_code                 TEXT,
    email                               TEXT,
    mobile_phone                        TEXT,
    ship_addr_city                      TEXT,
    ship_addr_country                   TEXT,
    -- Device Details (SDK)
    sdk_interface                       TEXT,
    sdk_ui_type                         TEXT,
    platform                            TEXT,
    device_model                        TEXT,
    os_name                             TEXT,
    os_version                          TEXT,
    locale                              TEXT,
    time_zone                           TEXT,
    screen_resolution                   TEXT,
    device_name                         TEXT,
    ip_address                          TEXT,
    latitude                            FLOAT,
    longitude                           FLOAT,
    application_package_name            TEXT,
    sdk_app_id                          TEXT,
    sdk_version                         TEXT,
    sdk_ref_number                      TEXT,
    date_time                           TEXT,
    -- Labels & metadata
    is_anomaly                          BOOLEAN NOT NULL DEFAULT FALSE,
    anomaly_types                       TEXT[],
    phase                               TEXT,
    sequence_idx                        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_syn_card    ON synthetic_transactions(card_id_hash);
CREATE INDEX IF NOT EXISTS idx_syn_phase   ON synthetic_transactions(phase);
CREATE INDEX IF NOT EXISTS idx_syn_anomaly ON synthetic_transactions(is_anomaly);

-- Per-card sufficient statistics (profile JSON)
CREATE TABLE IF NOT EXISTS synthetic_profiles (
    card_id_hash   TEXT PRIMARY KEY,
    profile_data   JSONB NOT NULL,
    txn_count      INTEGER,
    confidence     FLOAT,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 40-dimensional surprise vectors for IF training
CREATE TABLE IF NOT EXISTS synthetic_surprise_vectors (
    id              SERIAL PRIMARY KEY,
    card_id_hash    TEXT NOT NULL,
    transaction_id  INTEGER NOT NULL REFERENCES synthetic_transactions(id),
    surprise_vector FLOAT[] NOT NULL,       -- 40-element array
    is_anomaly      BOOLEAN NOT NULL DEFAULT FALSE,
    anomaly_types   TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_sv_card    ON synthetic_surprise_vectors(card_id_hash);
CREATE INDEX IF NOT EXISTS idx_sv_anomaly ON synthetic_surprise_vectors(is_anomaly);
