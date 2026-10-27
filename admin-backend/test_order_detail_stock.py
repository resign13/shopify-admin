"""Live order detail balances; fixtures are guarded by the shared local *_test DB."""
import copy
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
import test_orders as helpers
from test_workbench import db


class OrderDetailStockTest(unittest.TestCase):
    setUp = helpers.AdminOrdersTest.setUp
    call = helpers.AdminOrdersTest.call
    payload = helpers.AdminOrdersTest.payload
    create = helpers.AdminOrdersTest.create

    def detail(self, oid, role='admin'):
        r = self.call(f'orders/{oid}',role=role)
        self.assertEqual(r.status_code,200,r.json)
        return r.json['order']

    def set_stock(self, pid, size, stock):
        db._fetch_one('UPDATE product_size_prices SET stock=%s WHERE product_id=%s AND size_code=%s RETURNING id',(stock,pid,size))

    def balances(self):
        return {(r['product_id'],r['size_code']):r['stock'] for r in db._fetch_all('SELECT product_id,size_code,stock FROM product_size_prices')}

    def assert_balances(self, order):
        stocks = self.balances()
        for line in order['items']:
            self.assertIn('currentStock',line)
            self.assertEqual(line['currentStock'],stocks.get((line['productId'],line['sizeCode'])))

    def business(self):
        return {t:db._fetch_all(f'SELECT to_jsonb(t) AS value FROM {t} t ORDER BY to_jsonb(t)::text') for t in
                ['orders','order_items','products','product_size_prices','admin_audit_logs','order_warehouse_prints','order_created_events']}

    def test_exact_color_and_real_size_signed_stock_and_zero_not_product_total(self):
        self.set_stock(1,'M',-5); self.set_stock(1,'L',0); self.set_stock(2,'M',37)
        db._fetch_one('UPDATE products SET stock=99999 WHERE id=1 RETURNING id')
        self.assert_balances(self.detail(1))
        items = self.detail(1)['items']
        self.assertEqual({r['productId']:r['currentStock'] for r in items},{1:-5,2:37})
        db._fetch_one("UPDATE order_items SET size_code='L' WHERE order_id=1 AND product_id=1 RETURNING id")
        self.assertEqual(self.detail(1)['items'][0]['currentStock'],0)
        self.assertEqual(self.detail(1)['items'][0]['quantity'],2)

    def test_read_and_refresh_do_not_change_business_or_order_version(self):
        order = self.detail(1); before = self.business()
        for _ in range(3): self.assertEqual(self.detail(1),order)
        self.assertEqual(self.business(),before)
        self.set_stock(1,'M',-17)
        current = self.detail(1)
        self.assertEqual(current['items'][0]['currentStock'],-17)
        self.assertEqual(current['version'],order['version'])
        self.assertEqual(current['items'][0]['quantity'],order['items'][0]['quantity'])

    def test_all_states_display_actual_balance_without_another_subtraction_or_return(self):
        order = self.create()
        for status in ['partially_allocated','allocated','paid','shipped','completed','cancelled','pending_payment']:
            response = self.call(f"orders/{order['id']}",'PUT',{'version':order['version'],'status':status,'trackingNo':'TRACK'})
            self.assertEqual(response.status_code,200,response.json)
            order = response.json['order']; self.assert_balances(order)
            before = self.business()
            current = self.detail(order['id']); self.assert_balances(current)
            self.assertEqual(self.business(),before)

    def test_missing_removed_and_blank_sizes_are_null_not_zero_or_aggregate(self):
        for code in ('Gone size','',None):
            db._fetch_one('UPDATE order_items SET size_code=%s WHERE order_id=1 AND product_id=1 RETURNING id',(code,))
            self.assertIsNone(self.detail(1)['items'][0]['currentStock'])
        db._fetch_one("UPDATE order_items SET size_code='M' WHERE order_id=1 AND product_id=1 RETURNING id")
        db._fetch_one("DELETE FROM product_size_prices WHERE product_id=1 AND size_code='M' RETURNING id")
        self.assertIsNone(self.detail(1)['items'][0]['currentStock'])

    def test_inactive_products_retain_current_size_inventory(self):
        db._fetch_one('UPDATE products SET is_active=FALSE WHERE id=1 RETURNING id')
        self.set_stock(1,'M',-9)
        self.assertEqual(self.detail(1)['items'][0]['currentStock'],-9)

    def test_shared_weight_join_is_batched_and_default_list_and_exports_remain_unchanged(self):
        with patch.object(db,'_fetch_all',wraps=db._fetch_all) as queries:
            result = db.list_orders(order_ids=[1,2],include_weight=True,include_stock=True)
        self.assertEqual(queries.call_count,1)
        sql = queries.call_args.args[0]
        self.assertEqual(sql.count('JOIN product_size_prices'),1)
        for order in result: self.assert_balances(order)
        self.assertTrue(all('currentStock' not in line for order in db.list_orders(include_weight=True) for line in order['items']))
        listing = self.call('orders?page=1&pageSize=25').json['items']
        self.assertTrue(all('currentStock' not in line for order in listing for line in order['items']))

    def test_create_edit_cancel_note_and_replay_responses_have_fresh_readonly_stock(self):
        body = self.payload(); body['items'][0]['currentStock'] = 99999
        r = self.call('orders','POST',body); self.assertEqual(r.status_code,200,r.json)
        order = r.json['order']; self.assert_balances(order)
        replay = self.call('orders','POST',body); self.assertEqual(replay.status_code,200,replay.json)
        self.assertEqual(replay.json['order'],order)
        edit = copy.deepcopy(order); edit['items'][0].update(quantity=4,currentStock=99999)
        r = self.call(f"orders/{order['id']}/details",'PUT',edit)
        self.assertEqual(r.status_code,200,r.json); order = r.json['order']; self.assert_balances(order)
        self.assertEqual(order['items'][0]['currentStock'],6)
        r = self.call(f"orders/{order['id']}",'PUT',{'status':'cancelled','version':order['version'],'cancelNote':'cancel'})
        self.assertEqual(r.status_code,200,r.json); order = r.json['order']; self.assert_balances(order)
        before = self.balances()
        r = self.call(f"orders/{order['id']}",'PUT',{'version':order['version'],'cancelNote':'amended'})
        self.assertEqual(r.status_code,200,r.json); self.assert_balances(r.json['order'])
        self.assertEqual(self.balances(),before)

    def test_order_permission_is_sufficient_without_inventory_and_sales_scope_is_retained(self):
        user = db.create_admin_user({'name':'Order-only finance','email':'stock-finance@fixture.test','role':'finance','status':'active',
            'passwordHash':generate_password_hash('Fixture-Only',method='pbkdf2:sha256:1000'),'permissions':['orders']})
        self.tokens['finance'] = db.create_admin_session(user['id'])
        self.assertEqual(self.call('inventory/1',role='finance').status_code,403)
        self.assert_balances(self.detail(1,'finance'))
        for role in ['admin','warehouse']: self.assert_balances(self.detail(1,role))
        warehouse = self.detail(1,'warehouse')
        self.assertNotIn('totalAmount',warehouse); self.assertNotIn('unitPrice',warehouse['items'][0])
        own = self.call('orders','POST',self.payload(),role='sales').json['order']
        self.assert_balances(self.detail(own['id'],'sales'))
        self.assertEqual(self.call('orders/1',role='sales').status_code,404)
        self.assertEqual(self.call('orders/1',role='customer').status_code,403)
        db._fetch_one("UPDATE admin_users SET permissions='[]' WHERE id=%s RETURNING id",(user['id'],))
        self.assertEqual(self.call('orders/1',role='finance').status_code,403)


if __name__=='__main__':unittest.main()
