"""Order keyword search and export consistency on guarded isolated fixtures."""
import io
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from test_workbench import seed, application, db


class OrderSearchTest(unittest.TestCase):
    def setUp(self):
        self.tokens, _ = seed()
        application.app.config['TESTING'] = True
        self.b = db.create_admin_user({'name': 'Search Sales B', 'email': 'search-b@fixture.test',
                                      'passwordHash': 'fixture', 'role': 'sales', 'status': 'active'})['id']
        self.tokens['b'] = db.create_admin_session(self.b)
        db._fetch_one("UPDATE products SET product_code='ZM4757',sku='CURRENT-1',style_code='ZM4757' WHERE id=1 RETURNING id")
        # One order matches only the historical item SKU, not the current product.
        db._fetch_one("UPDATE order_items SET product_id=3,sku='ZM4757-历史' WHERE order_id=3 AND product_id=1 RETURNING id")
        # Multiple matching items must not duplicate the order or status counts.
        db._fetch_one("UPDATE order_items SET sku='ZM4757-另一颜色' WHERE order_id=2 AND product_id=2 RETURNING id")
        db._fetch_one('DELETE FROM order_items WHERE order_id=4 AND product_id=1 RETURNING id')
        db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id<>2 RETURNING id')
        db._fetch_one('UPDATE orders SET owner_admin_id=%s WHERE id=2 RETURNING id', (self.b,))
        db._fetch_one("UPDATE orders SET tracking_no='TRACK-ONLY-4' WHERE id=4 RETURNING id")

    def call(self, query, role='admin', route='orders'):
        with application.app.test_client() as client:
            return client.get('/api/admin/' + route + '?' + urlencode(query),
                              headers={'Authorization': 'Bearer ' + self.tokens[role]})

    def ids(self, query, role='admin'):
        response = self.call(query, role)
        self.assertEqual(response.status_code, 200, response.json)
        return {row['id'] for row in response.json['items']}

    def test_style_and_snapshot_search_deduplication_and_pagination(self):
        for keyword in ['ZM4757', 'zm4757', '  Zm4757  ']:
            response = self.call({'page': 1, 'pageSize': 25, 'keyword': keyword})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual({row['id'] for row in response.json['items']}, {1, 2, 3})
            self.assertEqual(response.json['total'], 3)
            self.assertEqual(response.json['statusCounts'], {'paid': 1, 'pending_payment': 1, 'cancelled': 1})
        self.assertEqual(self.ids({'keyword': '历史'}), {3})
        self.assertEqual(self.ids({'keyword': 'CURRENT-1'}), {1, 2})
        extra = db._fetch_all("INSERT INTO orders(order_no,store_user_id,status,contact_name,phone,country,shipping_address,total_amount,shipping_fee) "
                              "SELECT 'SEARCH-'||n,1,'paid','Alex','123','Germany','Fixture',29.9,0 FROM generate_series(5,30) n RETURNING id")
        db._fetch_all("INSERT INTO order_items(order_id,product_id,product_name,sku,size_code,quantity,unit_price,total_price) "
                      "SELECT id,1,'Fixture','ZM4757-分页','M',1,29.9,29.9 FROM orders WHERE order_no LIKE %s RETURNING id", ('SEARCH-%',))
        pages = [self.call({'page': page, 'pageSize': 25, 'keyword': 'ZM4757'}).json for page in range(1, 4)]
        self.assertTrue(all(page['total'] == 29 for page in pages))
        self.assertEqual({row['id'] for page in pages for row in page['items']}, {1, 2, 3, *[row['id'] for row in extra]})
        self.assertEqual([len(page['items']) for page in pages], [25, 4, 0])

    def test_combined_filters_and_status_counts(self):
        base = {'page': 1, 'keyword': 'ZM4757'}
        self.assertEqual(self.ids({**base, 'status': 'paid'}), {1})
        self.assertEqual(self.call({**base, 'status': 'paid'}).json['total'], 1)
        self.assertEqual(sum(self.call({**base, 'status': 'paid'}).json['statusCounts'].values()), 3)
        self.assertEqual(self.ids({**base, 'country': 'Germany', 'category': 'denim'}), {1, 3})
        self.assertEqual(self.ids({**base, 'dateFrom': '2026-09-18', 'dateTo': '2026-09-18'}), {1, 2, 3})
        self.assertEqual(self.ids({**base, 'style': 'ZM4757'}), {1, 2})
        self.assertEqual(self.ids({**base, 'category': 'outerwear'}), set())
        self.assertEqual(self.ids({**base, 'orderIds': '2,4'}), {2})

    def test_owner_scope_and_warehouse_redaction_still_apply(self):
        query = {'page': 1, 'keyword': 'ZM4757', 'salespersonId': self.b, '_ownerId': self.b}
        self.assertEqual(self.ids(query), {2})
        self.assertEqual(self.ids(query, 'sales'), {1, 3})
        self.assertEqual(self.ids(query, 'b'), {2})
        warehouse = self.call({'page': 1, 'keyword': 'ZM4757'}, 'warehouse')
        self.assertEqual(warehouse.json['total'], 3)
        for row in warehouse.json['items']:
            for key in ['goodsAmount', 'totalAmount', 'shippingFee']:
                self.assertNotIn(key, row)
            for item in row['items']:
                self.assertNotIn('unitPrice', item)
                self.assertNotIn('totalPrice', item)
        self.assertEqual(self.call(query, 'customer').status_code, 403)

    def test_both_exports_and_compatibility_routes_share_keyword_filters(self):
        for route, builder in [('orders/export', 'build_orders_export'), ('orders/export-by-sheet', 'build_orders_sheet_export')]:
            for view in ['', 'workbench']:
                for role, expected in [('admin', {1, 2, 3}), ('sales', {1, 3}), ('b', {2}), ('warehouse', {1, 2, 3})]:
                    query = {'keyword': 'zm4757', 'view': view, 'orderIds': '1,2,3,4', 'includeImages': '0'}
                    with patch.object(application, builder, return_value=io.BytesIO(b'fixture')) as mocked:
                        response = self.call(query, role, route)
                        self.assertEqual(response.status_code, 200, response.json)
                        orders = mocked.call_args.args[0]
                        self.assertEqual({row['id'] for row in orders}, expected)
                        self.assertEqual(len(orders), len(expected))
                        if role == 'warehouse': self.assertTrue(all('totalAmount' not in row for row in orders))
                with patch.object(application, builder, return_value=io.BytesIO(b'fixture')) as mocked:
                    self.call({'keyword': 'ZM4757', 'view': view, 'status': 'paid', 'category': 'denim',
                               'dateFrom': '2026-09-18', 'dateTo': '2026-09-18'}, route=route)
                    self.assertEqual([row['id'] for row in mocked.call_args.args[0]], [1])

    def test_existing_keywords_and_empty_or_invalid_matches_do_not_mutate_inventory(self):
        before = db._fetch_all('SELECT * FROM product_size_prices ORDER BY id')
        for keyword, expected in [('GT202609180004', {4}), ('Northline Apparel', {1, 2, 3, 4}),
                                  ('buyer@gingtto.test', {1, 2, 3, 4}), ('Alex Morgan', {1, 2, 3, 4}),
                                  ('TRACK-ONLY-4', {4}), ('NOT-A-STYLE', set()), ("' OR TRUE --", set()),
                                  ('   ', {1, 2, 3, 4})]:
            self.assertEqual(self.ids({'keyword': keyword}), expected)
            self.assertEqual(self.ids({'keyword': keyword, 'page': 1}), expected)
            with patch.object(application, 'build_orders_export', return_value=io.BytesIO(b'fixture')) as mocked:
                self.assertEqual(self.call({'keyword': keyword}, route='orders/export').status_code, 200)
                self.assertEqual({row['id'] for row in mocked.call_args.args[0]}, expected)
        self.assertEqual(db._fetch_all('SELECT * FROM product_size_prices ORDER BY id'), before)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM inventory_receipts')['n'], 0)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM admin_audit_logs')['n'], 0)


if __name__ == '__main__':
    unittest.main()
