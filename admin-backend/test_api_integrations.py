"""Real Cookie/CSRF management plus machine-only HTTP and DB boundary tests."""
import hashlib
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from flask import Flask, g
from flask.testing import FlaskClient
from psycopg import sql
from psycopg.errors import InsufficientPrivilege

from test_workbench import application, db, seed
import external_api
import external_api_schema
import security_core
import external_api_logging


class APIIntegrationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert db.DB_HOST == '127.0.0.1' and db.DB_NAME.endswith('_test')
        cls.password = secrets.token_urlsafe(40)
        cls.role = 'api_' + hashlib.sha256(db.DB_NAME.encode()).hexdigest()[:12] + '_test'
        cls.env = patch.dict(os.environ, {'EXTERNAL_API_ENABLED': '1', 'EXTERNAL_API_DB_USER': cls.role,
            'EXTERNAL_API_DB_PASSWORD': cls.password, 'EXTERNAL_API_PUBLIC_ORIGIN': 'https://gingtto.store',
            'SECURITY_ADMIN_CAPTCHA_ENABLED': '0', 'SECURITY_LOGIN_PROTECTION_ENABLED': '0'})
        cls.env.start()
        with db._connect() as conn:
            # This isolated fixture database is not the mirror/production DB.
            conn.execute(sql.SQL('REVOKE CREATE,TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db.DB_NAME)))
            conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'scripts/provision-external-api-role.py'),
            '--expected-db', db.DB_NAME, '--role', cls.role], capture_output=True, text=True)
        if result.returncode: raise RuntimeError('API test role provisioning failed: '+result.stderr[-1500:])
        cls.store = Flask('external-api-fixture')
        cls.store.testing = True
        cls.security = security_core.Security(cls.store, db, 'store')
        cls.api = external_api.register(cls.store, db, cls.security)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()

    def setUp(self):
        seed()
        with db._connect() as conn: conn.execute('TRUNCATE api_call_logs,api_integration_events,api_rate_buckets,api_request_leases')
        self.client, self.headers = self.login('admin')
        self.api.limit = 180
        self.api.global_limit = 10000
        self.api.global_concurrency = 4
        self.api.key_concurrency = 2
        self.machine = FlaskClient(self.store, self.store.response_class)

    def login(self, name):
        client = FlaskClient(application.app, application.app.response_class)
        csrf = client.get('/api/auth/csrf').json['csrfToken']
        response = client.post('/api/auth/admin/login', json={'email': name+'@gingtto.test', 'password': 'Workbench-Test-2026'},
            headers={'Origin': 'http://localhost', 'X-CSRF-Token': csrf})
        self.assertEqual(response.status_code, 200)
        return client, {'Origin': 'http://localhost', 'X-CSRF-Token': response.json['csrfToken'], 'X-Auth-Session': response.json['sessionId']}

    def generate(self, client=None, headers=None):
        client = client or self.client; headers = headers or self.headers
        item = client.get('/api/admin/api-integrations/me').json['item']
        response = client.post('/api/admin/api-integrations/me/generate', json={'version': item['version']}, headers=headers)
        self.assertEqual(response.status_code, 200)
        return response.json

    def call(self, key, path='/api/external/v1/products', **kwargs):
        return self.machine.get(path, headers={'Authorization': 'Bearer '+key}, **kwargs)

    def test_lifecycle_no_plaintext_and_cookies_do_not_authenticate_machine(self):
        generated = self.generate(); token = generated['key']
        event = db._fetch_one('SELECT key_id,event_code FROM api_integration_events ORDER BY id DESC LIMIT 1')
        self.assertEqual(str(event['key_id']),generated['item']['keyId'])
        self.assertEqual(event['event_code'],'generate')
        self.assertEqual(len(token), 48)
        metadata = self.client.get('/api/admin/api-integrations/me')
        self.assertNotIn(token, metadata.text)
        self.assertNotIn('token_hash', metadata.text)
        with db._connect() as conn:
            row = conn.execute('SELECT * FROM api_integrations').fetchone()
            self.assertEqual(row['token_hash'], hashlib.sha256(token.encode()).hexdigest())
            self.assertNotIn(token, str(row))
        self.assertEqual(self.call(token).status_code, 200)
        self.assertEqual(self.machine.get('/api/external/v1/products').status_code, 401)
        self.assertEqual(self.client.put('/api/admin/api-integrations/me/status', json={'enabled': False,'version':generated['item']['version']}).status_code, 403)
        paused = self.client.put('/api/admin/api-integrations/me/status', json={'enabled':False,'version':generated['item']['version']}, headers=self.headers)
        self.assertEqual(paused.status_code, 200)
        self.assertEqual(self.call(token).status_code, 401)
        resumed = self.client.put('/api/admin/api-integrations/me/status', json={'enabled':True,'version':paused.json['item']['version']}, headers=self.headers)
        reset = self.client.post('/api/admin/api-integrations/me/reset', json={'version':resumed.json['item']['version']}, headers=self.headers)
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(self.call(token).status_code, 401)
        self.assertEqual(self.call(reset.json['key']).status_code, 200)
        self.assertEqual(self.client.post('/api/admin/api-integrations/me/reset',json={'version':reset.json['item']['version']}).status_code,403)

    def test_database_budget_failure_is_503_without_auth_revoke_or_retry(self):
        import database_pool
        token=self.generate()['key']
        with patch.object(self.api,'connect',side_effect=database_pool.DatabaseBusy('fixture full')) as connect:
            response=self.call(token)
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json['code'],'database_busy')
        self.assertEqual(response.headers['Retry-After'],'2')
        self.assertIn('requestId',response.json)
        self.assertEqual(connect.call_count,1)
        self.assertNotIn('X-Session-Revoked',response.headers)

    def test_conservative_defaults_and_invalid_configuration(self):
        with patch.dict(os.environ,{'EXTERNAL_API_ENABLED':'0'}):
            for name in ['EXTERNAL_API_LIMIT','EXTERNAL_API_IP_LIMIT','EXTERNAL_API_GLOBAL_RPS','EXTERNAL_API_GLOBAL_CONCURRENCY','EXTERNAL_API_KEY_CONCURRENCY']:
                os.environ.pop(name,None)
            api=external_api.ExternalAPI(self.store,db,self.security)
            self.assertEqual((api.limit,api.ip_limit,api.global_limit,api.global_concurrency,api.key_concurrency),(60,300,10,4,2))
            with patch.dict(os.environ,{'EXTERNAL_API_KEY_CONCURRENCY':'5','EXTERNAL_API_GLOBAL_CONCURRENCY':'4'}):
                with self.assertRaises(RuntimeError):external_api.ExternalAPI(self.store,db,self.security)

    def test_global_short_window_across_keys_and_ips(self):
        token=self.generate()['key'];self.api.global_limit=2
        other='gapi_'+secrets.token_urlsafe(32)
        owner=db.create_admin_user({'name':'Other API fixture','email':uuid.uuid4().hex+'@fixture.test','passwordHash':'fixture','status':'active','role':'admin'})
        with db._connect() as conn:
            conn.execute('INSERT INTO api_integrations(admin_user_id,token_hash,key_id) VALUES(%s,%s,%s)',(owner['id'],hashlib.sha256(other.encode()).hexdigest(),uuid.uuid4()))
        self.assertEqual(self.call(token).status_code,200)
        self.assertEqual(self.call(other).status_code,200)
        response=self.machine.get('/api/external/v1/products',headers={'Authorization':'Bearer '+token},environ_overrides={'REMOTE_ADDR':'198.51.100.2'})
        self.assertEqual(response.status_code,429)
        self.assertEqual(response.headers['Retry-After'],'1')
        self.assertIn('requestId',response.json)

    def test_key_and_global_concurrency_limits_are_shared_metadata(self):
        token=self.generate()['key']
        key=db._fetch_one('SELECT key_id FROM api_integrations')['key_id']
        with db._connect() as conn:
            for _ in range(2):conn.execute("INSERT INTO api_request_leases VALUES(%s,%s,clock_timestamp()+interval '3 minutes')",(uuid.uuid4(),key))
        response=self.call(token)
        self.assertEqual((response.status_code,response.json['code']),(429,'concurrency_limited'))
        with db._connect() as conn:
            conn.execute('TRUNCATE api_request_leases')
            for _ in range(4):conn.execute("INSERT INTO api_request_leases VALUES(%s,%s,clock_timestamp()+interval '3 minutes')",(uuid.uuid4(),uuid.uuid4()))
        self.assertEqual(self.call(token).status_code,429)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM api_request_leases')['n'],4)

    def test_expired_lease_recovery_and_success_cleanup(self):
        token=self.generate()['key']
        with db._connect() as conn:
            for _ in range(4):conn.execute("INSERT INTO api_request_leases VALUES(%s,%s,clock_timestamp()-interval '1 second')",(uuid.uuid4(),uuid.uuid4()))
        self.assertEqual(self.call(token).status_code,200)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM api_request_leases')['n'],0)

    def test_error_response_releases_only_own_lease(self):
        token=self.generate()['key']
        with patch.object(self.api,'bundles',side_effect=RuntimeError('fixture failure')):
            self.assertEqual(self.call(token).status_code,500)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM api_request_leases')['n'],0)
        self.assertEqual(self.call(token).status_code,200)
        one,two=uuid.uuid4(),uuid.uuid4()
        with db._connect() as conn:
            for item in [one,two]:conn.execute("INSERT INTO api_request_leases VALUES(%s,%s,clock_timestamp()+interval '3 minutes')",(item,uuid.uuid4()))
        with self.store.test_request_context('/'):
            g.external_lease_id=one;self.api.release_request();self.api.release_request()
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM api_request_leases')['n'],1)

    def test_concurrency_budget_is_atomic_across_processes(self):
        code="""from flask import Flask,g
import db,security_core,external_api,uuid
a=Flask('leases');s=security_core.Security(a,db,'store');x=external_api.ExternalAPI(a,db,s)
with a.test_request_context('/'):
 g.external_request_id=str(uuid.uuid4())
 try:x.acquire_request(uuid.uuid4());print('admitted')
 except external_api.APIError as e:print(e.code)
"""
        children=[subprocess.Popen([sys.executable,'-c',code],cwd=Path(__file__).parent,env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(8)]
        results=[]
        for child in children:
            output,error=child.communicate(timeout=30)
            self.assertEqual(child.returncode,0,error[-1000:]);results.append(output.strip())
        self.assertEqual(results.count('admitted'),4)
        self.assertEqual(results.count('concurrency_limited'),4)

    def test_module_default_and_admin_persistent_block_and_revoke(self):
        sales = db._fetch_one("SELECT * FROM admin_users WHERE role='sales'")
        limited, headers = self.login('sales')
        self.assertEqual(limited.get('/api/admin/api-integrations/me').status_code,403)
        with db._connect() as conn: conn.execute("UPDATE admin_users SET permissions='[\"orders\",\"api-integrations\"]' WHERE id=%s",(sales['id'],))
        generated = self.generate(limited, headers)
        self.assertEqual(limited.get('/api/admin/api-integrations/accounts').status_code,403)
        self.assertEqual(limited.get('/api/admin/api-integrations/logs?userId=1').status_code,403)
        path = '/api/admin/api-integrations/accounts/'+str(sales['id'])
        blocked = self.client.put(path+'/authorization',json={'blocked':True,'version':generated['item']['version']}, headers=self.headers)
        self.assertEqual(blocked.status_code,200)
        self.assertEqual(self.call(generated['key']).status_code,401)
        self.assertEqual(limited.post('/api/admin/api-integrations/me/reset',json={'version':blocked.json['item']['version']},headers=headers).status_code,403)
        restored=self.client.put(path+'/authorization',json={'blocked':False,'version':blocked.json['item']['version']},headers=self.headers)
        self.assertEqual(self.call(generated['key']).status_code,200)
        revoked=self.client.post(path+'/revoke',json={'version':restored.json['item']['version']},headers=self.headers)
        self.assertEqual(revoked.status_code,200)
        self.assertEqual(self.call(generated['key']).status_code,401)
        accounts=self.client.get('/api/admin/api-integrations/accounts')
        self.assertNotIn(generated['key'],accounts.text)
        self.assertNotIn('token_hash',accounts.text)
        # Explicit lists do not silently acquire the new default permission.
        with db._connect() as conn: conn.execute("UPDATE admin_users SET permissions='[\"orders\"]' WHERE id=1")
        self.assertEqual(self.client.get('/api/admin/api-integrations/me').status_code,403)

    def test_permission_or_account_removal_permanently_revokes_but_password_does_not(self):
        token=self.generate()['key']
        with db._connect() as conn: conn.execute("UPDATE admin_users SET password_hash=password_hash,permissions=NULL WHERE id=1")
        self.assertEqual(self.call(token).status_code,200)
        with db._connect() as conn: conn.execute("UPDATE admin_users SET permissions='[\"orders\"]' WHERE id=1")
        self.assertEqual(self.call(token).status_code,401)
        with db._connect() as conn: conn.execute('UPDATE admin_users SET permissions=NULL WHERE id=1')
        self.assertEqual(self.call(token).status_code,401)
        token2=self.generate()['key']
        with db._connect() as conn: conn.execute("UPDATE admin_users SET status='disabled' WHERE id=1")
        self.assertEqual(self.call(token2).status_code,401)
        with db._connect() as conn: conn.execute("UPDATE admin_users SET status='active' WHERE id=1")
        self.assertEqual(self.call(token2).status_code,401)

    def test_expiry_zero_stock_material_order_and_field_whitelist(self):
        token=self.generate()['key']
        with db._connect() as conn:
            conn.execute("UPDATE product_size_prices SET stock=CASE size_code WHEN 'M' THEN -5 WHEN 'L' THEN 0 ELSE 12 END WHERE product_id=1")
            conn.execute("UPDATE product_images SET image_url='/uploads/'||id||'.jpg' WHERE product_id=1")
            conn.execute("UPDATE product_translations SET name='English catalog title',description='English material' WHERE product_id=1 AND lang_code='en'")
        row=self.call(token,'/api/external/v1/products/1')
        self.assertEqual(row.status_code,200)
        item=row.json['item'];self.assertEqual(item['title'],'English catalog title')
        self.assertEqual(item['sizes'],[{'size':'M','stock':0},{'size':'L','stock':0},{'size':'Tall XL','stock':12}])
        self.assertEqual(set(item),{'productId','styleCode','sku','sizes','color','category','title','summary','description','images'})
        self.assertTrue(all(v.startswith('https://gingtto.store/uploads/') for v in item['images']['gallery']))
        # Current catalog uses two explicitly configured external image origins.
        # Preserve original/signature URLs, but never auto-trust arbitrary hosts.
        originals=['https://img.smawell.shop/catalog/original.jpg?version=1',
                   'https://res.cloudinary.com/catalog/image/upload/original.jpg']
        with patch.object(self.api,'origins',self.api.origins|{'https://img.smawell.shop','https://res.cloudinary.com'}):
            for url in originals:self.assertEqual(self.api.image(url),url)
            for url in ['https://untrusted.test/image.jpg','https://user@img.smawell.shop/image.jpg',
                        'https://img.smawell.shop/a\nb.jpg','https://img.smawell.shop/a b.jpg',
                        'http://img.smawell.shop/image.jpg']:
                self.assertIsNone(self.api.image(url))
        self.assertEqual(row.headers['Cache-Control'],'no-store')
        self.assertNotIn('price',row.text.lower());self.assertNotIn('pending',row.text.lower())
        self.assertEqual(self.call(token,'/api/external/v1/products/99999').status_code,404)
        with db._connect() as conn: conn.execute('UPDATE products SET is_active=false WHERE id=1')
        self.assertEqual(self.call(token,'/api/external/v1/products/1').status_code,404)
        with db._connect() as conn: conn.execute("UPDATE api_integrations SET expires_at=clock_timestamp()-interval '1 second'")
        self.assertEqual(self.call(token).status_code,401)

    def test_cursor_filters_limits_and_missing_ids_no_business_writes(self):
        token=self.generate()['key']
        before=db._fetch_all('SELECT id,stock FROM product_size_prices ORDER BY id')
        first=self.call(token,'/api/external/v1/products?limit=2').json
        self.assertEqual([i['productId'] for i in first['items']],[1,2])
        second=self.call(token,'/api/external/v1/products?limit=2&cursor='+first['nextCursor']).json
        self.assertEqual([i['productId'] for i in second['items']],[3]);self.assertIsNone(second['nextCursor'])
        for query in ['limit=0','limit=101','cursor=-1','limit=1.5','keyword='+'x'*201,'styleCodes='+','.join(map(str,range(101)))]:
            self.assertEqual(self.call(token,'/api/external/v1/products?'+query).status_code,400)
        self.assertEqual(len(self.call(token,'/api/external/v1/products?skus=GT-2026-1,GT-2026-3').json['items']),2)
        inventory=self.call(token,'/api/external/v1/inventory?productIds=1,9999').json
        self.assertEqual(inventory['notFoundIds'],[9999]);self.assertNotIn('images',inventory['items'][0])
        self.assertEqual(self.call(token,'/api/external/v1/inventory').status_code,400)
        self.assertEqual(self.call(token,'/api/external/v1/inventory?productIds='+','.join(map(str,range(1,102)))).status_code,400)
        self.assertEqual(db._fetch_all('SELECT id,stock FROM product_size_prices ORDER BY id'),before)

    def test_independent_auth_namespace_and_cookie_csrf_rules(self):
        token=self.generate()['key'];auth={'Authorization':'Bearer '+token}
        guest=FlaskClient(application.app,application.app.response_class)
        self.assertEqual(guest.get('/api/admin/orders',headers=auth).status_code,401)
        self.assertEqual(self.machine.get('/api/auth/me',headers=auth).status_code,404)
        self.assertEqual(self.call(token,'/api/external/v1/products?token=bad').status_code,400)
        self.assertEqual(self.call(token,'/api/external/v1/orders').status_code,404)
        self.assertIn(self.machine.post('/api/external/v1/products',headers=auth).status_code,{404,405})
        self.assertEqual(self.machine.get('/api/external/v1/products',headers={'Cookie':'gingtto_store=anything'}).status_code,401)
        self.assertEqual(guest.post('/api/admin/api-integrations/me/generate',json={'version':0},headers=auth).status_code,401)

    def test_db_role_no_business_or_key_management_access(self):
        for statement in ['SELECT * FROM orders','SELECT password_hash FROM admin_users',
                          'UPDATE product_size_prices SET stock=0','SELECT * FROM finance_style_costs',
                          'CREATE TABLE forbidden_api_table(id int)',
                          'SELECT token_hash FROM api_integrations',
                          "UPDATE api_integrations SET enabled=true",'DELETE FROM api_call_logs']:
            with self.assertRaises(InsufficientPrivilege),self.api.connect() as conn: conn.execute(statement)
        with self.api.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM external_api_products_v').fetchone()['n'],3)

    def test_provisioner_rejects_business_identity_without_changing_its_grants(self):
        role='api_business_'+uuid.uuid4().hex[:10]+'_test'
        with db._connect() as conn:
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT').format(sql.Identifier(role)))
            conn.execute(sql.SQL('GRANT SELECT ON products TO {}').format(sql.Identifier(role)))
        try:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/provision-external-api-role.py'),
                '--expected-db',db.DB_NAME,'--role',role],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            with db._connect() as conn:
                self.assertTrue(conn.execute("SELECT has_table_privilege(%s,'products','SELECT') AS allowed",(role,)).fetchone()['allowed'])
                self.assertIsNone(conn.execute('SELECT rolpassword FROM pg_authid WHERE rolname=%s',(role,)).fetchone()['rolpassword'])
        finally:
            with db._connect() as conn:
                conn.execute(sql.SQL('REVOKE SELECT ON products FROM {}').format(sql.Identifier(role)))
                conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))

    def test_startup_rejects_privileges_on_unapproved_views_and_sequences(self):
        with db._connect() as conn:
            conn.execute('CREATE VIEW api_forbidden_fixture_v AS SELECT * FROM finance_style_costs')
            conn.execute(sql.SQL('GRANT SELECT ON api_forbidden_fixture_v TO {}').format(sql.Identifier(self.role)))
        try:
            with self.assertRaises(RuntimeError):self.api.validate_role()
        finally:
            with db._connect() as conn:conn.execute('DROP VIEW api_forbidden_fixture_v')
        with db._connect() as conn:conn.execute(sql.SQL('GRANT USAGE ON SEQUENCE orders_id_seq TO {}').format(sql.Identifier(self.role)))
        try:
            with self.assertRaises(RuntimeError):self.api.validate_role()
        finally:
            with db._connect() as conn:conn.execute(sql.SQL('REVOKE USAGE ON SEQUENCE orders_id_seq FROM {}').format(sql.Identifier(self.role)))
        self.api.validate_role()

    def test_http_access_logs_scrub_credentials_and_external_query_strings(self):
        token='gapi_'+secrets.token_urlsafe(32)
        line='GET /api/external/v1/products?token='+token.replace('gapi_','%67api_')+' HTTP/1.1'
        record=logging.LogRecord('werkzeug',logging.INFO,'',0,'%s',(line,),None)
        external_api_logging.CredentialFilter().filter(record)
        self.assertNotIn('?',record.getMessage());self.assertNotIn('%67api_',record.getMessage())
        record=logging.LogRecord('werkzeug',logging.INFO,'',0,'%s',(line.replace('/api/external/','/api%2Fexternal/'),),None)
        external_api_logging.CredentialFilter().filter(record)
        self.assertNotIn('?',record.getMessage());self.assertNotIn('%67api_',record.getMessage())
        atoms={'r':'GET /api/external/v1/products?token='+token+' HTTP/1.1','q':'token='+token,
               '{authorization}i':'Bearer '+token,'{cookie}i':'session-private-fixture'}
        record=logging.LogRecord('gunicorn.access',logging.INFO,'',0,'%(r)s %(q)s %({authorization}i)s %({cookie}i)s',(atoms,),None)
        external_api_logging.CredentialFilter().filter(record)
        message=record.getMessage()
        self.assertNotIn(token,message);self.assertNotIn('session-private-fixture',message);self.assertNotIn('?',message)

    def test_concurrent_generation_one_winner_and_stale_version_rejected(self):
        cookie=self.client.get_cookie(application.security.cookie)
        def generate_one(_):
            client=FlaskClient(application.app,application.app.response_class)
            client.set_cookie(cookie.key,cookie.value)
            return client.post('/api/admin/api-integrations/me/generate',json={'version':0},headers=self.headers).status_code
        with ThreadPoolExecutor(max_workers=4) as pool: result=list(pool.map(generate_one,range(4)))
        self.assertEqual(sorted(result),[200,409,409,409])
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM api_integrations WHERE token_hash IS NOT NULL')['n'],1)

    def test_quota_shared_processes_and_redacted_logs(self):
        token=self.generate()['key'];self.api.limit=2
        browser_buckets=db._fetch_all('SELECT bucket_key,ticks FROM security_rate_buckets ORDER BY bucket_key')
        self.assertEqual(self.call(token).status_code,200)
        self.assertEqual(self.call(token).status_code,200)
        limited=self.call(token);self.assertEqual(limited.status_code,429);self.assertGreater(int(limited.headers['Retry-After']),0)
        self.assertEqual(db._fetch_all('SELECT bucket_key,ticks FROM security_rate_buckets ORDER BY bucket_key'),browser_buckets)
        logs=self.client.get('/api/admin/api-integrations/logs').json
        self.assertEqual(logs['total'],3);self.assertNotIn(token,str(logs))
        self.assertEqual(set(logs['items'][0]),{'time','route','status','durationMs'})
        # Independent OS processes, not just threads or per-worker memory.
        code="""from flask import Flask
import db,security_core,external_api
a=Flask('quota');s=security_core.Security(a,db,'store');x=external_api.ExternalAPI(a,db,s)
print(x.reserve('process-fixture','shared',3))
"""
        children=[subprocess.Popen([sys.executable,'-c',code],cwd=Path(__file__).parent,env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(6)]
        result=[]
        for child in children:
            output,error=child.communicate(timeout=30)
            self.assertEqual(child.returncode,0,error[-1000:]);result.append(int(output.strip()))
        self.assertEqual(result.count(0),3);self.assertEqual(sum(v>0 for v in result),3)

    def test_response_is_one_snapshot_during_concurrent_stock_change(self):
        token=self.generate()['key']
        stock=db._fetch_one("SELECT stock FROM product_size_prices WHERE product_id=1 AND size_code='M'")['stock']
        original=self.api.bundles
        def change_while_reading(conn,rows,inventory=False):
            with db._connect() as writer:
                writer.execute("UPDATE product_size_prices SET stock=stock+7 WHERE product_id=1 AND size_code='M'")
            return original(conn,rows,inventory)
        with patch.object(self.api,'bundles',side_effect=change_while_reading):
            response=self.call(token,'/api/external/v1/products/1')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['item']['sizes'][0]['stock'],stock)
        self.assertEqual(self.call(token,'/api/external/v1/products/1').json['item']['sizes'][0]['stock'],stock+7)

    def test_beijing_expiry_validation_and_https_host_boundary(self):
        for value in ['2020-01-01T00:00:00+08:00','2099-01-01T00:00:00','bad']:
            response=self.client.post('/api/admin/api-integrations/me/generate',json={'version':0,'expiresAt':value},headers=self.headers)
            self.assertEqual(response.status_code,400)
        response=self.client.post('/api/admin/api-integrations/me/generate',json={'version':0,'expiresAt':'2099-01-01T12:00:00+08:00'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['item']['expiresAt'],'2099-01-01T04:00:00+00:00')
        token=response.json['key']
        with patch.object(self.security,'secure',True):
            self.assertEqual(self.call(token).status_code,426)
            self.assertEqual(self.call(token,base_url='https://localhost').status_code,200)
            self.assertEqual(self.machine.get('/api/external/v1/products',headers={'Authorization':'Bearer '+token,'X-Forwarded-Proto':'https'},environ_overrides={'REMOTE_ADDR':'203.0.113.7'}).status_code,426)
            self.assertEqual(self.call(token,base_url='https://invalid-host.test').status_code,400)

    def test_each_product_keeps_its_size_order_and_removed_sizes_are_not_zero_filled(self):
        token=self.generate()['key']
        with db._connect() as conn:
            conn.execute('DELETE FROM product_sizes WHERE product_id=2')
            conn.execute('DELETE FROM product_size_prices WHERE product_id=2')
            for order,size in enumerate(['36','34','S/28','均码']):
                conn.execute('INSERT INTO product_sizes(product_id,size_code,sort_order) VALUES(2,%s,%s)',(size,order))
                conn.execute('INSERT INTO product_size_prices(product_id,size_code,sort_order,price,stock) VALUES(2,%s,%s,10,0)',(size,order))
            conn.execute("DELETE FROM product_sizes WHERE product_id=3 AND size_code='L'")
        response=self.call(token).json['items']
        self.assertEqual([v['size'] for v in response[1]['sizes']],['36','34','S/28','均码'])
        self.assertNotIn('L',[v['size'] for v in response[2]['sizes']])
        self.assertEqual([v['size'] for v in response[0]['sizes']],['M','L','Tall XL'])

    def test_disabled_default_and_idempotent_additive_schema(self):
        with patch.dict(os.environ,{'EXTERNAL_API_ENABLED':'0'}):
            fixture=Flask('api-off');security=security_core.Security(fixture,db,'store');external_api.register(fixture,db,security)
        disabled=fixture.test_client().get('/api/external/v1/products')
        self.assertEqual(disabled.status_code,503)
        self.assertEqual(disabled.json['code'],'api_not_enabled')
        before=db._fetch_all('SELECT id,total_amount,status FROM orders ORDER BY id')
        token=self.generate()['key']
        with db._connect() as conn: external_api_schema.migrate(conn.cursor())
        self.assertEqual(self.call(token).status_code,200)
        self.assertEqual(db._fetch_all('SELECT id,total_amount,status FROM orders ORDER BY id'),before)


if __name__=='__main__': unittest.main()
