"""Daily event retention with a dedicated metadata-only credential.

Never imports application configuration or resets notification publication state.
"""
import argparse
import os
import psycopg

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--expected-db', required=True)
args = parser.parse_args()
if os.environ.get('PGDATABASE') != args.expected_db:
    raise SystemExit('Database confirmation does not match')
host = os.environ.get('PGHOST', '127.0.0.1')
if host not in {'127.0.0.1', '::1'}:
    raise SystemExit('Local database endpoint required')
with psycopg.connect(host=host, port=int(os.environ.get('PGPORT', '5432')), dbname=args.expected_db,
        user=os.environ['PGUSER'], password=os.environ.get('PGPASSWORD', ''), connect_timeout=5,
        options='-c statement_timeout=30000 -c lock_timeout=5000') as conn:
    conn.execute('SELECT pg_advisory_xact_lock(7192040)')
    removed = conn.execute("DELETE FROM order_created_events WHERE recorded_at<clock_timestamp()-INTERVAL '7 days'").rowcount
print(f'Expired notification events removed: {removed}; publication state preserved')
