"""Default is read-only preview. --apply explicitly grants dashboard once, audited."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
from sales_dashboard_access import apply_once, candidates

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
with db._connect() as conn:
    if not args.apply:
        conn.execute('SET TRANSACTION READ ONLY')
        result = {'readOnly': True, 'candidateIds': [row['id'] for row in candidates(conn)]}
    else:
        result = apply_once(conn)
print(json.dumps(result))
