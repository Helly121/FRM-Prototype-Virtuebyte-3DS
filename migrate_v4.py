import asyncio
import asyncpg
import os

PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@127.0.0.1:5432/postgres")

async def migrate():
    print(f"Connecting to {PG_DSN}")
    conn = await asyncpg.connect(PG_DSN)
    
    # 1. Rename and modify synthetic_profiles -> card_profiles
    print("Migrating synthetic_profiles -> card_profiles...")
    await conn.execute("""
        ALTER TABLE synthetic_profiles RENAME TO card_profiles;
        ALTER TABLE card_profiles RENAME COLUMN profile_data TO profile;
        ALTER TABLE card_profiles RENAME COLUMN txn_count TO transaction_count;
        ALTER TABLE card_profiles RENAME COLUMN confidence TO profile_confidence;
        
        ALTER TABLE card_profiles ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE card_profiles ADD COLUMN IF NOT EXISTS trust_state TEXT NOT NULL DEFAULT 'normal' CHECK (trust_state IN ('normal','elevated_scrutiny'));
        ALTER TABLE card_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
    """)
    
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_profile_updated ON card_profiles(updated_at);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_profile_gin ON card_profiles USING GIN (profile jsonb_path_ops);")
    
    # 2. Create outcome_feedback
    print("Creating outcome_feedback...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS outcome_feedback (
            id BIGSERIAL PRIMARY KEY,
            txn_id UUID NOT NULL,
            outcome TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_txn ON outcome_feedback(txn_id);
    """)
    
    # 3. Create global_blocklist
    print("Creating global_blocklist...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS global_blocklist (
            id BIGSERIAL PRIMARY KEY,
            field TEXT NOT NULL,
            value_hash TEXT NOT NULL,
            flagged_at TIMESTAMPTZ DEFAULT NOW(),
            source_card TEXT NOT NULL,
            UNIQUE (field, value_hash)
        );
    """)
    
    # 4. Create profile_reinforcement_log
    print("Creating profile_reinforcement_log...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS profile_reinforcement_log (
            id BIGSERIAL PRIMARY KEY,
            card_id_hash TEXT NOT NULL,
            reinforced_at TIMESTAMPTZ DEFAULT NOW(),
            reason TEXT
        );
    """)
    
    # 5. Alter scored_transactions for outcome_label
    print("Altering scored_transactions...")
    await conn.execute("""
        ALTER TABLE scored_transactions ADD COLUMN IF NOT EXISTS outcome_label TEXT;
    """)

    await conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
