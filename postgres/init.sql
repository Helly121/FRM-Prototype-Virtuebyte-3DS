-- ============================================================
-- 3DS Anomaly Detection System — PostgreSQL Schema (v5)
-- Complete schema including ALL runtime and pipeline tables.
-- This file runs automatically on first docker compose up.
-- ============================================================

-- Enable pgcrypto for SHA-256 hashing in seed data
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- 1. Runtime tables
-- ============================================================

-- Scored transactions log (audit)
CREATE TABLE IF NOT EXISTS scored_transactions (
    id                   BIGSERIAL PRIMARY KEY,
    txn_id               TEXT NOT NULL UNIQUE,
    card_id_hash         TEXT NOT NULL,
    scored_at            TIMESTAMPTZ DEFAULT NOW(),
    deviation_tier       TEXT CHECK (deviation_tier IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    total_deviation      FLOAT,
    if_score             FLOAT,
    profile_confidence   FLOAT,
    channel              TEXT DEFAULT 'SDK',
    contributing_factors JSONB,
    full_report          JSONB,
    outcome_label        TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_card_id   ON scored_transactions(card_id_hash);
CREATE INDEX IF NOT EXISTS idx_scored_at ON scored_transactions(scored_at);
CREATE INDEX IF NOT EXISTS idx_tier      ON scored_transactions(deviation_tier);
CREATE INDEX IF NOT EXISTS idx_outcome   ON scored_transactions(outcome_label);

-- Outcome feedback (chargeback, analyst review, OTP success)
CREATE TABLE IF NOT EXISTS outcome_feedback (
    id          BIGSERIAL PRIMARY KEY,
    txn_id      TEXT REFERENCES scored_transactions(txn_id),
    feedback_at TIMESTAMPTZ DEFAULT NOW(),
    outcome     TEXT CHECK (outcome IN ('confirmed_legit', 'confirmed_fraud', 'chargeback')),
    source      TEXT
);

-- ============================================================
-- 2. Runtime card profiles table (THE KEY TABLE)
-- ============================================================

CREATE TABLE IF NOT EXISTS card_profiles (
    card_id_hash        TEXT PRIMARY KEY,
    profile             JSONB NOT NULL,
    version             INTEGER NOT NULL DEFAULT 1,
    transaction_count   INTEGER DEFAULT 0,
    profile_confidence  FLOAT DEFAULT 0.0,
    trust_state         TEXT NOT NULL DEFAULT 'normal'
                        CHECK (trust_state IN ('normal','elevated_scrutiny')),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profile_updated ON card_profiles(updated_at);
CREATE INDEX IF NOT EXISTS idx_profile_gin     ON card_profiles USING GIN (profile jsonb_path_ops);

-- ============================================================
-- 3. Global blocklist
-- ============================================================

CREATE TABLE IF NOT EXISTS global_blocklist (
    id          BIGSERIAL PRIMARY KEY,
    field       TEXT NOT NULL,
    value_hash  TEXT NOT NULL,
    flagged_at  TIMESTAMPTZ DEFAULT NOW(),
    source_card TEXT NOT NULL,
    UNIQUE (field, value_hash)
);

-- ============================================================
-- 4. Profile reinforcement log
-- ============================================================

CREATE TABLE IF NOT EXISTS profile_reinforcement_log (
    id            BIGSERIAL PRIMARY KEY,
    card_id_hash  TEXT NOT NULL,
    reinforced_at TIMESTAMPTZ DEFAULT NOW(),
    reason        TEXT
);

-- ============================================================
-- 5. Offline pipeline tables (synthetic data & training)
-- ============================================================

CREATE TABLE IF NOT EXISTS synthetic_transactions (
    id                                  SERIAL PRIMARY KEY,
    card_id_hash                        TEXT NOT NULL,
    acct_type                           TEXT,
    mcc                                 TEXT,
    merchant_country_code               TEXT,
    purchase_amount                     FLOAT,
    purchase_currency                   TEXT,
    purchase_date                       TEXT,
    card_security_code_status           TEXT,
    three_ds_requestor_id               TEXT,
    three_ds_requestor_name             TEXT,
    three_ds_requestor_url              TEXT,
    three_ds_requestor_authentication_ind TEXT,
    three_ds_req_auth_method            TEXT,
    ch_acc_age_ind                      TEXT,
    ch_acc_change_ind                   TEXT,
    ch_acc_pw_change_ind                TEXT,
    txn_activity_day                    INTEGER,
    txn_activity_year                   INTEGER,
    provision_attempts_day              INTEGER,
    nb_purchase_account                 INTEGER,
    suspicious_acc_activity             TEXT,
    ship_name_indicator                 TEXT,
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
    is_anomaly                          BOOLEAN NOT NULL DEFAULT FALSE,
    anomaly_types                       TEXT[],
    phase                               TEXT,
    sequence_idx                        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_syn_card    ON synthetic_transactions(card_id_hash);
CREATE INDEX IF NOT EXISTS idx_syn_phase   ON synthetic_transactions(phase);
CREATE INDEX IF NOT EXISTS idx_syn_anomaly ON synthetic_transactions(is_anomaly);

CREATE TABLE IF NOT EXISTS synthetic_profiles (
    card_id_hash   TEXT PRIMARY KEY,
    profile_data   JSONB NOT NULL,
    txn_count      INTEGER,
    confidence     FLOAT,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS synthetic_surprise_vectors (
    id              SERIAL PRIMARY KEY,
    card_id_hash    TEXT NOT NULL,
    transaction_id  INTEGER NOT NULL REFERENCES synthetic_transactions(id),
    surprise_vector FLOAT[] NOT NULL,
    is_anomaly      BOOLEAN NOT NULL DEFAULT FALSE,
    anomaly_types   TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_sv_card    ON synthetic_surprise_vectors(card_id_hash);
CREATE INDEX IF NOT EXISTS idx_sv_anomaly ON synthetic_surprise_vectors(is_anomaly);

-- ============================================================
-- 6. Demo seed data — 100 realistic card profiles
-- ============================================================
-- These profiles are inserted so the Profile Explorer works
-- immediately after docker compose up without any manual steps.
-- Profiles are realistic JSON blobs mirroring the structure
-- that main.py's new_cold_profile() + update_profile() produce.

DO $$
DECLARE
    i INT;
    card_hash TEXT;
    profile_json JSONB;
    platforms TEXT[] := ARRAY['Android','Android','Android','Android','iOS','iOS','Android','Android','Android','iOS'];
    device_models TEXT[] := ARRAY[
        'Samsung Galaxy S23','Samsung Galaxy A54','Redmi Note 12',
        'OnePlus 12','iPhone 15 Pro','iPhone 14 Pro',
        'Google Pixel 8 Pro','Realme C55','Samsung Galaxy S24 Ultra','iPhone 15'
    ];
    os_names TEXT[] := ARRAY['Android','Android','Android','Android','iOS','iOS','Android','Android','Android','iOS'];
    os_versions TEXT[] := ARRAY['14','13','13','14','17.4','17.5','14','12','14','17.5'];
    locales TEXT[] := ARRAY['en_IN','en_IN','hi_IN','en_IN','en_IN','en_IN','en_IN','hi_IN','en_IN','en_US'];
    timezones TEXT[] := ARRAY[
        'Asia/Kolkata','Asia/Kolkata','Asia/Kolkata','Asia/Kolkata','Asia/Kolkata',
        'Asia/Kolkata','Asia/Kolkata','Asia/Kolkata','Asia/Kolkata','America/New_York'
    ];
    lats FLOAT[] := ARRAY[18.52,19.07,26.85,12.97,28.61,17.39,13.08,22.57,15.36,40.71];
    lons FLOAT[] := ARRAY[73.85,72.88,80.95,77.59,77.21,78.49,80.27,88.36,75.12,-74.01];
    mccs TEXT[] := ARRAY['5411','5812','5912','5541','7011','3000','5999','5411','5816','5944'];
    amounts FLOAT[] := ARRAY[1800,7300,500,13000,300,3600,2400,900,245,90];
    txn_count_arr INT[] := ARRAY[72,85,43,91,56,67,38,81,95,62];
    arch_idx INT;
BEGIN
    FOR i IN 1..100 LOOP
        arch_idx := ((i - 1) % 10) + 1;
        -- Use sha256 of 'card_XXXXXX' to match generate_dataset.py
        card_hash := encode(
            digest('card_' || lpad((i-1)::TEXT, 6, '0'), 'sha256'),
            'hex'
        );

        profile_json := jsonb_build_object(
            '_meta', jsonb_build_object(
                'card_id_hash', card_hash,
                'created_at', extract(epoch from now() - interval '180 days'),
                'last_updated', extract(epoch from now() - (random() * 3600 * 24 * 7)::INT),
                'history_depth_days', 180.0,
                'transaction_count', txn_count_arr[arch_idx],
                'profile_confidence', LEAST(1.0, txn_count_arr[arch_idx]::FLOAT / 50.0)
            ),
            'transaction', jsonb_build_object(
                'acct_type_freq', jsonb_build_object('01', 0.9, '02', 0.1),
                'mcc_freq', jsonb_build_object(mccs[arch_idx], 0.7, '5999', 0.2, '5412', 0.1),
                'country_freq', jsonb_build_object(
                    CASE WHEN arch_idx = 10 THEN '840' ELSE '356' END, 0.95,
                    CASE WHEN arch_idx = 10 THEN '356' ELSE '840' END, 0.05
                ),
                'currency_freq', jsonb_build_object(
                    CASE WHEN arch_idx = 10 THEN '840' ELSE '356' END, 0.95
                ),
                'amount_ewma_log', ln(1 + amounts[arch_idx]),
                'amount_ewma_var', (0.4 + random() * 0.4)::FLOAT,
                'hour_hist', '[0.025,0.02,0.015,0.01,0.01,0.01,0.015,0.02,0.03,0.04,0.05,0.06,0.07,0.08,0.08,0.07,0.065,0.06,0.07,0.08,0.085,0.09,0.08,0.06]'::JSONB,
                'dow_hist', '[0.12,0.14,0.13,0.14,0.16,0.17,0.14]'::JSONB,
                'cvv_match_rate', 0.97
            ),
            'requestor', jsonb_build_object(
                'known_requestors', jsonb_build_object(
                    'REQ0001', jsonb_build_object('freq', 45, 'last_seen', extract(epoch from now() - 3600)),
                    'REQ0002', jsonb_build_object('freq', 20, 'last_seen', extract(epoch from now() - 86400))
                ),
                'known_req_urls', jsonb_build_object(
                    'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
                    jsonb_build_object('freq', 45, 'last_seen', extract(epoch from now() - 3600))
                ),
                'auth_ind_freq', jsonb_build_object('01', 0.85, '02', 0.1, '03', 0.05),
                'auth_method_freq', jsonb_build_object('02', 0.6, '01', 0.2, '06', 0.2),
                'ch_acc_age_ind_last', 5,
                'ch_acc_change_ind_ewma', 4.2,
                'ch_acc_pw_change_ind_ewma', 4.5,
                'txn_activity_day_ewma', 1.2,
                'txn_activity_day_var', 0.5,
                'txn_activity_year_ewma', 52.0,
                'txn_activity_year_var', 25.0,
                'provision_attempts_ewma', 0.0,
                'provision_attempts_var', 0.01,
                'nb_purchase_ewma', 42.0,
                'nb_purchase_var', 10.0,
                'suspicious_ever', false,
                'ship_name_match_rate', 0.96
            ),
            'merchant', jsonb_build_object(
                'known_merchant_ids', jsonb_build_object(
                    'MID000001', jsonb_build_object('freq', 30, 'last_seen', extract(epoch from now() - 3600)),
                    'MID000002', jsonb_build_object('freq', 15, 'last_seen', extract(epoch from now() - 86400))
                ),
                'known_acquirer_bins', jsonb_build_object(
                    '411111', jsonb_build_object('freq', 40, 'last_seen', extract(epoch from now() - 3600))
                ),
                'ship_ind_freq', jsonb_build_object('01', 0.65, '02', 0.2, '03', 0.15),
                'billing_addr_hashes', jsonb_build_object(
                    encode(digest(
                        '123 main road|' || lower(
                            CASE arch_idx
                                WHEN 1 THEN 'pune'
                                WHEN 2 THEN 'mumbai'
                                WHEN 3 THEN 'lucknow'
                                WHEN 4 THEN 'bangalore'
                                WHEN 5 THEN 'delhi'
                                WHEN 6 THEN 'hyderabad'
                                WHEN 7 THEN 'chennai'
                                WHEN 8 THEN 'kolkata'
                                WHEN 9 THEN 'hubli'
                                ELSE 'new york'
                            END
                        ) || '|' ||
                        CASE WHEN arch_idx = 10 THEN '840' ELSE '356' END ||
                        '|400001',
                        'sha256'
                    ), 'hex'),
                    jsonb_build_object('freq', 35, 'last_seen', extract(epoch from now() - 3600))
                ),
                'shipping_addr_hashes', '{}',
                'known_email_hashes', '{}',
                'known_phone_hashes', '{}',
                'billing_lat', lats[arch_idx],
                'billing_lon', lons[arch_idx],
                'billing_radius_km', 5.0,
                'shipping_lat', lats[arch_idx],
                'shipping_lon', lons[arch_idx],
                'shipping_radius_km', 10.0
            ),
            'device', jsonb_build_object(
                'platform_freq', jsonb_build_object(platforms[arch_idx], 0.98, 'Other', 0.02),
                'device_model_freq', jsonb_build_object(device_models[arch_idx], 0.95, 'Other', 0.05),
                'os_name_freq', jsonb_build_object(os_names[arch_idx], 0.98),
                'os_version_freq', jsonb_build_object(os_versions[arch_idx], 0.95),
                'locale_freq', jsonb_build_object(locales[arch_idx], 0.97),
                'known_timezones', jsonb_build_object(
                    timezones[arch_idx],
                    jsonb_build_object('freq', txn_count_arr[arch_idx], 'last_seen', extract(epoch from now() - 3600))
                ),
                'known_resolutions', jsonb_build_object(
                    CASE
                        WHEN platforms[arch_idx] = 'iOS' THEN '1179x2556'
                        ELSE '1080x2340'
                    END,
                    jsonb_build_object('freq', txn_count_arr[arch_idx], 'last_seen', extract(epoch from now() - 3600))
                ),
                'known_ip_subnets', jsonb_build_object(
                    '192.168.1.0/24',
                    jsonb_build_object('freq', txn_count_arr[arch_idx], 'last_seen', extract(epoch from now() - 3600))
                ),
                'device_fp_hashes', '{}',
                'known_app_packages', jsonb_build_object(
                    encode(digest('com.merchant.pay.app1|' || device_models[arch_idx] || '|' || os_versions[arch_idx] || '|com.merchant.pay.app1', 'sha256'), 'hex'),
                    jsonb_build_object('freq', txn_count_arr[arch_idx], 'last_seen', extract(epoch from now() - 3600))
                ),
                'known_sdk_app_ids', '{}',
                'sdk_version_freq', jsonb_build_object('5.3.0', 0.8, '5.2.1', 0.2),
                'expected_sdk_ref_hash', encode(digest('SDK_REF_CONSTANT_HASH_V1', 'sha256'), 'hex'),
                'known_device_names', '{}',
                'known_sdk_interfaces', '{}',
                'geo_lat', lats[arch_idx],
                'geo_lon', lons[arch_idx],
                'geo_radius_km', 3.0,
                'probation', '{}'
            )
        );

        INSERT INTO card_profiles (
            card_id_hash, profile, version,
            transaction_count, profile_confidence,
            trust_state, created_at, updated_at
        ) VALUES (
            card_hash,
            profile_json,
            1,
            txn_count_arr[arch_idx],
            LEAST(1.0, txn_count_arr[arch_idx]::FLOAT / 50.0),
            'normal',
            NOW() - interval '180 days',
            NOW() - (random() * interval '7 days')
        )
        ON CONFLICT (card_id_hash) DO NOTHING;
    END LOOP;
END;
$$;

-- ============================================================
-- 7. Seed demo audit log (50 entries so Audit Log is populated)
-- ============================================================
DO $$
DECLARE
    i INT;
    tiers TEXT[] := ARRAY['LOW','LOW','LOW','MEDIUM','HIGH'];
    scores FLOAT[] := ARRAY[0.12,0.31,0.52,1.78,3.45];
    card_hashes TEXT[];
BEGIN
    SELECT ARRAY(SELECT card_id_hash FROM card_profiles ORDER BY created_at LIMIT 10)
    INTO card_hashes;

    IF array_length(card_hashes, 1) IS NULL THEN
        RETURN;
    END IF;

    FOR i IN 1..50 LOOP
        INSERT INTO scored_transactions (
            txn_id, card_id_hash, scored_at,
            deviation_tier, total_deviation, if_score,
            profile_confidence, channel,
            contributing_factors, full_report
        ) VALUES (
            'txn_seed_' || lpad(i::TEXT, 8, '0'),
            card_hashes[((i - 1) % array_length(card_hashes, 1)) + 1],
            NOW() - ((50 - i) * interval '10 minutes'),
            tiers[((i - 1) % 5) + 1],
            scores[((i - 1) % 5) + 1],
            CASE WHEN tiers[((i - 1) % 5) + 1] = 'HIGH' THEN -0.25
                 WHEN tiers[((i - 1) % 5) + 1] = 'MEDIUM' THEN -0.08
                 ELSE 0.05 END,
            0.85,
            'SDK',
            '[]'::JSONB,
            '{}'::JSONB
        ) ON CONFLICT (txn_id) DO NOTHING;
    END LOOP;
END;
$$;

-- ============================================================
-- 8. Seed blocklist entries (demo only)
-- ============================================================
INSERT INTO global_blocklist (field, value_hash, source_card)
VALUES
    ('device.ApplicationPackageName', encode(digest('com.fraud.app', 'sha256'), 'hex'), 'seed_demo'),
    ('device.IPAddress', encode(digest('8.8.8.8', 'sha256'), 'hex'), 'seed_demo')
ON CONFLICT (field, value_hash) DO NOTHING;
