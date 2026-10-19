"""Narrow machine-only read API. Never connects using a browser/business role."""
import hashlib
import math
import os
import re
import time
import uuid
from datetime import UTC, timedelta
from urllib.parse import urljoin, urlsplit

import psycopg
from psycopg.rows import dict_row
from flask import g, jsonify, request

PREFIX = '/api/external/'
BASE = PREFIX + 'v1'
ENDPOINTS = {'external_products', 'external_product', 'external_inventory'}


class APIError(Exception):
    def __init__(self, status, code, message, retry=None):
        self.status, self.code, self.message, self.retry = status, code, message, retry


def positive(value, maximum=9223372036854775807):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value) or int(value) > maximum:
        raise APIError(400, 'invalid_query', 'A positive integer within the documented limit is required.')
    return int(value)


def values(name, required=False, ids=False):
    raw = request.args.getlist(name)
    parts = [v.strip() for item in raw for v in item.split(',') if v.strip()]
    if required and not parts or len(parts) > 100 or any(len(p) > 200 for p in parts):
        raise APIError(400, 'invalid_query', 'Provide between 1 and 100 values, each at most 200 characters.')
    return list(dict.fromkeys(positive(p) if ids else p for p in parts))


class ExternalAPI:
    def __init__(self, app, db, security):
        self.app, self.db, self.security = app, db, security
        self.enabled = os.environ.get('EXTERNAL_API_ENABLED') == '1'
        self.limit = int(os.environ.get('EXTERNAL_API_LIMIT', '60'))
        self.ip_limit = int(os.environ.get('EXTERNAL_API_IP_LIMIT', '300'))
        self.global_limit = int(os.environ.get('EXTERNAL_API_GLOBAL_RPS', '10'))
        self.global_concurrency = int(os.environ.get('EXTERNAL_API_GLOBAL_CONCURRENCY', '4'))
        self.key_concurrency = int(os.environ.get('EXTERNAL_API_KEY_CONCURRENCY', '2'))
        if (not all(1 <= n <= 10000 for n in (self.limit,self.ip_limit,self.global_limit))
                or not 1 <= self.key_concurrency <= self.global_concurrency <= 64):
            raise RuntimeError('Invalid external API quota configuration')
        self.origin = os.environ.get('EXTERNAL_API_PUBLIC_ORIGIN', 'https://gingtto.store').rstrip('/')
        parsed = urlsplit(self.origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise RuntimeError('External API image origin must be an absolute HTTPS origin')
        self.origins = {self.origin}
        for value in os.environ.get('PUBLIC_IMAGE_ORIGINS', '').split(','):
            part = urlsplit(value.strip())
            if part.scheme == 'https' and part.hostname and not part.username and not part.password:
                self.origins.add(f'{part.scheme}://{part.netloc}')
        if self.enabled:
            if not os.environ.get('EXTERNAL_API_DB_USER') or len(os.environ.get('EXTERNAL_API_DB_PASSWORD', '')) < 32:
                raise RuntimeError('Dedicated external API database credentials required')
            self.validate_role()

    def connect(self):
        # Deliberately no fallback to DB_USER/DB_PASSWORD. The dedicated role has
        # only safe views and counters, even if a handler later regresses.
        kwargs=dict(host=os.environ.get('EXTERNAL_API_DB_HOST', self.db.DB_HOST),
            port=int(os.environ.get('EXTERNAL_API_DB_PORT', str(self.db.DB_PORT))),
            dbname=os.environ.get('EXTERNAL_API_DB_NAME', self.db.DB_NAME),
            user=os.environ['EXTERNAL_API_DB_USER'], password=os.environ['EXTERNAL_API_DB_PASSWORD'],
            connect_timeout=5, row_factory=dict_row,
            options='-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=10000')
        import database_pool
        if database_pool.enabled('EXTERNAL_API'):
            return database_pool.borrow(kwargs,namespace='external-api',prefix='EXTERNAL_API',default_size=2,
                settings={'statement_timeout':5000,'lock_timeout':2000,'idle_in_transaction_session_timeout':10000})
        return psycopg.connect(**kwargs)

    def validate_role(self):
        with self.connect() as conn:
            row = conn.execute("""SELECT current_user AS name,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,
              has_schema_privilege(current_user,'public','CREATE') AS ddl,
              has_database_privilege(current_user,current_database(),'CREATE') AS db_ddl,
              has_database_privilege(current_user,current_database(),'TEMP') AS temp
              FROM pg_roles WHERE rolname=current_user""").fetchone()
            if any(row[k] for k in ('rolsuper','rolcreatedb','rolcreaterole','rolbypassrls','ddl','db_ddl','temp')):
                raise RuntimeError('External API role has excessive privileges')
            if row['name'] == self.db.DB_USER: raise RuntimeError('External API and storefront database roles must differ')
            if conn.execute('''SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=current_user
                UNION ALL SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE r.rolname=current_user
                UNION ALL SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner WHERE r.rolname=current_user
                UNION ALL SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba WHERE r.rolname=current_user LIMIT 1''').fetchone():
                raise RuntimeError('External API role must have no memberships or object ownership')
            # Check effective column privileges too: table-wide checks miss
            # grants such as UPDATE(stock) or SELECT(password_hash).
            allowed = {'api_integrations', 'api_call_logs', 'api_rate_buckets', 'api_request_leases',
                       'external_api_credentials_v','external_api_products_v','external_api_sizes_v','external_api_images_v'}
            tables = conn.execute("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')""").fetchall()
            for table in tables:
                name = table['relname']
                if name in allowed: continue
                if conn.execute("""SELECT has_any_column_privilege(current_user,%s,'SELECT,INSERT,UPDATE,REFERENCES')
                    OR has_table_privilege(current_user,%s,'DELETE,TRUNCATE,TRIGGER') AS excessive""", (name, name)).fetchone()['excessive']:
                    raise RuntimeError('External API role can access a business table')
            for sequence in conn.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='S' AND c.relname<>'api_call_logs_id_seq'").fetchall():
                if conn.execute("SELECT has_sequence_privilege(current_user,%s,'SELECT,USAGE,UPDATE') AS excessive",(sequence['relname'],)).fetchone()['excessive']:
                    raise RuntimeError('External API role can access a business sequence')
            for view in ('external_api_credentials_v','external_api_products_v','external_api_sizes_v','external_api_images_v'):
                conn.execute('SELECT * FROM ' + view + ' LIMIT 0')
            for column in ('token_hash','enabled','admin_blocked','expires_at','version'):
                if conn.execute("SELECT has_column_privilege(current_user,'api_integrations',%s,'SELECT,INSERT,UPDATE') AS excessive", (column,)).fetchone()['excessive']:
                    raise RuntimeError('External API role can read or change credential storage')
            if conn.execute("SELECT has_table_privilege(current_user,'api_integrations','DELETE,TRUNCATE,TRIGGER') OR has_any_column_privilege(current_user,'api_call_logs','SELECT,UPDATE,REFERENCES') OR has_table_privilege(current_user,'api_call_logs','DELETE,TRUNCATE,TRIGGER') AS excessive").fetchone()['excessive']:
                raise RuntimeError('External API role has excessive metadata privileges')

    def error(self, error):
        response = jsonify({'code': error.code, 'message': error.message, 'requestId': g.external_request_id})
        response.status_code = error.status
        response.headers['Cache-Control'] = 'no-store'
        if error.retry: response.headers['Retry-After'] = str(error.retry)
        return response

    def reserve(self, label, subject, limit, seconds=60):
        key = hashlib.sha256((label + ':' + str(subject)).encode()).hexdigest()
        with self.connect() as conn:
            conn.execute('INSERT INTO api_rate_buckets(bucket_key) VALUES(%s) ON CONFLICT DO NOTHING', (key,))
            row = conn.execute('SELECT ticks,clock_timestamp() AS now FROM api_rate_buckets WHERE bucket_key=%s FOR UPDATE', (key,)).fetchone()
            now = row['now']; ticks = [t for t in row['ticks'] if t > now-timedelta(seconds=seconds)]
            retry = max(1, math.ceil((ticks[0]+timedelta(seconds=seconds)-now).total_seconds())) if len(ticks) >= limit else 0
            if not retry: ticks.append(now)
            conn.execute('UPDATE api_rate_buckets SET ticks=%s,updated_at=clock_timestamp() WHERE bucket_key=%s', (ticks, key))
        return retry

    def acquire_request(self, key_id):
        # A short metadata transaction, not a held connection/advisory lock.
        # All workers and aliases serialize admission on the same sentinel row.
        gate = hashlib.sha256(b'external-api-active-admission-v1').hexdigest()
        with self.connect() as conn:
            conn.execute('INSERT INTO api_rate_buckets(bucket_key) VALUES(%s) ON CONFLICT DO NOTHING',(gate,))
            now=conn.execute('SELECT clock_timestamp() AS now FROM api_rate_buckets WHERE bucket_key=%s FOR UPDATE',(gate,)).fetchone()['now']
            conn.execute('DELETE FROM api_request_leases WHERE expires_at<=%s',(now,))
            counts=conn.execute('SELECT count(*) AS total,count(*) FILTER(WHERE key_id=%s) AS own FROM api_request_leases',(key_id,)).fetchone()
            if counts['total']>=self.global_concurrency or counts['own']>=self.key_concurrency:
                raise APIError(429,'concurrency_limited','Too many concurrent requests. Try again shortly.',1)
            conn.execute('INSERT INTO api_request_leases(request_id,key_id,expires_at) VALUES(%s,%s,%s)',
                (g.external_request_id,key_id,now+timedelta(seconds=180)))
        g.external_lease_id=g.external_request_id

    def release_request(self):
        lease=getattr(g,'external_lease_id',None)
        if not lease:return
        try:
            with self.connect() as conn:
                conn.execute('DELETE FROM api_request_leases WHERE request_id=%s',(lease,))
            g.external_lease_id=None
        except psycopg.Error:
            # Teardown makes one further attempt; a crashed worker's lease has
            # a bounded expiry, so its capacity is never reserved permanently.
            self.app.logger.warning('external_api_lease_release_failed')

    def teardown(self, exception=None):
        self.release_request()

    def before(self):
        g.external_request_id = str(uuid.uuid4())
        g.external_identity = None
        g.external_lease_id = None
        try:
            if getattr(request.routing_exception, 'code', None) == 400:
                raise APIError(400, 'invalid_request', 'Invalid request.')
            if request.endpoint not in ENDPOINTS:
                known = bool(re.fullmatch(r'/api/external/v1/(?:products(?:/[0-9]+)?|inventory)', request.path))
                raise APIError(405 if known and request.method not in {'GET','HEAD'} else 404, 'not_found', 'Not found.')
            if request.method not in {'GET', 'HEAD'}: raise APIError(405, 'read_only', 'Only GET is supported.')
            if not self.enabled: raise APIError(503, 'api_not_enabled', 'The external API is not enabled.')
            if request.content_length or request.headers.get('Transfer-Encoding'):
                raise APIError(400, 'unexpected_body', 'Read requests must not include a body.')
            if request.query_string and any(k.lower() in {'key','token','api_key','access_token','authorization'} for k in request.args):
                raise APIError(400, 'credential_in_url', 'Send credentials only in the Authorization header.')
            retry = self.reserve('global-second','all-keys-and-aliases',self.global_limit,seconds=1)
            if retry:raise APIError(429,'rate_limited','Too many requests.',retry)
            retry = self.reserve('ip', self.security.digest('external-ip:'+(request.remote_addr or '')), self.ip_limit)
            if retry: raise APIError(429, 'rate_limited', 'Too many requests.', retry)
            header = request.headers.get('Authorization', '')
            if not re.fullmatch(r'Bearer gapi_[A-Za-z0-9_-]{43}', header):
                raise APIError(401, 'invalid_api_key', 'A valid API key is required.')
            digest = hashlib.sha256(header[7:].encode()).hexdigest()
            with self.connect() as conn:
                row = conn.execute('''SELECT admin_user_id,key_id,version FROM external_api_credentials_v
                    WHERE token_hash=%s AND allowed AND enabled AND NOT admin_blocked
                      AND (expires_at IS NULL OR expires_at>clock_timestamp())''', (digest,)).fetchone()
            if not row: raise APIError(401, 'invalid_api_key', 'A valid API key is required.')
            g.external_identity = row
            retry = self.reserve('key', row['key_id'], self.limit)
            if retry: raise APIError(429, 'rate_limited', 'Too many requests.', retry)
            self.acquire_request(row['key_id'])
            return None
        except APIError as error: return self.error(error)

    def record(self, response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Authorization'
        request_id = getattr(g, 'external_request_id', None) or str(uuid.uuid4())
        response.headers['X-Request-Id'] = request_id
        if response.is_json and response.status_code >= 400:
            data = response.get_json()
            if isinstance(data, dict) and 'requestId' not in data:
                response.set_data(self.app.json.dumps(dict(data, requestId=request_id)))
        identity = getattr(g, 'external_identity', None)
        try:
            if identity and not getattr(g,'security_database_busy',False):
                with self.connect() as conn:
                    conn.execute('UPDATE api_integrations SET last_used_at=clock_timestamp() WHERE admin_user_id=%s AND key_id=%s', (identity['admin_user_id'], identity['key_id']))
                    conn.execute('''INSERT INTO api_call_logs(admin_user_id,key_id,route,status,duration_ms,request_id)
                      VALUES(%s,%s,%s,%s,%s,%s)''', (identity['admin_user_id'],identity['key_id'],
                      request.url_rule.rule, response.status_code,
                      max(0, round((time.perf_counter()-g.security_started)*1000)), g.external_request_id))
        except psycopg.Error:
            self.app.logger.warning('external_api_metadata_write_failed')
        finally:self.release_request()

    def image(self, value):
        if not value or not isinstance(value, str) or re.search(r'[\x00-\x20\\]', value): return None
        url = urljoin(self.origin+'/', value)
        part = urlsplit(url)
        if part.username or part.password or part.fragment or part.scheme != 'https' or f'{part.scheme}://{part.netloc}' not in self.origins:
            return None
        return url

    def bundles(self, conn, rows, inventory=False):
        ids = [r['id'] for r in rows]
        if not ids: return []
        sizes = conn.execute('SELECT product_id,size_code,stock FROM external_api_sizes_v WHERE product_id=ANY(%s) ORDER BY product_id,sort_order,id', (ids,)).fetchall()
        size_map = {pid: [] for pid in ids}
        for row in sizes: size_map[row['product_id']].append({'size': row['size_code'], 'stock': row['stock']})
        galleries = {pid: [] for pid in ids}
        if not inventory:
            images = conn.execute('SELECT product_id,image_url FROM external_api_images_v WHERE product_id=ANY(%s) ORDER BY product_id,sort_order,id', (ids,)).fetchall()
            for image in images: galleries[image['product_id']].append(self.image(image['image_url']))
        items = []
        for row in rows:
            item = {'productId': row['id'], 'styleCode': row['style_code'], 'sku': row['sku'], 'sizes': size_map[row['id']]}
            if not inventory:
                item.update(color=row['color_name'], category={'id': row['category_id'], 'key': row['category_key'], 'name': row['category_name']},
                    title=row['title'], summary=row['summary'], description=row['description'], images={
                    'main': self.image(row['main_image_url']), 'gallery': galleries[row['id']],
                    'sizeChart': self.image(row['size_chart_image_url']), 'detail': self.image(row['description_image_url'])})
            items.append(item)
        return items

    def read(self, product_id=None, inventory=False):
        try:
            params = []; conditions = []; limit = None
            if inventory:
                ids = values('productIds', required=True, ids=True)
                conditions.append('id=ANY(%s)'); params.append(ids)
            elif product_id is not None:
                product_id = positive(str(product_id)); conditions.append('id=%s'); params.append(product_id)
            else:
                limit = positive(request.args.get('limit', '50'), 100)
                cursor = request.args.get('cursor')
                if cursor: conditions.append('id>%s'); params.append(positive(cursor))
                keyword = request.args.get('keyword', '').strip()
                if len(keyword) > 200: raise APIError(400, 'invalid_query', 'Keyword must not exceed 200 characters.')
                if keyword:
                    term = '%'+keyword.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
                    conditions.append('(style_code ILIKE %s OR sku ILIKE %s OR title ILIKE %s)'); params.extend([term]*3)
                for arg, column in [('styleCodes','style_code'), ('skus','sku')]:
                    selected = values(arg)
                    if selected: conditions.append(column+'=ANY(%s)'); params.append(selected)
                category = request.args.get('categoryId')
                if category: conditions.append('category_id=%s'); params.append(positive(category))
            with self.connect() as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                read_at = conn.execute('SELECT transaction_timestamp() AS now').fetchone()['now'].astimezone(UTC).isoformat()
                query = 'SELECT * FROM external_api_products_v' + (' WHERE '+' AND '.join(conditions) if conditions else '') + ' ORDER BY id'
                if limit: query += ' LIMIT %s'; params.append(limit+1)
                rows = conn.execute(query, params).fetchall()
                if product_id and not rows: raise APIError(404, 'product_not_found', 'Product not found.')
                more = bool(limit and len(rows)>limit)
                if limit: rows = rows[:limit]
                items = self.bundles(conn, rows, inventory)
            result = {'readAt': read_at, 'requestId': g.external_request_id}
            if product_id: result['item'] = items[0]
            else:
                result['items'] = items
                if inventory: result['notFoundIds'] = [pid for pid in ids if pid not in {r['id'] for r in rows}]
                else: result.update(nextCursor=str(rows[-1]['id']) if more else None, limit=limit)
            return jsonify(result)
        except APIError as error: return self.error(error)


def register(app, db, security):
    from external_api_logging import install
    install(app)
    api = ExternalAPI(app, db, security)
    app.extensions['external_api'] = api
    app.teardown_request(api.teardown)
    app.add_url_rule(BASE+'/products', 'external_products', api.read, methods=['GET'])
    app.add_url_rule(BASE+'/products/<int:product_id>', 'external_product', api.read, methods=['GET'])
    app.add_url_rule(BASE+'/inventory', 'external_inventory', lambda: api.read(inventory=True), methods=['GET'])
    return api
