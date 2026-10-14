"""Real Cookie/CSRF contract uploads and exports on guarded *_test data only."""
import io
import uuid
import unittest
from unittest.mock import patch

from flask.testing import FlaskClient
from openpyxl import load_workbook
from PIL import Image
from werkzeug.security import generate_password_hash

from test_workbench import application, db, seed


class ContractCookieTest(unittest.TestCase):
    def setUp(self):
        self.legacy = patch.object(application.media, 'mode', 'legacy')
        self.legacy.start(); self.addCleanup(self.legacy.stop)
        seed()
        db.create_admin_user({'name': 'Finance cookie fixture', 'email': 'finance-cookie@fixture.test',
            'passwordHash': generate_password_hash('Workbench-Test-2026', method='pbkdf2:sha256:1000'),
            'status': 'active', 'role': 'finance', 'permissions': ['finance']})

    def login(self, role):
        client = FlaskClient(application.app, application.app.response_class)
        token = client.get('/api/auth/csrf').json['csrfToken']
        response = client.post('/api/auth/admin/login', json={
            'email': 'finance-cookie@fixture.test' if role == 'finance' else role + '@gingtto.test',
            'password': 'Workbench-Test-2026'}, headers={'Origin': 'http://localhost', 'X-CSRF-Token': token})
        self.assertEqual(response.status_code, 200)
        return client, {'Origin': 'http://localhost', 'X-CSRF-Token': response.json['csrfToken'],
            'X-Auth-Session': response.json['sessionId']}

    def picture(self):
        raw = io.BytesIO(); Image.new('RGB', (320, 240), 'navy').save(raw, 'PNG'); raw.seek(0)
        return raw

    def inventory(self):
        return db._fetch_all('SELECT size_code,stock,contract_pending,pending_inbound,pending_inspection FROM product_size_prices WHERE product_id=1 ORDER BY id')

    def payload(self, images):
        return {'requestId': str(uuid.uuid4()), 'partyA': 'Fixture buyer', 'partyB': 'Fixture factory',
            'factoryName': 'Fixture factory', 'contractNo': 'COOKIE-CONTRACT-FIXTURE', 'deliveryDate': '2026-10-20',
            'styleImage': images[0], 'sizeChartImage': images[1], 'items': [{'productId': 1, 'quantities': {'M': 5, 'Tall XL': 7}}]}

    def test_cookie_upload_replay_and_real_image_export_keep_inventory_rules(self):
        client, headers = self.login('admin')
        with patch('urllib.request.urlopen', side_effect=AssertionError('Fixture upload must remain local')):
            uploaded = client.post('/api/admin/uploads', data={'purpose': 'contract',
                'files': [(self.picture(), 'style.png'), (self.picture(), 'sizes.png')]}, headers=headers)
        self.assertEqual(uploaded.status_code, 200)
        images = uploaded.json['urls']; self.assertEqual(len(images), 2)
        guest = FlaskClient(application.app, application.app.response_class)
        for url in images:
            path = url.removeprefix('http://localhost')
            response = guest.get(path + '?w=160'); self.assertEqual(response.status_code, 200); response.close()
        before = self.inventory(); body = self.payload(images)
        created = client.post('/api/admin/contracts', json=body, headers=headers)
        self.assertEqual(created.status_code, 200, created.json)
        item = created.json['item']; self.assertEqual(item['quantity'], 12)
        replay = client.post('/api/admin/contracts', json=body, headers=headers)
        self.assertEqual(replay.status_code, 200); self.assertTrue(replay.json['replayed'])
        after = self.inventory()
        for old, new in zip(before, after):
            self.assertEqual(new['stock'], old['stock'])
            self.assertEqual(new['pending_inbound'], old['pending_inbound'])
            self.assertEqual(new['pending_inspection'], old['pending_inspection'])
            self.assertEqual(new['contract_pending'], old['contract_pending'] + {'M': 5, 'Tall XL': 7}.get(new['size_code'], 0))
        with patch('safe_images.fetch_image', side_effect=AssertionError('Owned contract images must not use HTTP')):
            exported = client.get('/api/admin/contracts/' + str(item['id']) + '/export', headers=headers)
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.headers['Cache-Control'], 'no-store')
        self.assertEqual(len(load_workbook(io.BytesIO(exported.data)).active._images), 2)
        self.assertEqual(self.inventory(), after)
        cancelled = client.post('/api/admin/contracts/' + str(item['id']) + '/cancel', json={'revision': item['revision']}, headers=headers)
        self.assertEqual(cancelled.status_code, 200, cancelled.json)
        self.assertEqual(self.inventory(), before)

    def test_missing_csrf_and_unauthorized_roles_do_not_create_or_export(self):
        client, headers = self.login('admin'); before = self.inventory()
        denied = client.post('/api/admin/uploads', data={'purpose': 'contract', 'files': (self.picture(), 'blocked.png')})
        self.assertEqual(denied.status_code, 403)
        body = self.payload(['/uploads/fixture.jpg', '/uploads/fixture.jpg'])
        self.assertEqual(client.post('/api/admin/contracts', json=body).status_code, 403)
        created = client.post('/api/admin/contracts', json=body, headers=headers)
        self.assertEqual(created.status_code, 200)
        after = self.inventory()
        for role in ['finance', 'warehouse']:
            limited, own_headers = self.login(role)
            self.assertEqual(limited.get('/api/admin/contracts/' + str(created.json['item']['id']) + '/export', headers=own_headers).status_code, 403)
            self.assertEqual(limited.post('/api/admin/contracts', json=body, headers=own_headers).status_code, 403)
            self.assertEqual(limited.post('/api/admin/uploads', data={'purpose': 'contract', 'files': (self.picture(), 'blocked.png')}, headers=own_headers).status_code, 403)
        self.assertEqual(self.inventory(), after)
        self.assertNotEqual(before, after)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM purchase_contracts')['n'], 1)


if __name__ == '__main__': unittest.main()
