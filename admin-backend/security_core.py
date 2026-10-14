"""Shared browser security boundary; mirrored byte-for-byte in the storefront.

Credentials are opaque cookies. The public session identifier is never a credential.
Counters use separate committed transactions, including failed business requests.
"""
from contextlib import contextmanager
from datetime import timedelta
from functools import wraps
import hashlib
import hmac
import math
import os
import re
import secrets
import time
import uuid

from flask import g, jsonify, request, has_request_context, current_app
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from security_settings import attachment_mode, login_protection_enabled

VERSION = 'browser-security-v1'
ROLES = {'admin', 'sales', 'warehouse', 'customer', 'finance'}
SAFE = {'GET', 'HEAD', 'OPTIONS'}


def token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def test_database():
    return os.environ.get('PGHOST') == '127.0.0.1' and os.environ.get('PGDATABASE', '').endswith('_test')


def migrate(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS security_schema_versions (
      version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS token_hash VARCHAR(64);
    ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS public_id UUID NOT NULL DEFAULT gen_random_uuid();
    ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
    ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
    CREATE UNIQUE INDEX IF NOT EXISTS admin_sessions_token_hash ON admin_sessions(token_hash);
    CREATE UNIQUE INDEX IF NOT EXISTS admin_sessions_public_id ON admin_sessions(public_id);
    CREATE TABLE IF NOT EXISTS store_sessions (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      store_user_id BIGINT NOT NULL REFERENCES store_users(id) ON DELETE CASCADE,
      token_hash VARCHAR(64) NOT NULL UNIQUE, public_id UUID NOT NULL UNIQUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ);
    CREATE INDEX IF NOT EXISTS store_sessions_user ON store_sessions(store_user_id);
    CREATE TABLE IF NOT EXISTS security_rate_buckets (
      bucket_key VARCHAR(64) PRIMARY KEY, ticks TIMESTAMPTZ[] NOT NULL DEFAULT '{}',
      blocked_until TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE TABLE IF NOT EXISTS security_audit_events (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), channel TEXT NOT NULL,
      event_code TEXT NOT NULL, actor_type TEXT, actor_id BIGINT, route TEXT NOT NULL,
      status INTEGER NOT NULL, ip_digest VARCHAR(64) NOT NULL);
    CREATE INDEX IF NOT EXISTS security_audit_created ON security_audit_events(created_at DESC);
    CREATE TABLE IF NOT EXISTS security_request_metrics (
      hour TIMESTAMPTZ NOT NULL, channel TEXT NOT NULL, route TEXT NOT NULL,
      status INTEGER NOT NULL, calls BIGINT NOT NULL DEFAULT 0,
      duration_ms NUMERIC NOT NULL DEFAULT 0, PRIMARY KEY(hour,channel,route,status));''')
    # Retire every legacy bearer once, preserving notification FK identities.
    prepared_only = os.environ.get('SECURITY_MIGRATION_PREPARE_ONLY') == '1'
    if not prepared_only:
        cur.execute('SELECT id,token FROM admin_sessions WHERE token_hash IS NULL FOR UPDATE')
        for row in cur.fetchall():
            cur.execute('''UPDATE admin_sessions SET token_hash=%s, token=%s,
              expires_at=clock_timestamp(),revoked_at=clock_timestamp() WHERE id=%s''',
              (token_hash(row['token']), 'retired:' + str(row['id']), row['id']))
    from private_media import migrate as migrate_media
    migrate_media(cur)
    cur.execute('INSERT INTO security_schema_versions(version) VALUES(%s) ON CONFLICT DO NOTHING', ('browser-security-structure-v1' if prepared_only else VERSION,))


def new_session(db, channel, user_id):
    table, column, days = ('admin_sessions', 'admin_user_id', 7) if channel == 'admin' else ('store_sessions', 'store_user_id', 30)
    token, public = secrets.token_urlsafe(32), uuid.uuid4()
    with db.get_connection() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'session:{channel}:{int(user_id)}',))
        conn.execute(f'UPDATE {table} SET revoked_at=clock_timestamp() WHERE {column}=%s AND revoked_at IS NULL', (user_id,))
        if channel == 'admin':
            conn.execute('''INSERT INTO admin_sessions(admin_user_id,token,token_hash,public_id,expires_at)
              VALUES(%s,%s,%s,%s,clock_timestamp()+%s)''', (user_id, 'cookie:' + str(public), token_hash(token), public, timedelta(days=days)))
        else:
            conn.execute('''INSERT INTO store_sessions(store_user_id,token_hash,public_id,expires_at)
              VALUES(%s,%s,%s,clock_timestamp()+%s)''', (user_id, token_hash(token), public, timedelta(days=days)))
    return token


def session(db, channel, token):
    if not isinstance(token, str) or not 20 <= len(token) <= 128:
        return None
    if channel == 'admin':
        query = '''SELECT s.id AS session_id,s.public_id,s.expires_at,u.id,u.name,u.email,
          u.role,u.permissions,u.status,u.created_at FROM admin_sessions s JOIN admin_users u ON u.id=s.admin_user_id'''
    else:
        query = '''SELECT s.id AS session_id,s.public_id,s.expires_at,u.id,u.name,u.email,
          u.company_name,u.status,u.created_at FROM store_sessions s JOIN store_users u ON u.id=s.store_user_id'''
    with db._connect() as conn:
        row = conn.execute(query + " WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp() AND u.status='active'", (token_hash(token),)).fetchone()
    if row and (channel != 'admin' or row['role'] in ROLES):
        return row
    return None


def revoke(db, channel, token=None, user_id=None):
    table, column = ('admin_sessions', 'admin_user_id') if channel == 'admin' else ('store_sessions', 'store_user_id')
    with db.get_connection() as conn:
        if user_id is not None:
            conn.execute(f'UPDATE {table} SET revoked_at=clock_timestamp() WHERE {column}=%s AND revoked_at IS NULL', (user_id,))
        elif token:
            conn.execute(f'UPDATE {table} SET revoked_at=clock_timestamp() WHERE token_hash=%s AND revoked_at IS NULL', (token_hash(token),))
    if has_request_context() and current_app.extensions['security'].channel == channel:
        current = getattr(g, '_security_session', None)
        if current and ((user_id is not None and current['id'] == user_id) or token == request.cookies.get(('__Host-' if os.environ.get('APP_ENV','production') == 'production' else '') + 'gingtto-' + channel + '-session')):
            g.security_session_revoked = True


def validate_password(value):
    # The password/login-protection cutover is explicitly deferred. Existing
    # accounts and the previous create/change-password rules remain unchanged.
    if not login_protection_enabled():
        return
    weak = {'123456789012', '1234567890123', '1234567890123456', 'qwertyuiop12', 'abc123abc123'}
    normalized = re.sub(r'[^a-z0-9]', '', value.casefold()) if isinstance(value, str) else ''
    common = re.fullmatch(r'(password|passw0rd|qwerty|administrator|admin|letmein|welcome|gingtto|smawell)[0-9]*', normalized)
    if not isinstance(value, str) or len(value) < 12 or len(value) > 256 or len(set(value.casefold())) < 4 or normalized in weak or common:
        raise ValueError('Use at least 12 characters and avoid common passwords.')


class TrustedProxy:
    def __init__(self, app, peers):
        self.app, self.proxy, self.peers = app, ProxyFix(app, x_for=1, x_proto=1), set(peers)

    def __call__(self, environ, start_response):
        if environ.get('REMOTE_ADDR') in self.peers:
            return self.proxy(environ, start_response)
        for name in ('HTTP_X_FORWARDED_FOR', 'HTTP_X_FORWARDED_PROTO', 'HTTP_X_FORWARDED_HOST', 'HTTP_X_FORWARDED_PORT', 'HTTP_X_FORWARDED_PREFIX'):
            environ.pop(name, None)
        return self.app(environ, start_response)


class Security:
    def __init__(self, app, db, channel):
        self.app, self.db, self.channel = app, db, channel
        self.mode = os.environ.get('APP_ENV', 'production')
        if self.mode == 'test' and not test_database():
            raise RuntimeError('Test mode requires an isolated local *_test database')
        key = os.environ.get('SECURITY_SECRET', '')
        if not key and self.mode == 'test':
            key = 'fixture-only-security-key-not-for-production-2026'
        if len(key.encode()) < 32 or key.startswith(('REPLACE_', 'CHANGE_')) or len(set(key)) < 16:
            raise RuntimeError('SECURITY_SECRET must be configured with at least 32 random bytes')
        self.key = key.encode()
        if self.mode not in {'production','local','test'}: raise RuntimeError('Invalid APP_ENV')
        self.secure = self.mode == 'production'
        self.attachment_mode = attachment_mode()
        self.login_protection = login_protection_enabled()
        if self.secure and self.attachment_mode == 'private':
            if os.environ.get('SECURITY_LEGACY_SOURCES_CLOSED') != '1': raise RuntimeError('Legacy private object and CDN closure must be confirmed before cutover')
            with db._connect() as conn:
                if not conn.execute("SELECT 1 FROM security_media_migrations WHERE name='legacy-private-v1'").fetchone(): raise RuntimeError('Legacy attachment migration is incomplete')
        prefix = '__Host-' if self.secure else ''
        self.cookie = prefix + 'gingtto-' + channel + '-session'
        self.pre_cookie = prefix + 'gingtto-' + channel + '-preauth'
        origins = os.environ.get('SECURITY_ALLOWED_ORIGINS', '').split(',')
        self.origins = {s.strip().rstrip('/') for s in origins if s.strip()}
        hosts = [s.strip() for s in os.environ.get('SECURITY_ALLOWED_HOSTS', '').split(',') if s.strip()]
        if self.mode in {'local', 'test'}:
            hosts += ['localhost', '127.0.0.1']
        if not hosts:
            raise RuntimeError('SECURITY_ALLOWED_HOSTS must be configured')
        app.config.update(TRUSTED_HOSTS=list(set(hosts)), MAX_CONTENT_LENGTH=40 * 1024 * 1024,
                          MAX_FORM_MEMORY_SIZE=1024 * 1024, MAX_FORM_PARTS=40)
        app.wsgi_app = TrustedProxy(app.wsgi_app, os.environ.get('SECURITY_PROXY_PEERS', '127.0.0.1,::1').split(','))
        app.extensions['security'] = self
        app.before_request(self.before)
        app.after_request(self.after)
        app.teardown_request(self.teardown)
        app.add_url_rule('/api/auth/csrf', 'security_csrf', self.csrf_response, methods=['GET'])
        app.add_url_rule('/api/security/csp-report', 'security_csp_report', self.csp_report, methods=['POST'])
        app.register_error_handler(HTTPException, self.http_error)
        app.register_error_handler(Exception, self.server_error)

    def digest(self, text):
        return hmac.new(self.key, text.encode(), hashlib.sha256).hexdigest()

    def raw_token(self):
        return request.cookies.get(self.cookie, '')

    def current(self):
        identity = request._get_current_object()
        if getattr(g, '_security_request_identity', None) is not identity:
            g._security_request_identity = identity
            g._security_session = session(self.db, self.channel, self.raw_token())
        return g._security_session

    def csrf(self, row):
        return self.digest('csrf:' + self.channel + ':' + str(row['public_id']))

    def user(self, row):
        user = {'id': row['id'], 'name': row['name'], 'email': row['email'], 'status': row['status'], 'createdAt': row['created_at'].isoformat()}
        if self.channel == 'admin':
            user.update(role=row['role'], permissions=row['permissions'])
        else:
            user['companyName'] = row['company_name'] or ''
        return user

    def authenticated(self, func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            row = self.current()
            if not row:
                return self.error(401, 'session_invalid', 'Please sign in again.')
            g.current_user = self.user(row)
            g.current_token = self.raw_token()
            g.current_session = row
            return func(*args, **kwargs)
        return wrapped

    def metadata(self, row):
        return {'sessionId': str(row['public_id']), 'expiresAt': row['expires_at'].isoformat(), 'csrfToken': self.csrf(row)}

    def login_response(self, token, user):
        row = session(self.db, self.channel, token)
        g._security_session = row
        g.security_session_revoked = False
        g.security_event = 'login_success'
        response = jsonify({'user': user, **self.metadata(row)})
        response.set_cookie(self.cookie, token, max_age=7 * 86400 if self.channel == 'admin' else 30 * 86400,
                            httponly=True, secure=self.secure, samesite='Lax', path='/')
        response.delete_cookie(self.pre_cookie, secure=self.secure, httponly=True, samesite='Lax', path='/')
        return response

    def sign_in(self, email, password, sanitize):
        from werkzeug.security import check_password_hash, generate_password_hash
        retry = self.login_cooldown(email)
        if retry:
            return self.error(429, 'login_rate_limited', 'Too many sign-in attempts. Try again later.', retry)
        table = 'admin_users' if self.channel == 'admin' else 'store_users'
        context = self.db.REQUEST_CONNECTION if self.channel == 'admin' else self.db.CATALOG_CONNECTION
        with self.db._connect() as conn:
            marker = context.set(conn)
            try:
                candidate = conn.execute(f'SELECT id FROM {table} WHERE LOWER(email)=LOWER(%s)',(email,)).fetchone()
                prior = self.current()
                ids = sorted({r['id'] for r in (candidate,prior) if r})
                if ids: conn.execute(f'SELECT id FROM {table} WHERE id=ANY(%s) ORDER BY id FOR UPDATE',(ids,)).fetchall()
                user = conn.execute(f'SELECT * FROM {table} WHERE LOWER(email)=LOWER(%s)',(email,)).fetchone()
                if user and (not candidate or user['id'] != candidate['id']): user = None
                matched = False
                if user:
                    matched = check_password_hash(user['password_hash'], password)
                elif self.login_protection:
                    if not hasattr(self, '_dummy_password'):
                        self._dummy_password = generate_password_hash('not-a-user-password-' + secrets.token_urlsafe(24), method='pbkdf2:sha256:600000')
                    check_password_hash(self._dummy_password, password)
                if not user or user['status'] != 'active' or not matched or (self.channel == 'admin' and user['role'] not in ROLES):
                    retry = self.login_cooldown(email, failed=True)
                    message = 'Invalid email or password' if self.channel == 'admin' and not self.login_protection else 'Invalid account or password.'
                    return self.error(429 if retry else 401, 'login_rate_limited' if retry else 'login_failed',
                                      'Too many sign-in attempts. Try again later.' if retry else message, retry)
                retry = self.login_cooldown(email, success=True)
                if retry:
                    return self.error(429, 'login_rate_limited', 'Too many sign-in attempts. Try again later.', retry)
                if self.current():
                    revoke(self.db, self.channel, token=self.raw_token())
                token = new_session(self.db, self.channel, user['id'])
                profile = sanitize(self.user(user))
            finally:
                context.reset(marker)
        return self.login_response(token, profile)

    def logout_response(self):
        revoke(self.db, self.channel, token=self.raw_token())
        g.security_event = 'logout'
        response = jsonify({'message': 'ok'})
        response.delete_cookie(self.cookie, secure=self.secure, httponly=True, samesite='Lax', path='/')
        return response

    def csrf_response(self):
        row = self.current()
        if row:
            return jsonify({'csrfToken': self.csrf(row), 'sessionId': str(row['public_id'])})
        seed = f'{int(time.time())}.{secrets.token_urlsafe(24)}'
        signed = seed + '.' + self.digest('preauth:' + self.channel + ':' + seed)
        response = jsonify({'csrfToken': signed})
        response.set_cookie(self.pre_cookie, signed, max_age=900, httponly=True, secure=self.secure, samesite='Lax', path='/')
        return response

    def valid_csrf(self):
        value = request.headers.get('X-CSRF-Token', '')
        if len(value) > 256:
            return False
        row = self.current()
        if row:
            return bool(value) and hmac.compare_digest(value, self.csrf(row))
        cookie = request.cookies.get(self.pre_cookie, '')
        try:
            stamp, nonce, signature = value.split('.')
            seed = stamp + '.' + nonce
            return bool(cookie) and hmac.compare_digest(cookie, value) and 0 <= time.time() - int(stamp) <= 900 and hmac.compare_digest(signature, self.digest('preauth:' + self.channel + ':' + seed))
        except (ValueError, TypeError):
            return False

    def origin_valid(self):
        from urllib.parse import urlsplit
        origin = request.headers.get('Origin')
        if not origin:
            referer = request.headers.get('Referer', '')
            parts = urlsplit(referer)
            origin = f'{parts.scheme}://{parts.netloc}' if parts.scheme and parts.netloc else ''
        return origin in ({request.host_url.rstrip('/')} | self.origins)

    def reserve(self, label, subject, limit, seconds):
        key = self.digest('quota:' + self.channel + ':' + label + ':' + subject)
        with self.db._connect() as conn:
            conn.execute('INSERT INTO security_rate_buckets(bucket_key) VALUES(%s) ON CONFLICT DO NOTHING', (key,))
            row = conn.execute('SELECT ticks,clock_timestamp() AS now FROM security_rate_buckets WHERE bucket_key=%s FOR UPDATE', (key,)).fetchone()
            now = row['now']; ticks = [t for t in row['ticks'] if t > now - timedelta(seconds=seconds)]
            retry = max(1, math.ceil((ticks[0] + timedelta(seconds=seconds) - now).total_seconds())) if len(ticks) >= limit else 0
            if not retry:
                ticks.append(now)
            conn.execute('UPDATE security_rate_buckets SET ticks=%s,updated_at=clock_timestamp() WHERE bucket_key=%s', (ticks, key))
        return retry

    def login_cooldown(self, email, failed=False, success=False):
        if not self.login_protection:
            return 0
        key = self.digest('login-account:' + self.channel + ':' + email)
        with self.db._connect() as conn:
            conn.execute('INSERT INTO security_rate_buckets(bucket_key) VALUES(%s) ON CONFLICT DO NOTHING', (key,))
            row = conn.execute('SELECT *,clock_timestamp() AS now FROM security_rate_buckets WHERE bucket_key=%s FOR UPDATE', (key,)).fetchone()
            now = row['now']
            if row['blocked_until'] and row['blocked_until'] > now:
                return math.ceil((row['blocked_until'] - now).total_seconds())
            ticks = [t for t in row['ticks'] if t > now - timedelta(minutes=15)]
            if failed:
                ticks.append(now)
            blocked = now + timedelta(minutes=15) if len(ticks) >= 10 else None
            if success:
                ticks, blocked = [], None
            conn.execute('UPDATE security_rate_buckets SET ticks=%s,blocked_until=%s,updated_at=clock_timestamp() WHERE bucket_key=%s', (ticks, blocked, key))
            return 900 if blocked else 0

    def error(self, status, code, message, retry=None):
        g.security_event = code
        response = jsonify({'code': code, 'message': message})
        response.status_code = status
        if retry:
            response.headers['Retry-After'] = str(retry)
        return response

    def before(self):
        # g belongs to an application context, not necessarily one HTTP request
        # (nested clients and long-lived app contexts can reuse it). Never carry
        # a previous identity, export cache or audit actor into another request.
        for key in ('_security_request_identity', '_security_session', 'current_user',
                    'current_token', 'current_session', 'security_session_revoked',
                    'security_event', 'security_exporting', 'export_image_cache'):
            g.pop(key, None)
        g.security_started = time.perf_counter()
        path = request.path
        if self.channel == 'admin' and path.startswith('/api/public/'):
            return self.error(410, 'endpoint_retired', 'This endpoint has been retired.')
        if path.startswith('/api/internal/') and os.environ.get('INTERNAL_COMPAT_ENABLED') != '1':
            return self.error(404, 'not_found', 'Not found.')
        if not path.startswith('/api/'):
            return None
        if self.secure and not request.is_secure and not (path == '/api/health' and request.remote_addr in {'127.0.0.1', '::1'}):
            return self.error(426, 'https_required', 'Use HTTPS.')
        if path == '/api/health':
            return None
        if path == '/api/security/csp-report':
            retry = self.reserve('csp-report', request.remote_addr or '', 20, 60)
            if retry: return self.error(429, 'rate_limited', 'Too many reports.', retry)
            if (request.content_length or 0) > 8192: return self.error(413, 'body_too_large', 'Report is too large.')
            return None
        if any(len(value) > 200 for key, value in request.args.items() if key in {'keyword', 'q', 'customerName'}):
            return self.error(400, 'query_too_long', 'Search text must be 200 characters or fewer.')
        if request.content_length and request.is_json and request.content_length > 1024 * 1024:
            return self.error(413, 'body_too_large', 'Request is too large.')
        if request.is_json and request.method not in SAFE and not isinstance(request.get_json(silent=True), dict):
            return self.error(400, 'invalid_body', 'A JSON object is required.')
        row = self.current()
        expected = request.headers.get('X-Auth-Session')
        if row and expected and expected != str(row['public_id']):
            return self.error(409, 'session_changed', 'The signed-in account changed. Reload this page.')
        login = path in {'/api/auth/admin/login', '/api/auth/store/login'}
        if login and self.login_protection:
            retry = self.reserve('login-ip', request.remote_addr or '', 100, 600)
            if retry:
                return self.error(429, 'login_rate_limited', 'Too many sign-in attempts. Try again later.', retry)
        elif not login and path != '/api/auth/csrf' and not path.startswith('/api/attachments/') and request.url_rule and not row and not path.startswith('/api/internal/'):
            return self.error(401, 'session_invalid', 'Please sign in again.')
        if request.method not in SAFE and not path.startswith('/api/internal/'):
            if not self.origin_valid() or not self.valid_csrf():
                return self.error(403, 'csrf_invalid', 'Reload this page before trying again.')
        if not login:
            category = 'read'
            if '/order-notifications/' in path:
                category = 'voice'
            elif 'export' in path or path.endswith('/invoice'):
                category = 'export'
            elif path.endswith(('/uploads', '/order-attachments', '/attachments')) or '/inventory/import/' in path:
                category = 'upload'
            elif request.method not in SAFE and not path.endswith(('/preview', '/query', '/validate')):
                category = 'write'
            if self.channel == 'store' and path == '/api/products': category = 'inventory'
            limit = {'read': 180, 'voice': 120, 'export': 5, 'upload': 20, 'write': 60, 'inventory': 6}[category]
            limit = int(os.environ.get('SECURITY_LIMIT_' + category.upper(), limit))
            if not 1 <= limit <= 10000: raise RuntimeError('Invalid security quota configuration')
            subject = str(row['id']) if category == 'export' and row else str(row['public_id']) if row else 'ip:' + (request.remote_addr or '')
            retry = self.reserve(category, subject, limit, 60)
            if retry:
                return self.error(429, 'rate_limited', 'Too many requests. Try again later.', retry)
            if category == 'export' and row:
                conn = self.db._connect(autocommit=True)
                key = f'export:{self.channel}:{row["id"]}'
                if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked', (key,)).fetchone()['locked']:
                    conn.close()
                    return self.error(429, 'export_in_progress', 'Another export is in progress. Try again later.', 5)
                g.security_export_connection, g.security_export_key = conn, key
                g.security_exporting = True
        return None

    def after(self, response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if self.secure:
            response.headers['Strict-Transport-Security'] = 'max-age=' + os.environ.get('SECURITY_HSTS_MAX_AGE', '300')
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            if response.status_code >= 500:
                response.set_data(self.app.json.dumps({'code':'service_error','message':'The service is temporarily unavailable. Try again later.'}))
                response.content_type = 'application/json'
            if getattr(g, 'security_session_revoked', False):
                response.headers['X-Session-Revoked'] = '1'
                response.delete_cookie(self.cookie, secure=self.secure, httponly=True, samesite='Lax', path='/')
            row = getattr(g, '_security_session', None)
            if row:
                response.headers['X-Auth-Session'] = str(row['public_id'])
        if response.mimetype == 'text/html':
            response.headers['Cache-Control'] = 'no-store'
            images = os.environ.get('PUBLIC_IMAGE_ORIGINS', '').split(',')
            sources = ' '.join(s.strip() for s in images if s.strip().startswith('https://'))
            policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: " + sources + "; font-src 'self' data:; connect-src 'self' " + sources + "; media-src 'self' blob:; worker-src 'self' blob:; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'; report-uri /api/security/csp-report"
            response.headers['Content-Security-Policy' if os.environ.get('SECURITY_CSP_ENFORCE') == '1' else 'Content-Security-Policy-Report-Only'] = policy
        if response.is_json and (request.path.startswith(('/api/admin/orders', '/api/admin/order-drafts', '/api/admin/contracts', '/api/admin/purchase-contracts', '/api/store/orders')) or request.path == '/api/orders'):
            media = self.app.extensions.get('media')
            if media and response.status_code < 400:
                response.set_data(self.app.json.dumps(media.rewrite(response.get_json())))
        if request.path.startswith('/api/') and request.path != '/api/health':
            self.record(response)
        return response

    def teardown(self, error=None):
        conn = getattr(g, 'security_export_connection', None)
        if conn:
            g.security_export_connection = None
            try:
                conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (g.security_export_key,))
            finally:
                conn.close()

    def record(self, response):
        route = request.url_rule.rule if request.url_rule else '/api/<unknown>'
        duration = max(0, (time.perf_counter() - getattr(g, 'security_started', time.perf_counter())) * 1000)
        event = getattr(g, 'security_event', None)
        if not event and response.status_code in {401, 403, 429}:
            event = {401: 'session_invalid', 403: 'permission_denied', 429: 'rate_limited'}[response.status_code]
        try:
            with self.db._connect() as conn:
                conn.execute('''INSERT INTO security_request_metrics(hour,channel,route,status,calls,duration_ms)
                  VALUES(date_trunc('hour',clock_timestamp()),%s,%s,%s,1,%s)
                  ON CONFLICT(hour,channel,route,status) DO UPDATE SET calls=security_request_metrics.calls+1,
                    duration_ms=security_request_metrics.duration_ms+EXCLUDED.duration_ms''', (self.channel, route, response.status_code, duration))
                if event:
                    row = getattr(g, '_security_session', None)
                    conn.execute('''INSERT INTO security_audit_events(channel,event_code,actor_type,actor_id,route,status,ip_digest)
                      VALUES(%s,%s,%s,%s,%s,%s,%s)''', (self.channel, event, self.channel if row else None, row['id'] if row else None, route, response.status_code, self.digest('ip:' + (request.remote_addr or ''))))
        except Exception:
            self.app.logger.warning('security_metrics_write_failed')

    def csp_report(self):
        # Do not persist document URLs, referrers, blocked URLs or script samples.
        g.security_event = 'csp_violation'
        return '', 204

    def http_error(self, exc):
        return self.error(exc.code or 500, 'http_error', {400: 'Invalid request.', 403: 'Forbidden.', 404: 'Not found.', 413: 'Request is too large.'}.get(exc.code, 'Request failed.'))

    def server_error(self, exc):
        self.app.logger.error('request_failed exception_type=%s route=%s', type(exc).__name__, request.url_rule.rule if request.url_rule else '<unknown>')
        return self.error(500, 'service_error', 'The service is temporarily unavailable. Try again later.')

    @contextmanager
    def export_slot(self):
        row = self.current()
        with self.db._connect() as conn:
            key = f'export:{self.channel}:{row["id"]}'
            locked = conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked', (key,)).fetchone()['locked']
            if not locked:
                from werkzeug.exceptions import TooManyRequests
                raise TooManyRequests('Another export is in progress.')
            try:
                yield
            finally:
                conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))
