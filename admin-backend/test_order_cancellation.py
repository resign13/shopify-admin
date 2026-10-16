"""Cancellation notes and inventory integrity: guarded local *_test database only."""
import copy
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import patch
from openpyxl import load_workbook
from werkzeug.security import generate_password_hash
import test_orders as existing
from test_workbench import db
import order_cancellation


class CancellationTest(unittest.TestCase):
    setUp = existing.AdminOrdersTest.setUp
    call = existing.AdminOrdersTest.call
    payload = existing.AdminOrdersTest.payload
    create = existing.AdminOrdersTest.create
    stock = existing.AdminOrdersTest.stock

    def detail(self, oid, role='admin'):
        r = self.call(f'orders/{oid}', role=role)
        self.assertEqual(r.status_code, 200, r.json)
        return r.json['order']

    def update(self, order, **fields):
        r = self.call(f"orders/{order['id']}", 'PUT', {'version': order['version'], **fields})
        self.assertEqual(r.status_code, 200, r.json)
        return r.json['order']

    def history(self, oid):
        return self.call(f'orders/{oid}/operations').json['items']

    def test_cancel_note_is_separate_preserves_money_and_is_visible_on_list(self):
        order = self.create()
        db._fetch_one("UPDATE orders SET note='Packing note',payment_link='https://pay.fixture',tracking_no='TRACK' WHERE id=%s RETURNING id", (order['id'],))
        order = self.detail(order['id'])
        note = '客户调整计划\n<svg onload=alert(1)>仅文字'
        result = self.update(order, status='cancelled', cancelNote=note)
        self.assertEqual(result['cancelNote'], note)
        self.assertEqual(result['note'], 'Packing note')
        for key in ('totalAmount', 'shippingFee', 'paymentLink', 'trackingNo'):
            self.assertEqual(result[key], order[key], key)
        # Cancellation returns stock, so only the live stock field should differ.
        self.assertEqual([{k:v for k,v in r.items() if k!='currentStock'} for r in result['items']],
                         [{k:v for k,v in r.items() if k!='currentStock'} for r in order['items']])
        self.assertEqual(self.stock()['stock'], 30)
        rows = self.call('orders?status=cancelled').json['items']
        self.assertEqual(next(r for r in rows if r['id'] == order['id'])['cancelNote'], note)
        event = self.history(order['id'])[0]
        self.assertEqual(event['action'], 'cancel')
        self.assertIn({'field':'cancelNote','before':'','after':note}, event['changes'])

    def test_note_only_fill_edit_clear_does_not_touch_inventory_or_other_business(self):
        order = self.update(self.create(), status='cancelled')
        db._fetch_one("INSERT INTO order_warehouse_prints(order_id,printed_by_admin_id,printed_by_name,export_kind) VALUES(%s,3,'仓库','export') RETURNING order_id",(order['id'],))
        order = self.detail(order['id'])
        marks = db._fetch_all('SELECT * FROM order_warehouse_prints ORDER BY order_id')
        notifications = db._fetch_all('SELECT * FROM order_created_events ORDER BY id')
        before_stock = self.stock()
        for value in ('首次补填', '更正\n第二行', ''):
            previous = copy.deepcopy(order)
            order = self.update(order, cancelNote=value)
            self.assertEqual(order['cancelNote'], value)
            for key in previous.keys() - {'cancelNote', 'version', 'updatedAt'}:
                self.assertEqual(order[key], previous[key], key)
            self.assertEqual(self.stock(), before_stock)
            self.assertEqual(db._fetch_all('SELECT * FROM order_warehouse_prints ORDER BY order_id'),marks)
            self.assertEqual(db._fetch_all('SELECT * FROM order_created_events ORDER BY id'),notifications)
            self.assertEqual([r['field'] for r in self.history(order['id'])[0]['changes']], ['cancelNote'])
        count = len(self.history(order['id']))
        same = self.update(order, cancelNote='')
        self.assertEqual(same['version'], order['version'])
        self.assertEqual(len(self.history(order['id'])), count)

    def test_restore_clears_current_note_but_keeps_audit_and_recancel_is_blank(self):
        order = self.update(self.create(), status='cancelled', cancelNote='原取消原因')
        restored = self.update(order, status='paid')
        self.assertEqual(restored['cancelNote'], '')
        self.assertEqual(self.stock()['stock'], 25)
        self.assertTrue(any(c['field']=='cancelNote' and c['before']=='原取消原因' and c['after']==''
                            for c in self.history(order['id'])[0]['changes']))
        order = self.update(restored, status='cancelled')
        self.assertEqual(order['cancelNote'], '')
        self.assertEqual(self.stock()['stock'], 30)
        self.assertTrue(any(c.get('after')=='原取消原因' for e in self.history(order['id']) for c in e['changes']))

    def test_validation_and_note_only_on_active_order_have_no_side_effects(self):
        order = self.create(); balance = self.stock()
        for note in (None, 1, True, [], {}, '中'*501, 'nul\x00', '\ud800'):
            with self.subTest(note=type(note)):
                r = self.call(f"orders/{order['id']}", 'PUT', {'status':'cancelled', 'version':order['version'], 'cancelNote':note})
                self.assertEqual(r.status_code, 400, r.json)
                self.assertEqual(self.detail(order['id']), order)
                self.assertEqual(self.stock(), balance)
        for body in ({'cancelNote':'active','version':order['version']}, {'status':'cancelled','cancelNote':'no version'}):
            self.assertEqual(self.call(f"orders/{order['id']}", 'PUT', body).status_code, 400)
        result = self.update(order, status='cancelled', cancelNote='中'*500)
        self.assertEqual(len(result['cancelNote']), 500)

    def test_cancel_note_not_carried_by_drafts_or_new_orders(self):
        order = self.update(self.create(), status='cancelled', cancelNote='internal-only')
        body = self.payload(); body['sourceOrderId'] = order['id']; body['cancelNote'] = 'not copied'
        result = self.call('orders/drafts','POST', {'draftKey':str(uuid.uuid4()),'draft':body})
        self.assertEqual(result.status_code,200,result.json)
        draft = self.call(f"orders/drafts/{result.json['id']}").json['draft']
        self.assertNotIn('cancelNote',draft)
        self.assertNotIn('internal-only',str(draft))
        self.assertEqual(self.call('orders','POST',body).status_code,400)
        self.assertEqual(self.detail(order['id'])['cancelNote'],'internal-only')

    def test_full_editor_cancellation_and_restore_use_same_note_rules(self):
        order = self.create(); order.update(status='cancelled', cancelNote='编辑器取消', note='普通备注')
        r = self.call(f"orders/{order['id']}/details", 'PUT', order)
        self.assertEqual(r.status_code, 200, r.json)
        result = self.detail(order['id'])
        self.assertEqual((result['cancelNote'], result['note']), ('编辑器取消', '普通备注'))
        self.assertEqual(self.stock()['stock'], 30)
        # Full editor echoes the saved reason while changing status; restoration clears it.
        result['status'] = 'pending_payment'
        r = self.call(f"orders/{order['id']}/details", 'PUT', result)
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(self.detail(order['id'])['cancelNote'], '')
        self.assertEqual(self.stock()['stock'], 25)

    def test_concurrent_cancel_and_stale_note_only_save_do_not_double_return_stock(self):
        order = self.create()
        body = {'version':order['version'], 'status':'cancelled', 'cancelNote':'并发取消'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _:self.call(f"orders/{order['id']}", 'PUT', body), range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [200,409])
        self.assertEqual(self.stock()['stock'], 30)
        cancelled = self.detail(order['id'])
        # Legacy repeated status transition also does not return inventory again.
        self.assertEqual(self.call(f"orders/{order['id']}", 'PUT', {'status':'cancelled'}).status_code, 200)
        self.assertEqual(self.detail(order['id'])['cancelNote'], '并发取消')
        self.assertEqual(self.stock()['stock'], 30)
        r = self.call(f"orders/{order['id']}", 'PUT', {'version':cancelled['version'], 'cancelNote':'过期改写'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.detail(order['id'])['cancelNote'], '并发取消')

    def test_inventory_failure_rolls_back_status_note_and_audit(self):
        order = self.create(); stock = self.stock(); history = self.history(order['id'])
        from test_workbench import application
        original = db.inventory_policy.return_order_stock
        def fail(cur, ids):
            original(cur, ids)
            raise ValueError('fixture rollback after inventory update')
        with patch.object(application.inventory_policy, 'return_order_stock', side_effect=fail):
            r = self.call(f"orders/{order['id']}", 'PUT', {'status':'cancelled','version':order['version'],'cancelNote':'失败不能落库'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.detail(order['id']), order)
        self.assertEqual(self.stock(), stock)
        self.assertEqual(self.history(order['id']), history)

    def test_sales_ownership_module_and_warehouse_visibility(self):
        r = self.call('orders','POST',self.payload(),role='sales')
        self.assertEqual(r.status_code,200,r.json)
        own = self.detail(r.json['order']['id'], 'sales')
        r = self.call(f"orders/{own['id']}",'PUT',{'status':'cancelled','version':own['version'],'cancelNote':'本人订单'},role='sales')
        self.assertEqual(r.status_code,200,r.json)
        own = r.json['order']
        other = self.create()
        for path, method, body in ((f"orders/{other['id']}",'GET',None),
                (f"orders/{other['id']}",'PUT',{'status':'cancelled','version':other['version'],'cancelNote':'越权'})):
            self.assertEqual(self.call(path,method,body,role='sales').status_code,404)
        warehouse = self.detail(own['id'],'warehouse')
        self.assertEqual(warehouse['cancelNote'],'本人订单'); self.assertNotIn('totalAmount',warehouse)
        r = self.call(f"orders/{own['id']}",'PUT',{'version':own['version'],'cancelNote':'仓库补充'},role='warehouse')
        self.assertEqual(r.status_code,200,r.json); self.assertNotIn('totalAmount',r.json['order'])
        self.assertEqual(self.call(f"orders/{own['id']}",'PUT',{'version':r.json['order']['version'],'cancelNote':'客户'},role='customer').status_code,403)
        db._fetch_one("UPDATE admin_users SET permissions='[]' WHERE role='warehouse' RETURNING id")
        self.assertEqual(self.call(f"orders/{own['id']}",role='warehouse').status_code,403)

    def test_finance_requires_explicit_order_permission(self):
        user = db.create_admin_user({'name':'财务','email':'cancel-finance@test.fixture','role':'finance',
            'status':'active','passwordHash':generate_password_hash('Fixture-2026',method='pbkdf2:sha256:1000'), 'permissions':['finance']})
        self.tokens['finance'] = db.create_admin_session(user['id'])
        order = self.update(self.create(), status='cancelled', cancelNote='财务可见性')
        self.assertEqual(self.call(f"orders/{order['id']}",role='finance').status_code,403)
        db._fetch_one("UPDATE admin_users SET permissions='[\"finance\",\"orders\"]' WHERE id=%s RETURNING id",(user['id'],))
        self.assertEqual(self.detail(order['id'],'finance')['cancelNote'],'财务可见性')

    def test_reorder_and_customer_exports_do_not_include_internal_cancel_note(self):
        secret = 'INTERNAL-CANCEL-NOTE-ONLY'
        order = self.update(self.create(), status='cancelled', cancelNote=secret)
        draft = self.call(f"orders/{order['id']}/reorder-draft")
        self.assertEqual(draft.status_code,200,draft.json)
        self.assertNotIn(secret, str(draft.json)); self.assertNotIn('cancelNote',draft.json)
        for path in (f"orders/{order['id']}/invoice",f"orders/export?orderIds={order['id']}&includeImages=0"):
            r = self.call(path)
            self.assertEqual(r.status_code,200,r.json)
            book = load_workbook(BytesIO(r.data))
            self.assertNotIn(secret, str([c.value for s in book for row in s for c in row]))
        with db.get_connection() as conn:
            for _ in range(2): order_cancellation.migrate(conn.cursor())
        self.assertEqual(self.detail(order['id'])['cancelNote'], secret)


if __name__ == '__main__': unittest.main()
