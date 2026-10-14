"""Department defaults, explicit staff grants and account recovery protections."""
import unittest
from test_workbench import seed, application, db
from module_permissions import DEFAULTS
from werkzeug.security import generate_password_hash


class ModulePermissionsTest(unittest.TestCase):
    def setUp(self):
        self.tokens, _ = seed()
        finance = db.create_admin_user({'name':'Finance fixture','email':'finance@gingtto.test',
            'passwordHash':generate_password_hash('Fixture-only',method='pbkdf2:sha256:1000'),
            'status':'active','role':'finance'})
        self.tokens['finance'] = db.create_admin_session(finance['id'])
        application.app.config['TESTING'] = True

    def call(self, path, method='GET', body=None, role='admin'):
        with application.app.test_client() as client:
            return client.open('/api/admin/' + path, method=method, json=body,
                               headers={'Authorization': 'Bearer ' + self.tokens[role]})

    def grant(self, role, permissions):
        user = db.get_admin_user_by_email(role + '@gingtto.test')
        response = self.call(f"admin-users/{user['id']}", 'PUT', {'permissions': permissions})
        self.assertEqual(response.status_code, 200, response.json)
        # Permission changes retire the old cookie; a fresh login then sees
        # the new grant. Both boundaries must be exercised, not just 403.
        self.assertIsNone(db.get_admin_user_by_session_token(self.tokens[role]))
        self.assertEqual(self.call('orders', role=role).status_code, 401)
        self.tokens[role] = db.create_admin_session(user['id'])
        return response.json['user']

    def test_legacy_defaults_and_explicit_empty_existing_session(self):
        for role, expected in DEFAULTS.items():
            user = db.get_admin_user_by_session_token(self.tokens[role])
            self.assertEqual(user['permissions'], expected)
        self.grant('sales', [])
        for path in ['dashboard', 'inventory', 'orders', 'products', 'home-config', 'catalog-options']:
            self.assertEqual(self.call(path, role='sales').status_code, 403, path)
        self.assertEqual(db.get_admin_user_by_session_token(self.tokens['sales'])['permissions'], [])
        self.grant('sales', ['inventory'])
        self.assertEqual(self.call('inventory?page=1', role='sales').status_code, 200)
        self.assertEqual(self.call('orders', role='sales').status_code, 403)
        listed = self.call('admin-users?page=1').json['items']
        self.assertEqual(next(u for u in listed if u['role'] == 'sales')['permissions'], ['inventory'])

    def test_role_limits_and_management_denial(self):
        self.assertEqual(self.call('admin-users/4', 'PUT', {'permissions': ['admin-users']}).status_code, 400)
        for value in [None, 'inventory', [1], ['unknown']]:
            self.assertEqual(self.call('admin-users/2', 'PUT', {'permissions': value}).status_code, 400)
        self.assertEqual(self.call('admin-users/2', 'PUT', {'permissions': []}, role='sales').status_code, 403)
        self.grant('warehouse', ['inventory'])
        self.assertEqual(self.call('orders/1', 'PUT', {'status': 'paid'}, role='warehouse').status_code, 403)
        self.assertEqual(self.call('inventory/1', 'PUT', {'stockBySize': {'M': 20}}, role='customer').status_code, 403)

    def test_last_effective_administrator_and_creation(self):
        self.assertEqual(self.call('admin-users/1', 'PUT', {'permissions': []}).status_code, 400)
        response = self.call('admin-users', 'POST', {'name': 'Restricted admin', 'email': 'restricted@test.local',
                           'password': 'Fixture-only-password', 'role': 'admin', 'permissions': ['inventory']})
        self.assertEqual(response.status_code, 201, response.json)
        other = response.json['user']['id']
        self.assertEqual(self.call('admin-users/1', 'PUT', {'permissions': []}).status_code, 400)
        self.assertEqual(self.call(f'admin-users/{other}', 'PUT', {'permissions': ['admin-users']}).status_code, 200)
        self.grant('admin', ['inventory'])
        self.assertEqual(self.call('admin-users').status_code, 403)
        self.tokens['admin'] = db.create_admin_session(other)
        self.assertEqual(self.call(f'admin-users/{other}', 'PUT', {'status': 'disabled'}).status_code, 400)
        self.assertEqual(self.call(f'admin-users/{other}', 'PUT', {'role': 'sales', 'permissions': []}).status_code, 400)

    def test_module_dependencies_and_retired_activity_writes(self):
        before = db.get_homepage_config()
        self.assertEqual(self.call('home-config', 'PUT', before).status_code, 410)
        self.assertEqual(self.call('activity-config', 'PUT', before).status_code, 410)
        self.assertEqual(db.get_homepage_config(), before)
        self.grant('sales', ['presale'])
        self.assertEqual(self.call('presale', role='sales').status_code, 200)
        self.assertEqual(self.call('products?page=1', role='sales').status_code, 200)
        self.assertEqual(self.call('products/1', 'DELETE', role='sales').status_code, 403)
        self.assertEqual(self.call('home-config', role='sales').status_code, 403)
        self.assertEqual(self.call('activity-config','PUT',before,role='sales').status_code,403)
        self.grant('sales', ['orders'])
        self.assertEqual(self.call('orders/customers?page=1', role='sales').status_code, 200)
        self.assertEqual(self.call('products/1', role='sales').status_code, 200)
        self.assertEqual(self.call('products/batch', 'POST', {}, role='sales').status_code, 403)

    def test_create_finance_account_defaults_and_explicit_revocation(self):
        response=self.call('admin-users','POST',{'name':'New finance','email':'new-finance@test.local',
            'password':'Fixture-only-password','role':'finance'})
        self.assertEqual(response.status_code,201,response.json)
        account=response.json['user']
        self.assertCountEqual(account['permissions'],['finance','contracts'])
        self.tokens['finance']=db.create_admin_session(account['id'])
        self.assertEqual(self.call('finance/options',role='finance').status_code,200)
        self.assertEqual(self.call('admin-users',role='finance').status_code,403)
        self.assertEqual(self.call(f"admin-users/{account['id']}",'PUT',{'permissions':[]}).status_code,200)
        self.assertEqual(self.call('finance/options',role='finance').status_code,401)
        self.tokens['finance']=db.create_admin_session(account['id'])
        self.assertEqual(self.call('finance/options',role='finance').status_code,403)
        self.assertEqual(self.call('admin-users/2','PUT',{'permissions':['finance']}).status_code,200)

    def test_staff_extra_grants_preserve_account_role_and_do_not_leak_by_default(self):
        for role in ['sales', 'warehouse', 'finance']:
            original=db.get_admin_user_by_email(role+'@gingtto.test')
            self.grant(role, ['finance','contracts'])
            self.assertEqual(self.call('finance/options',role=role).status_code,200)
            self.assertEqual(self.call('contracts',role=role).status_code,200)
            self.assertEqual(self.call('admin-users',role=role).status_code,403)
            self.assertEqual(db.get_admin_user_by_email(role+'@gingtto.test')['role'],original['role'])
            self.grant(role, [])
            self.assertEqual(self.call('finance/options',role=role).status_code,403)
            self.assertEqual(self.call('contracts',role=role).status_code,403)

    def test_omitted_permissions_preserve_explicit_extra_grants(self):
        self.grant('finance',['finance','contracts','presale'])
        user=db.get_admin_user_by_email('finance@gingtto.test')
        updated=self.call(f"admin-users/{user['id']}",'PUT',{'name':'Renamed finance'})
        self.assertEqual(updated.status_code,200,updated.json)
        self.assertEqual(updated.json['user']['permissions'],['presale','contracts','finance'])
        # Explicit empty is still revocation, never restoration of defaults.
        self.grant('finance',[])
        self.assertEqual(self.call('contracts',role='finance').status_code,403)

    def test_explicit_account_management_grant_is_not_implicit_or_self_selected(self):
        self.assertEqual(self.call('admin-users',role='finance').status_code,403)
        self.assertEqual(self.call('admin-users/1','PUT',{'permissions':['finance','admin-users']},role='finance').status_code,403)
        self.grant('finance',['finance','admin-users'])
        self.assertEqual(self.call('admin-users',role='finance').status_code,200)
        sales=db.get_admin_user_by_email('sales@gingtto.test')
        changed=self.call(f"admin-users/{sales['id']}",'PUT',{'permissions':['contracts']},role='finance')
        self.assertEqual(changed.status_code,200,changed.json)
        self.assertEqual(changed.json['user']['role'],'sales')

    def test_finance_default_contract_workflow_keeps_stock_and_audit(self):
        from test_contracts import ContractsTest
        from unittest.mock import patch
        from PIL import Image
        from io import BytesIO
        before=db._fetch_all('SELECT size_code,stock,contract_pending FROM product_size_prices WHERE product_id=1 ORDER BY id')
        payload=ContractsTest.payload(self)
        response=self.call('contracts','POST',payload,role='finance')
        self.assertEqual(response.status_code,200,response.json)
        item=response.json['item'];path=f"contracts/{item['id']}"
        self.assertEqual(self.call(path,role='finance').status_code,200)
        self.assertEqual(self.call('products/1',role='finance').status_code,200)
        self.assertEqual(self.call('catalog-options',role='finance').status_code,200)
        self.assertEqual(self.call('products/1','PUT',{},role='finance').status_code,403)
        after=db._fetch_all('SELECT size_code,stock,contract_pending FROM product_size_prices WHERE product_id=1 ORDER BY id')
        for old,new in zip(before,after):
            self.assertEqual(new['stock'],old['stock'])
            self.assertEqual(new['contract_pending'],old['contract_pending']+payload['items'][0]['quantities'].get(old['size_code'],0))
        photo=BytesIO();Image.new('RGB',(4,4),'white').save(photo,format='JPEG')
        with patch.object(application,'fetch_image_bytes',return_value=photo.getvalue()):
            self.assertEqual(self.call(path+'/export',role='finance').status_code,200)
        edited={**payload,'note':'Finance update','revision':item['revision']}
        updated=self.call(path,'PUT',edited,role='finance')
        self.assertEqual(updated.status_code,200,updated.json)
        cancelled=self.call(path+'/cancel','POST',{'revision':updated.json['item']['revision']},role='finance')
        self.assertEqual(cancelled.status_code,200,cancelled.json)
        self.assertEqual(db._fetch_all('SELECT size_code,stock,contract_pending FROM product_size_prices WHERE product_id=1 ORDER BY id'),before)
        logs=db._fetch_all("SELECT actor FROM admin_audit_logs WHERE module='contracts'")
        self.assertTrue(logs)
        self.assertTrue(all(row['actor']['role']=='finance' for row in logs))


if __name__ == '__main__': unittest.main()
