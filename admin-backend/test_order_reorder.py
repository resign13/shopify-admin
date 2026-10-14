"""Reorders use only the guarded local *_test database from test_workbench."""
import copy
import json
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_orders as helpers
from test_workbench import db, fixture_file


class ReorderTest(unittest.TestCase):
    setUp = helpers.AdminOrdersTest.setUp
    call = helpers.AdminOrdersTest.call
    payload = helpers.AdminOrdersTest.payload
    create = helpers.AdminOrdersTest.create
    stock = helpers.AdminOrdersTest.stock

    def draft(self, oid):
        response = self.call(f'orders/{oid}/reorder-draft')
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def body(self, oid):
        result = self.draft(oid)
        return {**result['draft'], 'sourceOrderId': oid, 'requestId': str(uuid.uuid4()), 'ownerConfirmed': True}

    def counts(self):
        return {table: db._fetch_one(f'SELECT COUNT(*) AS n FROM {table}')['n']
                for table in ['orders', 'admin_order_requests', 'admin_audit_logs', 'order_created_events']}

    def test_readonly_draft_copies_whitelist_current_prices_and_full_attachments(self):
        source = self.create(); oid = source['id']
        files = [fixture_file(f'/uploads/legacy-{n}.pdf','order',oid) for n in range(18)] + [fixture_file('/uploads/photo.jpg','order',oid)]
        db._fetch_one('UPDATE orders SET note=%s,label_image_urls=%s,tracking_no=%s,payment_link=%s,status=%s WHERE id=%s RETURNING id',
                      ('辅料\nPacking instructions', json.dumps(files), 'OLD-TRACK', 'https://old.test/pay', 'completed', oid))
        before = self.counts(); stock = self.stock()
        result = self.draft(oid); body = result['draft']
        self.assertEqual(self.counts(), before); self.assertEqual(self.stock(), stock)
        self.assertEqual(body['note'], '辅料\nPacking instructions')
        self.assertEqual(body['shippingFee'], 12.5)
        self.assertEqual(body['inheritedAttachmentUrls'], files)
        self.assertEqual(body['items'][0]['unitPrice'], 29.9)
        self.assertEqual(body['items'][0]['oldUnitPrices'], [20])
        self.assertEqual(body['items'][0]['quantity'], 2)
        for key in ['status', 'trackingNo', 'paymentLink', 'version', 'requestId', 'createdAt']:
            self.assertNotIn(key, body)

    def test_create_independent_pending_order_and_replay_once(self):
        source = self.create(); oid = source['id']; before = self.call(f'orders/{oid}').json['order']
        body = self.body(oid); initial = self.stock(); counts = self.counts()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call('orders', 'POST', body), range(2)))
        self.assertEqual([r.status_code for r in results], [200, 200], [r.json for r in results])
        self.assertEqual(sum(r.json['replayed'] for r in results), 1)
        new = results[0].json['order']; self.assertNotEqual(new['id'], oid)
        self.assertEqual(new['status'], 'pending_payment'); self.assertEqual(new['trackingNo'], '')
        self.assertEqual(new['totalAmount'], 162); self.assertEqual(new['shippingFee'], 12.5)
        self.assertEqual(self.call(f'orders/{oid}').json['order'], before)
        self.assertEqual(self.stock()['stock'], initial['stock'] - 5)
        for old, now in zip(initial['sizePrices'], self.stock()['sizePrices']):
            for key in ['contractPending','pendingInspection','pendingInbound','defectivePending','temporaryInbound']:
                self.assertEqual(old[key], now[key])
        self.assertEqual(self.counts()['order_created_events'], counts['order_created_events'] + 1)
        self.assertEqual(self.call(f"orders/{new['id']}/operations").json['total'], 0)
        audit = db._fetch_one("SELECT after_data FROM admin_audit_logs WHERE action='REORDER' AND object_id=%s", (str(new['id']),))
        self.assertEqual(audit['after_data']['sourceOrderId'], oid)

    def test_price_change_conflict_rolls_back_and_reconfirmation_succeeds(self):
        oid = self.create()['id']; body = self.body(oid); before = self.counts(); stock = self.stock()['stock']
        db._fetch_one("UPDATE product_size_prices SET price=35 WHERE product_id=1 AND size_code='M' RETURNING id")
        result = self.call('orders', 'POST', body)
        self.assertEqual(result.status_code, 409, result.json)
        self.assertEqual(result.json['code'], 'reorder_price_changed')
        self.assertEqual(result.json['changes'][0]['unitPrice'], 35)
        self.assertEqual(self.counts(), before); self.assertEqual(self.stock()['stock'], stock)
        body['items'][0]['unitPrice'] = 35
        self.assertEqual(self.call('orders', 'POST', body).status_code, 200)

    def test_added_lines_also_use_current_prices(self):
        body = self.body(self.create()['id'])
        body['items'].append({'productId':2,'sizeCode':'M','quantity':1,'unitPrice':1})
        response = self.call('orders','POST',body)
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json['changes'][0]['productId'],2)

    def test_all_source_statuses_supported(self):
        oid = self.create()['id']
        for status in ['pending_payment','allocated','paid','shipped','completed','cancelled']:
            db._fetch_one('UPDATE orders SET status=%s WHERE id=%s RETURNING id',(status,oid))
            response = self.call('orders','POST',self.body(oid))
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['order']['status'],'pending_payment')
            self.assertEqual(self.call(f'orders/{oid}').json['order']['status'],status)

    def test_attachments_independent_complete_and_membership_checked(self):
        oid = self.create()['id']; files = [fixture_file(f'/uploads/{n}.pdf','order',oid) for n in range(19)] + [fixture_file('/uploads/legacy.doc','order',oid)]
        db._fetch_one('UPDATE orders SET label_image_urls=%s WHERE id=%s RETURNING id',(json.dumps(files),oid))
        bad = self.body(oid); bad['labelPdfUrl'] = '/uploads/extra.pdf'
        self.assertEqual(self.call('orders','POST',bad).status_code,400)
        body = self.body(oid); body['inheritedAttachmentUrls'].pop(0)
        body['labelImageUrls'] = [fixture_file('/uploads/new.jpg')]; body['labelPdfUrl'] = ''
        response = self.call('orders','POST',body); self.assertEqual(response.status_code,200,response.json)
        copied = response.json['order']; expected = files[1:] + [fixture_file('/uploads/new.jpg')]
        self.assertEqual(copied['labelImageUrls'],expected)
        self.assertEqual(self.call(f'orders/{oid}').json['order']['labelImageUrls'],files)
        # Future edits must also preserve all historical files rather than truncating.
        edit = self.call(f"orders/{copied['id']}").json['order']
        edit.update(inheritedAttachmentUrls=expected[:-1],labelImageUrls=[],labelPdfUrl='')
        updated = self.call(f"orders/{copied['id']}/details",'PUT',edit)
        self.assertEqual(updated.status_code,200,updated.json)
        self.assertEqual(updated.json['order']['labelImageUrls'],expected[:-1])
        bad = self.body(oid); bad['inheritedAttachmentUrls'].append('/uploads/not-from-source.pdf')
        self.assertEqual(self.call('orders','POST',bad).status_code,400)
        bad = self.payload(); bad['inheritedAttachmentUrls'] = [files[0]]
        self.assertEqual(self.call('orders','POST',bad).status_code,400)

    def test_legacy_image_limit_preserves_history_and_limits_new_uploads(self):
        oid = self.create()['id']; files = [fixture_file(f'/uploads/{n}.jpg','order',oid) for n in range(12)]
        db._fetch_one('UPDATE orders SET label_image_urls=%s WHERE id=%s RETURNING id',(json.dumps(files),oid))
        response = self.call('orders','POST',self.body(oid))
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['order']['labelImageUrls'],files)
        bad = self.body(oid); bad['labelImageUrls'] = ['/uploads/new.jpg']
        self.assertEqual(self.call('orders','POST',bad).status_code,400)

    def test_unavailable_items_retained_as_issues_and_duplicates_merged(self):
        oid = self.create()['id']
        db._fetch_one("INSERT INTO order_items(order_id,product_id,product_name,sku,size_code,quantity,unit_price,total_price) VALUES(%s,1,'Fixture','GT-2026-1','M',1,22,22) RETURNING id",(oid,))
        result = self.draft(oid)
        self.assertEqual(result['draft']['items'][0]['quantity'],3)
        self.assertEqual(result['draft']['items'][0]['oldUnitPrices'],[20,22])
        db._fetch_one("UPDATE order_items SET size_code='' WHERE order_id=%s AND size_code='L' RETURNING id",(oid,))
        result = self.draft(oid); self.assertEqual(result['issues'][0]['reason'],'原订单未指定尺码')
        db._fetch_one("DELETE FROM product_size_prices WHERE product_id=1 AND size_code='M' RETURNING id")
        self.assertEqual(len(self.draft(oid)['issues']),2)
        db._fetch_one('UPDATE products SET is_active=FALSE WHERE id=1 RETURNING id')
        self.assertTrue(all(i['reason']=='商品已下架' for i in self.draft(oid)['issues']))

    def test_customer_owner_and_submit_revalidation(self):
        oid = self.create()['id']
        db._fetch_one("UPDATE orders SET owner_admin_id=2 WHERE id=%s RETURNING id",(oid,))
        db._fetch_one("UPDATE admin_users SET status='disabled' WHERE id=2 RETURNING id")
        result = self.draft(oid); self.assertTrue(result['ownerNeedsConfirmation'])
        body = self.body(oid); body['ownerConfirmed'] = False
        self.assertEqual(self.call('orders','POST',body).status_code,400)
        body['ownerConfirmed'] = True
        self.assertEqual(self.call('orders','POST',body).status_code,200)
        db._fetch_one("UPDATE store_users SET status='disabled' WHERE id=1 RETURNING id")
        self.assertTrue(self.draft(oid)['customerUnavailable'])
        self.assertIsNone(self.draft(oid)['draft']['userId'])
        body['requestId'] = str(uuid.uuid4())
        self.assertEqual(self.call('orders','POST',body).status_code,400)

    def test_roles_scope_and_revocation(self):
        oid = self.create()['id']; body = self.body(oid)
        for role in ['warehouse','customer']:
            self.assertEqual(self.call(f'orders/{oid}/reorder-draft',role=role).status_code,403)
            self.assertEqual(self.call('orders','POST',body,role).status_code,403)
        self.assertEqual(self.call(f'orders/{oid}/reorder-draft',role='sales').status_code,404)
        self.assertEqual(self.call('orders','POST',body,'sales').status_code,404)
        db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id=%s RETURNING id',(oid,))
        result = self.call(f'orders/{oid}/reorder-draft',role='sales')
        self.assertEqual(result.status_code,200)
        body = {**result.json['draft'],'requestId':str(uuid.uuid4()),'sourceOrderId':oid}
        self.assertEqual(self.call('orders','POST',body,'sales').status_code,200)
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE id=2 RETURNING id")
        self.assertEqual(self.call(f'orders/{oid}/reorder-draft',role='sales').status_code,403)
        self.assertEqual(self.call('orders','POST',body,'sales').status_code,403)

    def test_audit_failure_rolls_back_order_stock_receipt_and_event(self):
        oid = self.create()['id']; body = self.body(oid); before = self.counts(); stock = self.stock()
        with patch('order_reorder.audit',side_effect=ValueError('fixture audit failure')):
            result = self.call('orders','POST',body)
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.counts(),before); self.assertEqual(self.stock(),stock)
        self.assertEqual(self.call('orders','POST',body).status_code,200)

    def test_deleted_source_and_current_product_rechecked(self):
        oid = self.create()['id']; body = self.body(oid)
        db._fetch_one('UPDATE products SET is_active=FALSE WHERE id=1 RETURNING id')
        self.assertEqual(self.call('orders','POST',body).status_code,400)
        db._fetch_one('DELETE FROM orders WHERE id=%s RETURNING id',(oid,))
        self.assertEqual(self.call('orders','POST',body).status_code,404)


if __name__ == '__main__':
    unittest.main()
