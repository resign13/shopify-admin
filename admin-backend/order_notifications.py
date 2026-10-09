"""Session-bound order notifications. No order, stock or financial writes."""
import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import timedelta

import db

PUBLISH_LOCK = 7192040
PAGE_SIZE = 100


class NotificationError(Exception):
    def __init__(self, message, status=409, code='notification_cursor_invalid'):
        super().__init__(message)
        self.status, self.code = status, code


def enabled():
    return os.environ.get('ORDER_VOICE_ENABLED', '').lower() in {'1', 'true', 'on'}


def _secret():
    value = os.environ.get('ORDER_VOICE_CURSOR_SECRET', '').encode()
    if len(value) < 32:
        raise NotificationError('语音提醒签名配置尚未就绪', 503, 'notification_configuration')
    return value


def _clock():
    return db._fetch_one('SELECT clock_timestamp() AS now')['now']


def _identity(token):
    row = db._fetch_one('SELECT s.id FROM admin_sessions s JOIN admin_users u ON u.id=s.admin_user_id '
                        "WHERE s.token=%s AND u.status='active'", (token,))
    if not row:
        raise NotificationError('登录已失效，请重新登录', 401, 'notification_session_invalid')
    return row['id']


def _pack(data):
    raw = base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':'), sort_keys=True).encode()).decode().rstrip('=')
    signature = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + '.' + signature


def _unpack(value, session):
    try:
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError()
        raw, signature = value.split('.')
        expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
        if data['v'] != 1 or data['s'] != session or type(data['p']) is not int:
            raise ValueError()
        row = db._fetch_one('SELECT baseline FROM order_notification_starts WHERE session_id=%s AND request_id=%s',
                            (session, uuid.UUID(data['r'])))
        if not row or data['b'] != row['baseline'] or data['p'] < data['b']:
            raise ValueError()
        if not 0 <= _clock().timestamp() - data['t'] <= 7 * 86400:
            raise ValueError()
        return data
    except NotificationError:
        raise
    except (ValueError, KeyError, TypeError, OverflowError):
        raise NotificationError('提醒进度已失效，请重新开启语音提醒') from None


def _publish():
    # READ COMMITTED: take a fresh snapshot AFTER acquiring the publisher lock.
    # The order INSERT trigger never acquires this lock.
    db._fetch_one('SELECT pg_advisory_xact_lock(%s)', (PUBLISH_LOCK,))
    previous = db._fetch_one('SELECT last_sequence FROM order_notification_state WHERE singleton')['last_sequence']
    row = db._fetch_one('''WITH pending AS (
        SELECT id, row_number() OVER (ORDER BY id) AS n FROM order_created_events
        WHERE publish_sequence IS NULL
      ), published AS (
        UPDATE order_created_events e SET publish_sequence=%s+p.n FROM pending p
        WHERE e.id=p.id RETURNING e.publish_sequence
      ) SELECT COALESCE(MAX(publish_sequence),%s) AS last FROM published''', (previous, previous))
    db._fetch_one('UPDATE order_notification_state SET last_sequence=%s WHERE singleton RETURNING singleton', (row['last'],))
    return row['last']


def _visible(rows, user):
    owner = user['id'] if user['role'] == 'sales' else None
    ids = [row['id'] for row in rows]
    if not ids:
        return []
    return db._fetch_all('''SELECT e.id AS "eventId", o.id AS "orderId", o.order_no AS "orderNo",
        e.recorded_at AS "createdAt" FROM order_created_events e JOIN orders o ON o.id=e.order_id
        WHERE e.id=ANY(%s) AND o.status<>'cancelled' AND o.order_no NOT LIKE 'TEMP-%%'
        AND (%s::bigint IS NULL OR o.owner_admin_id=%s) ORDER BY e.publish_sequence''', (ids, owner, owner))


def _response(events, **extra):
    for row in events:
        row['createdAt'] = row['createdAt'].isoformat()
    return {'enabled': True, 'events': events, **extra}


def start(token, body):
    now = _clock()
    if not enabled():
        return {'enabled': False, 'serverTime': now.isoformat()}
    _secret()
    session = _identity(token)
    try:
        request_id = uuid.UUID(str(body.get('requestId', '')))
    except ValueError:
        raise NotificationError('requestId 必须为 UUID', 400, 'notification_request_invalid') from None
    high = _publish()
    row = db._fetch_one('''INSERT INTO order_notification_starts(session_id,request_id,baseline)
        VALUES(%s,%s,%s) ON CONFLICT(session_id,request_id) DO UPDATE SET request_id=EXCLUDED.request_id
        RETURNING baseline,started_at''', (session, request_id, high))
    cursor = _pack({'v': 1, 's': session, 'r': str(request_id), 'b': row['baseline'], 'p': row['baseline'], 't': now.timestamp()})
    return {'enabled': True, 'cursor': cursor, 'serverTime': now.isoformat()}


def poll(token, body, user):
    now = _clock()
    if not enabled():
        return {'enabled': False, 'serverTime': now.isoformat()}
    data = _unpack(body.get('cursor'), _identity(token))
    high = _publish()
    recovery = body.get('recovery') is True or 'end' in data
    if recovery and 'end' not in data:
        data.update(end=high, cutoff=(now - timedelta(minutes=10)).timestamp())
    boundary = data.get('end', high)
    scanned = db._fetch_all('SELECT id,publish_sequence,recorded_at FROM order_created_events '
                            'WHERE publish_sequence>%s AND publish_sequence<=%s ORDER BY publish_sequence LIMIT %s',
                            (data['p'], boundary, PAGE_SIZE + 1))
    has_more = len(scanned) > PAGE_SIZE
    rows = scanned[:PAGE_SIZE]
    data['p'] = rows[-1]['publish_sequence'] if has_more else boundary
    eligible = [row for row in rows if not recovery or row['recorded_at'].timestamp() >= data['cutoff']]
    events = _visible(eligible, user)
    cutoff = data.get('cutoff')
    if recovery and not has_more:
        data.pop('end', None)
        data.pop('cutoff', None)
    data['t'] = now.timestamp()
    return _response(events, cursor=_pack(data), serverTime=now.isoformat(), hasMore=has_more,
                     recovery=recovery, recoveryComplete=recovery and not has_more, cutoffAt=cutoff)


def validate(token, body, user):
    now = _clock()
    if not enabled():
        return {'enabled': False, 'serverTime': now.isoformat()}
    data = _unpack(body.get('cursor'), _identity(token))
    ids = body.get('eventIds')
    if not isinstance(ids, list) or len(ids) > PAGE_SIZE or any(type(i) is not int or i <= 0 for i in ids):
        raise NotificationError('eventIds 最多包含 100 个有效事件编号', 400, 'notification_request_invalid')
    rows = db._fetch_all('SELECT id FROM order_created_events WHERE id=ANY(%s) '
                         'AND publish_sequence>%s AND publish_sequence<=%s', (ids, data['b'], data['p']))
    return _response(_visible(rows, user), serverTime=now.isoformat())


def cleanup():
    # No publication-counter reset, no business-table writes.
    with db.get_connection() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (PUBLISH_LOCK,))
        rows = conn.execute("DELETE FROM order_created_events WHERE recorded_at<clock_timestamp()-INTERVAL '7 days' RETURNING id").fetchall()
    return len(rows)
