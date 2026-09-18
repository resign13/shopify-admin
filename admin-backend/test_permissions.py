"""Explicit module grants, role limits and account recovery protections."""
import unittest
from test_workbench import seed, application, db
from module_permissions import DEFAULTS


class ModulePermissionsTest(unittest.TestCase):
    def setUp(self):
        self.tokens, _ = seed()
        application.app.config['TESTING'] = True

    def call(self, path, method='GET', body=None, role='admin'):
        with application.app.test_client() as client:
            return client.open('/api/admin/' + path, method=method, json=body,
                               headers={'Authorization': 'Bearer ' + self.tokens[role]})

    def grant(self, role, permissions):
        user = db.get_admin_user_by_email(role + '@gingtto.test')
        response = self.call(f"admin-users/{user['id']}", 'PUT', {'permissions': permissions})
        self.assertEqual(response.status_code, 200, response.json)
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
        self.assertEqual(self.call('admin-users/2', 'PUT', {'permissions': ['admin-users']}).status_code, 400)
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

    def test_module_dependencies_and_scoped_activity_updates(self):
        config = self.call('home-config').json['config']
        for key in config['heroBanners']:
            config['heroBanners'][key] = '/uploads/fixture.jpg'
        response = self.call('home-config', 'PUT', config)
        self.assertEqual(response.status_code, 200, response.json)
        self.grant('sales', ['activity-zone/apply'])
        self.assertEqual(self.call('products?page=1', role='sales').status_code, 200)
        self.assertEqual(self.call('products/1', 'DELETE', role='sales').status_code, 403)
        self.assertEqual(self.call('home-config', role='sales').status_code, 403)
        config = self.call('activity-config', role='sales').json['config']
        self.assertEqual(self.call('activity-config', 'PUT', config, role='sales').status_code, 400)
        body = {'version': config['version'], 'collectionProductIds': {key: [1] for key in config['collectionProductIds']}}
        response = self.call('activity-config', 'PUT', body, role='sales')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['config']['heroBanners'], config['heroBanners'])
        self.assertEqual(self.call('activity-config', 'PUT', body, role='sales').status_code, 409)
        self.grant('sales', ['home-config'])
        config = self.call('home-config', role='sales').json['config']
        config['collectionProductIds'] = {key: [] for key in config['collectionProductIds']}
        self.assertEqual(self.call('home-config', 'PUT', config, role='sales').status_code, 403)
        self.grant('sales', ['orders'])
        self.assertEqual(self.call('orders/customers?page=1', role='sales').status_code, 200)
        self.assertEqual(self.call('products/1', role='sales').status_code, 200)
        self.assertEqual(self.call('products/batch', 'POST', {}, role='sales').status_code, 403)


if __name__ == '__main__':
    unittest.main()
