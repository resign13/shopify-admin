"""Schema checks are read-only. Optional HTTP smoke writes notification progress only.

Uses existing active sessions without logging in or changing any staff session.
Never creates accounts, business orders, stock changes or synthetic order events.
"""
import argparse
import json
import sys
from pathlib import Path
from urllib import request, error
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--http', action='store_true')
parser.add_argument('--expect-enabled', choices=['enable', 'disable'], default='disable')
args = parser.parse_args()

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
import module_permissions

with db._connect() as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    row = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='orders'::regclass "
                       "AND tgname='orders_created_notification' AND tgenabled='O') AS ready").fetchone()
    assert row['ready'], 'Order notification trigger missing or disabled'
    assert conn.execute('SELECT COUNT(*) AS n FROM order_notification_state').fetchone()['n'] == 1
    assert conn.execute('SELECT NOT EXISTS(SELECT 1 FROM order_created_events e, order_notification_state s '
                        'WHERE e.publish_sequence>s.last_sequence) AS valid').fetchone()['valid']
print('Notification schema and publication progress verified (read-only).')

if args.http:
    opener = request.build_opener(request.ProxyHandler({}))

    def post(operation, body, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = request.Request('http://127.0.0.1:5302/api/admin/order-notifications/' + operation,
                              data=json.dumps(body).encode(), headers=headers, method='POST')
        try:
            with opener.open(req, timeout=15) as response:
                return response.status, json.load(response)
        except error.HTTPError as response:
            return response.code, {}  # No credentials, cursors or response content in diagnostics.

    assert post('start', {'requestId': str(uuid.uuid4())})[0] == 401, 'Anonymous request was not rejected'
    with db._connect() as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        sessions = conn.execute("SELECT DISTINCT ON (u.role) s.token,u.id,u.role,u.permissions "
                                "FROM admin_sessions s JOIN admin_users u ON u.id=s.admin_user_id "
                                "WHERE u.status='active' AND u.role IN ('admin','sales','warehouse') "
                                "ORDER BY u.role,s.id DESC").fetchall()
    expected = args.expect_enabled == 'enable'
    checked = []
    for user in sessions:
        if 'orders' not in module_permissions.effective(user):
            continue
        body = {'requestId': str(uuid.uuid4())}
        status, start = post('start', body, user['token'])
        assert status == 200 and start.get('enabled') is expected, 'Live start switch check failed'
        if expected:
            status, retry = post('start', body, user['token'])
            assert status == 200 and retry.get('enabled'), 'Live start retry failed'
            status, result = post('poll', {'cursor': start['cursor']}, user['token'])
            assert status == 200 and result.get('enabled'), 'Live poll failed'
            assert all(set(e) == {'eventId','orderId','orderNo','createdAt'} for e in result['events']), 'Non-minimal event fields'
            if user['role'] == 'sales' and result['events']:
                ids = [e['orderId'] for e in result['events']]
                with db._connect() as conn:
                    conn.execute('SET TRANSACTION READ ONLY')
                    assert conn.execute('SELECT COUNT(*) AS n FROM orders WHERE id=ANY(%s) AND owner_admin_id=%s',
                                        (ids,user['id'])).fetchone()['n'] == len(ids), 'Sales ownership mismatch'
            status, valid = post('validate', {'cursor': result['cursor'], 'eventIds': []}, user['token'])
            assert status == 200 and valid.get('events') == [], 'Live validate failed'
            assert post('poll', {'cursor': 'invalid'}, user['token'])[0] == 409, 'Invalid cursor not rejected'
        checked.append(user['role'])
    assert checked, 'No existing active permitted staff session is available for live HTTP verification'
    print('Live notification HTTP checks passed: enabled=%s roles=%s; no business writes or new sessions.'
          % (expected, ','.join(checked)))
