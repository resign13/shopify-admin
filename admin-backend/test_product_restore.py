"""Product deletion feedback and restore. Uses only the local *_test database."""
import unittest

from test_workbench import application, db, seed


class ProductRestoreTest(unittest.TestCase):
    def setUp(self):
        self.tokens, self.products = seed()
        application.app.config['TESTING'] = True

    def call(self, path, method='GET', body=None, role='admin'):
        headers = {'Authorization': 'Bearer ' + self.tokens[role]} if role else {}
        with application.app.test_client() as client:
            return client.open('/api/admin/' + path, method=method, json=body, headers=headers)

    def detail(self, product_id):
        response = self.call(f'products/{product_id}')
        self.assertEqual(response.status_code, 200, response.json)
        return response.json['product']

    def deactivate(self, product_id):
        response = self.call(f'products/{product_id}', 'DELETE', {'version': self.detail(product_id)['version']})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['action'], 'hidden')
        return self.detail(product_id)

    def test_delete_then_restore_preserves_orders_prices_inventory_and_audit(self):
        product_id = self.products[0]['id']
        before = self.detail(product_id)
        orders = db._fetch_one('SELECT COUNT(*) AS n FROM order_items WHERE product_id=%s', (product_id,))['n']
        hidden = self.deactivate(product_id)
        self.assertFalse(hidden['isActive'])
        response = self.call(f'products/{product_id}/restore', 'POST', {'version': hidden['version']}, role='sales')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['action'], 'restored')
        after = self.detail(product_id)
        self.assertTrue(after['isActive'])
        for field in ['sku', 'productCode', 'sizePrices', 'gallery', 'stock']:
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM order_items WHERE product_id=%s', (product_id,))['n'], orders)
        active = self.call('products?page=1&status=active').json['items']
        inactive = self.call('products?page=1&status=inactive').json['items']
        self.assertIn(product_id, [item['id'] for item in active])
        self.assertNotIn(product_id, [item['id'] for item in inactive])
        audit = db._fetch_one('''SELECT actor, before_data->>'is_active' AS before_active,
            after_data->>'is_active' AS after_active FROM admin_audit_logs
            WHERE entity_table='products' AND object_id=%s AND module='products'
            ORDER BY id DESC LIMIT 1''', (str(product_id),))
        self.assertEqual((audit['before_active'], audit['after_active']), ('false', 'true'))
        self.assertEqual(audit['actor']['role'], 'sales')
        self.assertEqual(self.call(f'products/{product_id}/restore', 'POST', {'version': hidden['version']}).status_code, 409)
        self.assertEqual(self.call(f'products/{product_id}/restore', 'POST', {'version': after['version']}).status_code, 400)

    def test_unreferenced_product_is_physically_deleted(self):
        product = db.create_product({'categoryKey': 'outerwear', 'productCode': 'DELETE-FIXTURE',
            'sku': 'DELETE-FIXTURE', 'slug': 'delete-fixture', 'title': 'Delete fixture',
            'image': '/uploads/fixture.jpg', 'sizes': ['M'],
            'sizePrices': [{'sizeCode': 'M', 'price': 5, 'stock': 0}]})
        product_id = product['id']
        response = self.call(f'products/{product_id}', 'DELETE', {'version': self.detail(product_id)['version']})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['action'], 'deleted')
        self.assertIsNone(db._fetch_one('SELECT id FROM products WHERE id=%s', (product_id,)))

    def test_restore_requires_authorization_and_current_version(self):
        product_id = self.products[0]['id']
        hidden = self.deactivate(product_id)
        path = f'products/{product_id}/restore'
        self.assertEqual(self.call(path, 'POST', {'version': hidden['version']}, role=None).status_code, 401)
        self.assertEqual(self.call(path, 'POST', {'version': hidden['version']}, role='warehouse').status_code, 403)
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\"]'::jsonb WHERE role='sales' RETURNING id")
        self.assertEqual(self.call(path, 'POST', {'version': hidden['version']}, role='sales').status_code, 403)
        self.assertEqual(self.call(path, 'POST', {}).status_code, 400)
        self.assertEqual(self.call('products/999999/restore', 'POST', {'version': 'missing'}).status_code, 404)
        db._fetch_one('UPDATE products SET updated_at=clock_timestamp() WHERE id=%s RETURNING id', (product_id,))
        self.assertEqual(self.call(path, 'POST', {'version': hidden['version']}).status_code, 409)
        self.assertFalse(self.detail(product_id)['isActive'])

    def test_restore_rejects_inactive_category_or_duplicate_product_code(self):
        product_id = self.products[0]['id']
        hidden = self.deactivate(product_id)
        path = f'products/{product_id}/restore'
        db._fetch_one('UPDATE product_categories SET is_active=FALSE WHERE id=(SELECT category_id FROM products WHERE id=%s) RETURNING id', (product_id,))
        response = self.call(path, 'POST', {'version': hidden['version']})
        self.assertEqual(response.status_code, 400, response.json)
        self.assertIn('分类', response.json['message'])
        db._fetch_one('UPDATE product_categories SET is_active=TRUE WHERE id=(SELECT category_id FROM products WHERE id=%s) RETURNING id', (product_id,))
        db._fetch_one('UPDATE products SET product_code=LOWER(%s) WHERE id=%s RETURNING id',
                      (hidden['productCode'], self.products[1]['id']))
        response = self.call(path, 'POST', {'version': hidden['version']})
        self.assertEqual(response.status_code, 400, response.json)
        self.assertIn('编码', response.json['message'])
        self.assertFalse(self.detail(product_id)['isActive'])


if __name__ == '__main__':
    unittest.main()
