"""Scheduled retention, using its metadata-only credential, never a migrator."""
import argparse
import os
import psycopg
parser=argparse.ArgumentParser();parser.add_argument('--expected-db',required=True);args=parser.parse_args()
# This identity must not read either application's .env/security credentials.
# Its own root-managed EnvironmentFile supplies a metadata-only DB credential.
if os.environ.get('PGDATABASE')!=args.expected_db:raise SystemExit('Database confirmation does not match')
host=os.environ.get('PGHOST','127.0.0.1')
if host not in {'127.0.0.1','::1'}:raise SystemExit('Local database endpoint required')
with psycopg.connect(host=host,port=int(os.environ.get('PGPORT','5432')),dbname=args.expected_db,
        user=os.environ['PGUSER'],password=os.environ.get('PGPASSWORD',''),connect_timeout=5,
        options='-c statement_timeout=30000 -c lock_timeout=5000') as conn:
    conn.execute("DELETE FROM security_audit_events WHERE created_at<clock_timestamp()-interval '90 days'")
    conn.execute("DELETE FROM security_request_metrics WHERE hour<clock_timestamp()-interval '30 days'")
    conn.execute("DELETE FROM security_rate_buckets WHERE updated_at<clock_timestamp()-interval '2 days' AND COALESCE(blocked_until,clock_timestamp())<=clock_timestamp()")
    conn.execute("DELETE FROM store_sessions WHERE expires_at<clock_timestamp()-interval '90 days'")
    conn.execute("DELETE FROM admin_sessions WHERE expires_at<clock_timestamp()-interval '90 days'")
print('Security retention completed; business records and notification publishing progress preserved')
