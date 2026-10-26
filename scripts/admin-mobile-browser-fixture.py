"""Isolated fixture for the admin mobile browser checks; no manual-mirror writes."""
import argparse
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5380)
args = parser.parse_args()
if not 1024 <= args.port <= 65535:
    parser.error('A non-privileged local test port is required')

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mobile_fixture', root / 'scripts/order-selection-browser-fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
fixture.fixtures.seed()
fixture.fixtures.fixture_file('/uploads/fixture.pdf')

# Keep dashboard data inside the current reporting period instead of relying
# on a hard-coded month offset. Only the isolated fixture's dates change.
today = datetime.now(timezone(timedelta(hours=8))).date()
with fixture.fixtures.db.get_connection() as conn:
    conn.execute("""UPDATE orders SET created_at = created_at +
        (%s::date - (SELECT max(created_at)::date FROM orders)) * interval '1 day'""", (today,))

fixture.fixtures.application.ADMIN_FRONTEND_DIST = root / 'frontend/dist'
fixture.fixtures.application.app.run(host='127.0.0.1', port=args.port, threaded=True, use_reloader=False)
