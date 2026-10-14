"""Real cookie clients (no fixture bearer adapter), only guarded *_test databases."""
import io
import os
import socket
import subprocess
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import Flask, jsonify
from flask.testing import FlaskClient
from PIL import Image
from test_workbench import application, db, seed
from private_media import file_id, validate_content, url_for
from security_core import token_hash, validate_password, migrate, Security
from safe_images import public_address, validate_url, fetch_image


def png():
    out=io.BytesIO();Image.new('RGB',(4,4),'blue').save(out,format='PNG');return out.getvalue()


class SecurityTest(unittest.TestCase):
    def setUp(self):
        # These tests retain coverage for the later private-attachment cutover.
        # The released phase-one default is tested separately, not overridden.
        self.media_patch = patch.object(application.media, 'mode', 'private')
        self.media_patch.start(); self.addCleanup(self.media_patch.stop)
        self.tokens,self.products=seed()
        self.app=application.app
        self.client=self.login()

    def bare(self): return FlaskClient(self.app,self.app.response_class)

    def login(self, role='admin'):
        client=self.bare()
        csrf=client.get('/api/auth/csrf').json['csrfToken']
        response=client.post('/api/auth/admin/login',json={'email':role+'@gingtto.test','password':'Workbench-Test-2026'},headers={'Origin':'http://localhost','X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,200,response.json)
        client.csrf=response.json['csrfToken'];client.public_id=response.json['sessionId']
        self.assertNotIn('token',response.json)
        return client

    def headers(self,client=None):
        client=client or self.client
        return {'Origin':'http://localhost','X-CSRF-Token':client.csrf,'X-Auth-Session':client.public_id}

    def upload(self,client=None,purpose='order'):
        client=client or self.client
        response=client.post('/api/admin/uploads',data={'files':(io.BytesIO(png()),'fixture.png'),'purpose':purpose},headers=self.headers(client))
        self.assertEqual(response.status_code,200,response.json)
        return response.json['urls'][0]

    def payload(self, attachments=None):
        return {'requestId':str(uuid.uuid4()),'userId':1,'contactName':'Fixture Buyer','phone':'123456',
          'country':'Germany','address':'Fixture Street','shippingFee':0,
          'items':[{'productId':1,'sizeCode':'M','quantity':2,'unitPrice':20}],
          'labelImageUrls':attachments or []}

    def test_cookie_hash_absolute_expiry_and_single_login(self):
        cookie=self.client.get_cookie(application.security.cookie)
        self.assertTrue(cookie.http_only);self.assertEqual(cookie.same_site,'Lax');self.assertFalse(cookie.domain.startswith('.'))
        raw=cookie.value
        row=db._fetch_one('SELECT * FROM admin_sessions WHERE token_hash=%s',(token_hash(raw),))
        self.assertNotEqual(row['token'],raw)
        self.assertAlmostEqual((row['expires_at']-row['created_at']).total_seconds(),7*86400,delta=10)
        self.client.get('/api/auth/me');self.client.get('/api/admin/orders')
        self.assertEqual(db._fetch_one('SELECT expires_at FROM admin_sessions WHERE id=%s',(row['id'],))['expires_at'],row['expires_at'])
        newer=self.login();self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertEqual(newer.get('/api/auth/me').status_code,200)

    def test_csrf_origin_guard_and_bearer_retirement(self):
        body=self.payload()
        for headers in ({'Origin':'http://localhost'},{**self.headers(),'Origin':'https://outside.test'},{**self.headers(),'X-Auth-Session':'different-public-id'}):
            response=self.client.post('/api/admin/orders',json=body,headers=headers)
            self.assertIn(response.status_code,[403,409])
        other=self.bare();self.assertEqual(other.get('/api/admin/orders',headers={'Authorization':'Bearer '+self.tokens['admin']}).status_code,401)
        self.assertEqual(other.post('/api/auth/admin/login',json={'email':'admin@gingtto.test','password':'Workbench-Test-2026'}).status_code,403)

    def test_old_endpoints_host_and_cache_headers(self):
        guest=self.bare()
        for path,status in [('/api/public/products',410),('/api/internal/orders',404),('/api/admin/orders',401),('/uploads/unknown.pdf',404)]:
            self.assertEqual(guest.get(path).status_code,status)
        self.assertEqual(guest.get('/api/health',headers={'Host':'arbitrary.invalid'}).status_code,400)
        response=self.client.get('/api/admin/orders',headers={'Origin':'https://outside.test'})
        self.assertEqual(response.headers.get('Cache-Control'),'no-store')
        self.assertEqual(response.headers.get('X-Content-Type-Options'),'nosniff')
        self.assertNotIn('Access-Control-Allow-Origin',response.headers)

    def test_reused_app_context_never_reuses_previous_request_identity(self):
        with self.app.app_context():
            self.assertEqual(self.client.get('/api/admin/orders').status_code,200)
            self.assertEqual(self.bare().get('/api/admin/orders').status_code,401)
            self.assertEqual(self.client.get('/api/admin/orders').status_code,200)

    def test_production_cookie_https_and_untrusted_forwarding(self):
        db._fetch_one("INSERT INTO security_media_migrations(name) VALUES('legacy-private-v1') ON CONFLICT DO NOTHING RETURNING name")
        with patch.dict(os.environ,{'APP_ENV':'production','SECURITY_SECRET':'production-probe-'+uuid.uuid4().hex,
                'SECURITY_ALLOWED_HOSTS':'admin.fixture.test','SECURITY_LEGACY_SOURCES_CLOSED':'1',
                'SECURITY_ALLOWED_ORIGINS':'','SECURITY_PROXY_PEERS':'127.0.0.1,::1'}):
            probe=Flask('production-probe');boundary=Security(probe,db,'admin')
            @probe.post('/api/auth/admin/login')
            def login():return boundary.sign_in('admin@gingtto.test','Workbench-Test-2026',lambda user:user)
            @probe.get('/api/admin/orders')
            @boundary.authenticated
            def orders():return jsonify({'items':[]})
            client=FlaskClient(probe,probe.response_class)
            self.assertEqual(client.post('/api/auth/admin/login',base_url='http://admin.fixture.test').status_code,426)
            csrf=client.get('/api/auth/csrf',base_url='https://admin.fixture.test').json['csrfToken']
            signed=client.post('/api/auth/admin/login',base_url='https://admin.fixture.test',
                headers={'Origin':'https://admin.fixture.test','X-CSRF-Token':csrf})
            self.assertEqual(signed.status_code,200)
            cookie=client.get_cookie('__Host-gingtto-admin-session',domain='admin.fixture.test')
            self.assertTrue(cookie.secure);self.assertTrue(cookie.http_only);self.assertEqual(cookie.same_site,'Lax')
            self.assertEqual(client.get('/api/admin/orders',base_url='https://admin.fixture.test').status_code,200)
            forged=client.get('/api/admin/orders',base_url='http://admin.fixture.test',
                headers={'X-Forwarded-Proto':'https','X-Forwarded-For':'127.0.0.1'},environ_overrides={'REMOTE_ADDR':'198.51.100.1'})
            self.assertEqual(forged.status_code,426)
            self.assertEqual(client.get('/api/admin/orders',base_url='https://unknown.fixture.test').status_code,400)

    def test_logout_expiration_and_permissions_revoke(self):
        self.assertEqual(self.client.post('/api/auth/logout',headers=self.headers()).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        client=self.login('sales')
        db.update_admin_user(2,{'name':'Fixture','email':'sales@gingtto.test','status':'active','role':'sales','permissions':['inventory']})
        self.assertEqual(client.get('/api/auth/me').status_code,401)
        client=self.login()
        db._fetch_one('UPDATE admin_sessions SET expires_at=clock_timestamp()-interval \'1 second\' WHERE public_id=%s RETURNING id',(client.public_id,))
        self.assertEqual(client.get('/api/auth/me').status_code,401)

    def test_login_cooldown_and_generic_failure(self):
        enabled = patch.object(application.security, 'login_protection', True)
        enabled.start(); self.addCleanup(enabled.stop)
        client=self.bare();csrf=client.get('/api/auth/csrf').json['csrfToken'];headers={'Origin':'http://localhost','X-CSRF-Token':csrf}
        a=client.post('/api/auth/admin/login',json={'email':'missing@test.invalid','password':'wrong'},headers=headers)
        b=client.post('/api/auth/admin/login',json={'email':'sales@gingtto.test','password':'wrong'},headers=headers)
        self.assertEqual(a.json,b.json)
        for i in range(9): response=client.post('/api/auth/admin/login',json={'email':'sales@gingtto.test','password':'wrong'},headers=headers)
        self.assertEqual(response.status_code,429);self.assertGreater(int(response.headers['Retry-After']),0)
        self.assertEqual(client.post('/api/auth/admin/login',json={'email':'sales@gingtto.test','password':'Workbench-Test-2026'},headers=headers).status_code,429)

    def test_shared_quota_concurrency_and_no_partial_write(self):
        with ThreadPoolExecutor(max_workers=6) as workers:
            retries=list(workers.map(lambda _:application.security.reserve('concurrent-fixture','one',3,60),range(9)))
        self.assertEqual(retries.count(0),3)
        before=db._fetch_one("SELECT stock FROM product_size_prices WHERE product_id=1 AND size_code='M'")['stock']
        with patch.dict(os.environ,{'SECURITY_LIMIT_WRITE':'1'}):
            first=self.client.post('/api/admin/orders',json=self.payload(),headers=self.headers());self.assertEqual(first.status_code,200,first.json)
            second=self.client.post('/api/admin/orders',json=self.payload(),headers=self.headers());self.assertEqual(second.status_code,429,second.json)
        after=db._fetch_one("SELECT stock FROM product_size_prices WHERE product_id=1 AND size_code='M'")['stock']
        self.assertEqual(before-after,2)

    def test_shared_quota_across_processes(self):
        code = """import db; from flask import Flask; from security_core import Security
s=Security(Flask('quota-process'),db,'admin')
print(s.reserve('multiprocess-fixture','shared-subject',3,60))"""
        def reserve(_):
            result = subprocess.run([sys.executable, '-c', code], env=os.environ.copy(),
                capture_output=True, text=True, timeout=60, check=True)
            return int(result.stdout.strip())
        with ThreadPoolExecutor(max_workers=6) as workers:
            retries = list(workers.map(reserve, range(8)))
        self.assertEqual(retries.count(0), 3)
        self.assertTrue(all(value >= 0 for value in retries))

    def test_unbound_private_upload_and_attachment_binding_rollback(self):
        url=self.upload();sales=self.login('sales');guest=self.bare()
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(sales.get(url).status_code,404);self.assertIn(guest.get(url).status_code,[401,404])
        before=db._fetch_one("SELECT stock FROM product_size_prices WHERE product_id=1 AND size_code='M'")['stock']
        body=self.payload([url]);body['labelImageUrls']=['https://outside.invalid/a.png']
        response=self.client.post('/api/admin/orders',json=body,headers=self.headers());self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(db._fetch_one("SELECT stock FROM product_size_prices WHERE product_id=1 AND size_code='M'")['stock'],before)
        response=self.client.post('/api/admin/orders',json=self.payload([url]),headers=self.headers());self.assertEqual(response.status_code,200,response.json)
        order=response.json['order'];self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(sales.get(url).status_code,404)
        db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id=%s RETURNING id',(order['id'],))
        self.assertEqual(sales.get(url).status_code,200)
        db._fetch_one('UPDATE orders SET owner_admin_id=NULL WHERE id=%s RETURNING id',(order['id'],))
        self.assertEqual(sales.get(url).status_code,404)

    def test_upload_real_type_and_active_pdf_validation(self):
        for data,name in [(b'<svg><script>bad</script></svg>','bad.svg'),(b'MZ executable','bad.png'),(png(),'wrong.jpg')]:
            r=self.client.post('/api/admin/uploads',data={'files':(io.BytesIO(data),name)},headers=self.headers())
            self.assertEqual(r.status_code,400,r.json)
        from pypdf import PdfWriter
        out=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.add_js('app.alert(1)');writer.write(out)
        with self.assertRaises(ValueError):validate_content(out.getvalue(),'.pdf')
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);out=io.BytesIO();writer.write(out)
        self.assertEqual(validate_content(out.getvalue(),'.pdf'),'application/pdf')
        camera=io.BytesIO()
        Image.new('RGB',(4,4),'blue').save(camera,format='MPO',save_all=True,append_images=[Image.new('RGB',(4,4),'red')])
        self.assertEqual(validate_content(camera.getvalue(),'.jpg'),'image/jpeg')

    def test_legacy_cdn_image_format_and_private_copy_are_independent(self):
        old='/uploads/cdn-negotiated.jpg'
        public=application.media.register_legacy(old,png(),purpose='product',entity_type='product',entity_id=1)
        private=application.media.register_legacy(old,png(),purpose='legacy-private',entity_type='order',entity_id=1)
        self.assertEqual(public['mime_type'],'image/png');self.assertTrue(public['filename'].endswith('.png'))
        self.assertNotEqual(public['storage_key'],private['storage_key'])
        self.assertEqual(self.bare().get(url_for(public)).status_code,200)
        self.assertIn(self.bare().get(url_for(private)).status_code,[401,404])
        self.assertEqual(self.client.get(url_for(private)).status_code,200)

    def test_migration_idempotent_retains_progress_and_retires_legacy(self):
        legacy=db._fetch_one("INSERT INTO admin_sessions(admin_user_id,token) VALUES(1,'fixture-legacy-plaintext') RETURNING id")
        with db._connect() as conn:
            migrate(conn.cursor());migrate(conn.cursor())
        row=db._fetch_one('SELECT token,token_hash,revoked_at FROM admin_sessions WHERE id=%s',(legacy['id'],))
        self.assertEqual(row['token_hash'],token_hash('fixture-legacy-plaintext'));self.assertNotEqual(row['token'],'fixture-legacy-plaintext');self.assertIsNotNone(row['revoked_at'])
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)

    def test_password_rule_query_cap_and_sanitized_audit(self):
        with patch.dict(os.environ, {'SECURITY_LOGIN_PROTECTION_ENABLED': '1'}):
            for value in ['short','123456789012','password1234','Password123!','Welcome2026!','qwertyuiop12']:
                with self.assertRaises(ValueError):validate_password(value)
            validate_password('Fixture-Strong-Password-2026')
        self.assertEqual(self.client.get('/api/admin/orders?keyword='+'x'*201).status_code,400)
        self.client.post('/api/admin/orders',json=self.payload(),headers={'Origin':'https://outside.test'})
        row=db._fetch_one('SELECT * FROM security_audit_events ORDER BY id DESC LIMIT 1')
        self.assertEqual(row['event_code'],'csrf_invalid')
        self.assertNotIn('request_body',row);self.assertNotIn('token',row);self.assertNotIn('email',row)

    def test_ssrf_destinations_and_redirects(self):
        for value in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','224.0.0.1']:
            self.assertFalse(public_address(value))
        self.assertTrue(public_address('1.1.1.1'))
        with patch.dict(os.environ,{'PUBLIC_IMAGE_ORIGINS':'https://trusted.test'}):
            for url in ['http://trusted.test/image.png','https://trusted.test:8443/a','https://user:secret@trusted.test/a','https://outside.test/a']:
                with self.assertRaises(ValueError):validate_url(url)
            with patch('safe_images.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
                with self.assertRaises(ValueError):validate_url('https://trusted.test/a.png')
            with patch('safe_images.socket.getaddrinfo',return_value=[
                    (socket.AF_INET6,1,6,'',('2606:4700:4700::1111',443)),(socket.AF_INET,1,6,'',('1.1.1.1',443))]):
                self.assertEqual(validate_url('https://trusted.test/a.png')[1],'1.1.1.1')


if __name__=='__main__':unittest.main()
