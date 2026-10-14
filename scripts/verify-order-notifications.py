"""Read-only schema and anonymous HTTP checks; never reuses staff credentials.

Does not log in, write progress, create orders or change inventory/sessions.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib import request, error
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--http', action='store_true')
parser.add_argument('--expect-enabled', choices=['enable', 'disable'])
parser.add_argument('--audio-sha256')
args = parser.parse_args()
if args.http and args.expect_enabled is None:
    parser.error('--expect-enabled is required for live verification')

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
import order_notifications

if args.expect_enabled is not None:
    assert order_notifications.enabled() == (args.expect_enabled == 'enable'), 'Loaded notification switch does not match the requested state'
    if args.expect_enabled == 'enable': order_notifications._secret()
    print('Runtime notification configuration verified; signing key not disclosed.')

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
    if args.audio_sha256:
        assets = Path(__file__).resolve().parents[1] / 'frontend' / 'dist' / 'assets'
        matching = [p for p in assets.glob('new-order-zh-CN-*.wav')
                    if hashlib.sha256(p.read_bytes()).hexdigest() == args.audio_sha256]
        assert matching, 'Deployed audio does not match the release recording'
        with opener.open('http://127.0.0.1:5302/assets/' + matching[0].name, timeout=15) as response:
            assert response.status == 200 and hashlib.sha256(response.read()).hexdigest() == args.audio_sha256, 'Live audio response mismatch'
        print('Live double-phrase WAV resource verified: SHA256=' + args.audio_sha256)

    def post(operation, body):
        headers = {'Content-Type': 'application/json'}
        req = request.Request('http://127.0.0.1:5302/api/admin/order-notifications/' + operation,
                              data=json.dumps(body).encode(), headers=headers, method='POST')
        try:
            with opener.open(req, timeout=15) as response:
                return response.status, json.load(response)
        except error.HTTPError as response:
            return response.code, {}  # No credentials, cursors or response content in diagnostics.

    # Production acceptance does not reconstruct or reuse staff credentials.
    assert post('start', {'requestId':str(uuid.uuid4())})[0] in {401,426}, 'Notification endpoint must reject unauthenticated requests'
    print('Live notification anonymous boundary verified; authenticated roles are covered by isolated cookie/browser tests.')
