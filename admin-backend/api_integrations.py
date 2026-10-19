"""Browser-owned machine credentials. No raw credential is retrievable."""
import hashlib
import os
import secrets
import uuid
from datetime import UTC, datetime
from functools import wraps

from flask import g, jsonify, request
import db
import module_permissions

BASE = '/api/admin/api-integrations'
SCOPES = ['products:read', 'inventory:read']


class Conflict(ValueError):
    pass


def eligible(user):
    return user['status'] == 'active' and user['role'] in module_permissions.STAFF_ROLES and 'api-integrations' in module_permissions.effective(user)


def iso(value):
    return value.astimezone(UTC).isoformat() if value else None


def metadata(conn, user_id):
    row = conn.execute('SELECT *,clock_timestamp() AS now FROM api_integrations WHERE admin_user_id=%s', (user_id,)).fetchone()
    if not row:
        return {'status': 'not_generated', 'keyId': None, 'keyLabel': None, 'version': 0,
                'expiresAt': None, 'lastUsedAt': None, 'calls24h': 0, 'adminBlocked': False}
    state = ('admin_blocked' if row['admin_blocked'] else 'not_generated' if not row['token_hash']
             else 'expired' if row['expires_at'] and row['expires_at'] <= row['now']
             else 'enabled' if row['enabled'] else 'owner_disabled')
    calls = conn.execute("SELECT COUNT(*) AS n FROM api_call_logs WHERE admin_user_id=%s AND created_at>clock_timestamp()-interval '24 hours'", (user_id,)).fetchone()['n']
    return {'status': state, 'keyId': str(row['key_id']) if row['key_id'] else None,
            'keyLabel': 'api_••••_' + str(row['key_id'])[-8:] if row['key_id'] else None,
            'version': row['version'], 'adminBlocked': row['admin_blocked'],
            'expiresAt': iso(row['expires_at']), 'lastUsedAt': iso(row['last_used_at']), 'calls24h': calls}


def expiry(body):
    value = body.get('expiresAt')
    if value is None or value == '': return None
    if not isinstance(value, str) or len(value) > 40: raise ValueError('有效期格式不正确')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result <= datetime.now(UTC): raise ValueError()
        return result
    except ValueError: raise ValueError('请选择带时区的未来到期时间') from None


def mutate(action, user_id=None):
    actor = g.current_user
    manager = user_id is not None
    if manager and not module_permissions.can_administer(actor): return jsonify({'message': 'Forbidden'}), 403
    user_id = user_id if manager else actor['id']
    body = request.get_json(silent=True) or {}
    version = body.get('version')
    if isinstance(version, bool) or not isinstance(version, int) or version < 0: raise ValueError('缺少有效版本，请刷新后重试')
    if any(k in body for k in ('key', 'token', 'tokenHash', 'adminBlocked')): raise ValueError('密钥由系统生成')
    token = None
    with db._connect() as conn:
        # Same lock order as the user UPDATE and its revocation trigger. A
        # concurrent permission removal cannot race a credential generation.
        owner = conn.execute('SELECT id,role,status,permissions FROM admin_users WHERE id=%s FOR UPDATE', (user_id,)).fetchone()
        if not owner or owner['role'] not in module_permissions.STAFF_ROLES:
            return jsonify({'message': 'Not found'}), 404
        conn.execute('INSERT INTO api_integrations(admin_user_id) VALUES(%s) ON CONFLICT DO NOTHING', (user_id,))
        row = conn.execute('SELECT *,clock_timestamp() AS now FROM api_integrations WHERE admin_user_id=%s FOR UPDATE', (user_id,)).fetchone()
        if row['version'] != version: raise Conflict('状态已改变，请刷新后重试')
        if not manager and (not eligible(owner) or row['admin_blocked']):
            return jsonify({'message': '管理员已禁用 API 授权或账号权限已撤销'}), 403
        event_key = row['key_id']
        if action in {'generate', 'reset'}:
            if action == 'generate' and row['token_hash']: raise Conflict('已有 Key，请使用重置')
            if action == 'reset' and not row['token_hash']: raise Conflict('尚无 Key，请使用生成')
            token = 'gapi_' + secrets.token_urlsafe(32)
            key_id = uuid.uuid4()
            event_key = key_id
            conn.execute('''UPDATE api_integrations SET token_hash=%s,key_id=%s,enabled=true,
                expires_at=%s,last_used_at=NULL WHERE admin_user_id=%s''',
                (hashlib.sha256(token.encode()).hexdigest(), key_id, expiry(body), user_id))
        elif action == 'status':
            enabled = body.get('enabled')
            if not isinstance(enabled, bool): raise ValueError('启用状态不正确')
            if not row['token_hash']: raise Conflict('请先生成 Key')
            if enabled and row['expires_at'] and row['expires_at'] <= row['now']: raise Conflict('Key 已过期，请重置')
            conn.execute('UPDATE api_integrations SET enabled=%s WHERE admin_user_id=%s', (enabled, user_id))
            action = 'owner_enabled' if enabled else 'owner_disabled'
        elif action == 'authorization':
            blocked = body.get('blocked')
            if not isinstance(blocked, bool): raise ValueError('授权状态不正确')
            conn.execute('UPDATE api_integrations SET admin_blocked=%s WHERE admin_user_id=%s', (blocked, user_id))
            action = 'admin_blocked' if blocked else 'admin_restored'
        elif action == 'revoke':
            conn.execute('UPDATE api_integrations SET token_hash=NULL,key_id=NULL,enabled=false WHERE admin_user_id=%s', (user_id,))
        else: raise ValueError('操作不正确')
        conn.execute('UPDATE api_integrations SET version=version+1,updated_at=clock_timestamp() WHERE admin_user_id=%s', (user_id,))
        conn.execute('INSERT INTO api_integration_events(actor_id,subject_id,key_id,event_code) VALUES(%s,%s,%s,%s)',
                     (actor['id'], user_id, event_key, action))
        result = metadata(conn, user_id)
    return jsonify({'item': result, **({'key': token} if token else {})})


def register(app, require_auth):
    from external_api_logging import install
    install(app)
    def guard(fn):
        @wraps(fn)
        @require_auth
        def wrapped(*args, **kwargs):
            if not eligible(g.current_user): return jsonify({'message': 'Forbidden'}), 403
            try: return fn(*args, **kwargs)
            except Conflict as exc: return jsonify({'message': str(exc), 'code': 'api_key_conflict'}), 409
            except ValueError as exc: return jsonify({'message': str(exc)}), 400
        return wrapped

    @app.get(BASE + '/me')
    @guard
    def api_integration_me():
        with db._connect() as conn: item = metadata(conn, g.current_user['id'])
        return jsonify({'item': item, 'scopes': SCOPES,
                        'canManage': module_permissions.can_administer(g.current_user),
                        'baseUrl': os.environ.get('EXTERNAL_API_PUBLIC_ORIGIN', 'https://gingtto.store').rstrip('/') + '/api/external/v1'})

    for action, method in [('generate', 'POST'), ('reset', 'POST'), ('status', 'PUT')]:
        app.add_url_rule(BASE + '/me/' + action, 'api_integration_' + action,
                         guard(lambda action=action: mutate(action)), methods=[method])

    @app.get(BASE + '/accounts')
    @guard
    def api_integration_accounts():
        if not module_permissions.can_administer(g.current_user): return jsonify({'message': 'Forbidden'}), 403
        keyword = request.args.get('keyword', '').strip()
        page = int(request.args.get('page', '1'))
        if len(keyword) > 200 or not 1 <= page <= 100000: raise ValueError('查询条件不正确')
        pattern = '%' + keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        with db._connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            where = "role IN ('admin','sales','warehouse','finance') AND (name ILIKE %s OR email ILIKE %s)"
            total = conn.execute('SELECT count(*) AS n FROM admin_users WHERE ' + where, (pattern, pattern)).fetchone()['n']
            users = conn.execute('SELECT id,name,email,role,status,permissions FROM admin_users WHERE ' + where + ' ORDER BY id LIMIT 20 OFFSET %s', (pattern, pattern, (page-1)*20)).fetchall()
            items = [dict(metadata(conn, u['id']), id=u['id'], name=u['name'], email=u['email'], role=u['role'], accountStatus=u['status'], moduleAllowed=eligible(u)) for u in users]
        return jsonify({'items': items, 'total': total, 'pageSize': 20, 'page': page})

    for action, method in [('authorization', 'PUT'), ('revoke', 'POST')]:
        app.add_url_rule(BASE + '/accounts/<int:user_id>/' + action, 'api_integration_admin_' + action,
                         guard(lambda user_id, action=action: mutate(action, user_id)), methods=[method])

    @app.get(BASE + '/logs')
    @guard
    def api_integration_logs():
        user_id = int(request.args.get('userId', g.current_user['id']))
        if user_id != g.current_user['id'] and not module_permissions.can_administer(g.current_user):
            return jsonify({'message': 'Forbidden'}), 403
        page = int(request.args.get('page', '1'))
        if not 1 <= page <= 100000: raise ValueError('页码不正确')
        with db._connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            total = conn.execute("SELECT count(*) AS n FROM api_call_logs WHERE admin_user_id=%s AND created_at>clock_timestamp()-interval '30 days'", (user_id,)).fetchone()['n']
            rows = conn.execute("""SELECT created_at,route,status,duration_ms FROM api_call_logs
                WHERE admin_user_id=%s AND created_at>clock_timestamp()-interval '30 days'
                ORDER BY id DESC LIMIT 20 OFFSET %s""", (user_id, (page-1)*20)).fetchall()
        return jsonify({'items': [{'time': iso(r['created_at']), 'route': r['route'], 'status': r['status'], 'durationMs': r['duration_ms']} for r in rows], 'total': total, 'pageSize': 20})
