"""Small isolated browser fixture for the dashboard Excel export."""
import os
import sys
from pathlib import Path

if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise RuntimeError('Explicit local *_test database required')
os.environ.update(APP_ENV='test', DB_SCHEMA_AUTO_MIGRATE='1', SECURITY_ADMIN_CAPTCHA_ENABLED='0', ORDER_VOICE_ENABLED='0')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'admin-backend'))
from test_dashboard import DashboardTest, application

fixture = DashboardTest()
fixture.setUp()
for index in range(12):
    fixture.product(f'EXTRA-{index:02}', stock=index)
application.ADMIN_FRONTEND_DIST = root / 'frontend/dist'
application.app.run(host='127.0.0.1', port=5395, threaded=True, use_reloader=False)
