import sys; sys.path.insert(0, 'd:/FRM Anamoly MVP/scoring-engine')
from app.features import extract_and_score
import psycopg2, json, os
import db_config
from db_config import get_connection, row_to_payload

import pgserver
from pathlib import Path
pg_data_dir = str(Path(__file__).resolve().parent.parent / ".pgdata")
pg = pgserver.get_server(pg_data_dir)
os.environ['PG_DSN'] = pg.get_uri()
conn = get_connection()
with conn.cursor() as cur:
    cur.execute("SELECT * FROM synthetic_transactions WHERE phase='scoring' AND is_anomaly=True AND 'amount_spike' = ANY(anomaly_types) LIMIT 1")
    row = cur.fetchone()
    col_names = [d[0] for d in cur.description]
    row_dict = dict(zip(col_names, row))
    payload = row_to_payload(row_dict)
    
    cur.execute(f"SELECT profile_data FROM synthetic_profiles WHERE card_id_hash='{payload['card_id_hash']}'")
    profile = cur.fetchone()[0]
    
    print("PROFILE TRANSACTION:")
    print(json.dumps(profile['transaction'], indent=2))
    for k,v in payload.items(): print(f"{k}: {repr(v)} ({type(v)})")

    cur.execute(f"SELECT profile_data FROM synthetic_profiles WHERE card_id_hash='{payload['card_id_hash']}'")
    profile = cur.fetchone()[0]

sv, _, cf = extract_and_score(payload, profile)
print('Surprise Vector:')
print(sv)
print('Cross Field:')
print(cf)
