"""Notification integration tests are guarded by the shared *_test fixture."""
import os
import subprocess
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import test_workbench as fixtures
import order_notifications as notifications
import order_notification_schema as schema

db = fixtures.db


class OrderNotificationsTest(unittest.TestCase):
    call = fixtures.WorkbenchTest.call

    def setUp(self):
        fixtures.WorkbenchTest.setUp(self)
        self.config = patch.dict(os.environ, {'ORDER_VOICE_ENABLED': '1', 'ORDER_VOICE_CURSOR_SECRET': 'fixture-only-signing-key-not-for-production'})
        self.config.start(); self.addCleanup(self.config.stop)
        db._fetch_one('DELETE FROM order_created_events RETURNING id')

    def start(self, role='admin', request_id=None):
        response = self.call('order-notifications/start', 'POST', {'requestId': request_id or str(uuid.uuid4())}, role=role)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json['cursor']

    def poll(self, cursor, auth_role='admin', **extra):
        return self.call('order-notifications/poll', 'POST', {'cursor': cursor, **extra}, role=auth_role)

    def insert(self, owner=None, **fields):
        return db._fetch_one('INSERT INTO orders(store_user_id,contact_name,phone,shipping_address,order_no,status,owner_admin_id,total_amount) VALUES(1,$$Fixture$$,$$123$$,$$Fixture$$,%s,%s,%s,0) RETURNING id',
                            (fields.get('order_no', 'LM-TEST-' + uuid.uuid4().hex[:20]), fields.get('status', 'paid'), owner))['id']

    def test_default_disabled_and_missing_signing_secret(self):
        with patch.dict(os.environ, {'ORDER_VOICE_ENABLED': '0', 'ORDER_VOICE_CURSOR_SECRET': ''}):
            self.assertFalse(self.call('order-notifications/start','POST',{}).json['enabled'])
            order = self.insert()
            self.assertIsNotNone(db._fetch_one('SELECT id FROM order_created_events WHERE order_id=%s',(order,)))
        with patch.dict(os.environ, {'ORDER_VOICE_CURSOR_SECRET': ''}):
            response = self.call('order-notifications/start','POST',{'requestId':str(uuid.uuid4())})
            self.assertEqual(response.status_code,503)

    def test_baseline_and_idempotent_start(self):
        self.insert()
        request_id = str(uuid.uuid4()); cursor = self.start(request_id=request_id)
        new = self.insert()
        retry = self.start(request_id=request_id)
        result = self.poll(retry).json
        self.assertEqual([e['orderId'] for e in result['events']],[new])
        self.assertEqual(self.poll(cursor).json['events'],result['events'])

    def test_backend_creation_replay_rollback_and_edits(self):
        cursor = self.start()
        body = {'requestId':str(uuid.uuid4()),'userId':1,'contactName':'Fixture','phone':'123','country':'DE','address':'Fixture',
                'items':[{'productId':1,'sizeCode':'M','quantity':1,'unitPrice':29.9}]}
        first = self.call('orders','POST',body); self.assertEqual(first.status_code,200,first.json)
        self.assertEqual(self.call('orders','POST',body).status_code,200)
        order_id = first.json['order']['id']
        before = db._fetch_one('SELECT COUNT(*) AS n FROM order_created_events')['n']
        with db._connect() as conn:
            conn.execute("INSERT INTO orders(store_user_id,contact_name,phone,shipping_address,order_no,status,total_amount) VALUES(1,$$Fixture$$,$$123$$,$$Fixture$$,'LM-ROLLBACK','paid',0)")
            conn.rollback()
        db._fetch_one("UPDATE orders SET status='allocated',owner_admin_id=2 WHERE id=%s RETURNING id", (order_id,))
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM order_created_events')['n'], before)
        events = self.poll(cursor).json['events']; self.assertEqual(len(events),1)
        self.assertTrue(events[0]['orderNo'].startswith('LM-')); self.assertNotIn('TEMP-',str(events))

    def test_commit_inversion_does_not_skip_late_transaction(self):
        cursor = self.start()
        with db._connect() as late:
            a = late.execute("INSERT INTO orders(store_user_id,contact_name,phone,shipping_address,order_no,status,total_amount) VALUES(1,$$Fixture$$,$$123$$,$$Fixture$$,'LM-LATE','paid',0) RETURNING id").fetchone()['id']
            b = self.insert()
            first = self.poll(cursor).json
            self.assertEqual([e['orderId'] for e in first['events']],[b])
            late.commit()
        second = self.poll(first['cursor']).json
        self.assertEqual([e['orderId'] for e in second['events']],[a])

    def test_role_filters_and_minimal_fields(self):
        sales = self.start('sales'); admin = self.start(); warehouse = self.start('warehouse')
        mine = self.insert(2); self.insert(1); self.insert(None)
        self.assertEqual([e['orderId'] for e in self.poll(sales,'sales',ownerId=1,role='admin').json['events']],[mine])
        for cursor, role in [(admin,'admin'),(warehouse,'warehouse')]:
            events = self.poll(cursor,role).json['events']; self.assertEqual(len(events),3)
            self.assertEqual(set(events[0]),{'eventId','orderId','orderNo','createdAt'})
        self.assertEqual(self.call('order-notifications/start','POST',{},role='customer').status_code,403)
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE id=2 RETURNING id")
        self.assertEqual(self.poll(sales,'sales').status_code,403)

    def test_validate_after_cancel_delete_and_reassignment(self):
        cursor = self.start('sales'); a=self.insert(2); b=self.insert(2); c=self.insert(2)
        data=self.poll(cursor,'sales').json
        db._fetch_one("UPDATE orders SET status='cancelled' WHERE id=%s RETURNING id",(a,))
        db._fetch_one('DELETE FROM orders WHERE id=%s RETURNING id',(b,))
        db._fetch_one('UPDATE orders SET owner_admin_id=1 WHERE id=%s RETURNING id',(c,))
        response=self.call('order-notifications/validate','POST',{'cursor':data['cursor'],'eventIds':[e['eventId'] for e in data['events']]},role='sales')
        self.assertEqual(response.json['events'],[])
        self.assertEqual(self.poll(data['cursor'],'sales').json['events'],[])

    def test_scan_pagination_before_permission_filter(self):
        cursor=self.start('sales')
        with db._connect() as conn:
            for i in range(205):
                conn.execute('INSERT INTO orders(store_user_id,contact_name,phone,shipping_address,order_no,status,owner_admin_id,total_amount) VALUES(1,$$Fixture$$,$$123$$,$$Fixture$$,%s,%s,%s,0)',(f'LM-BULK-{i}','paid',2 if i>=100 else 1))
        result=self.poll(cursor,'sales').json
        self.assertEqual(result['events'],[]); self.assertTrue(result['hasMore'])
        second=self.poll(result['cursor'],'sales').json
        self.assertEqual(len(second['events']),100); self.assertTrue(second['hasMore'])
        third=self.poll(second['cursor'],'sales').json
        self.assertEqual(len(third['events']),5); self.assertFalse(third['hasMore'])

    def test_fixed_recovery_boundary_and_ten_minute_recording_time(self):
        cursor=self.start(); old=self.insert()
        db._fetch_one("UPDATE order_created_events SET recorded_at=clock_timestamp()-INTERVAL '11 minutes' WHERE order_id=%s RETURNING id",(old,))
        with db._connect() as conn:
            for i in range(102):
                conn.execute("INSERT INTO orders(store_user_id,contact_name,phone,shipping_address,order_no,status,total_amount,created_at) VALUES(1,$$Fixture$$,$$123$$,$$Fixture$$,%s,'paid',0,'2020-01-01')",(f'LM-REC-{i}',))
        first=self.poll(cursor,recovery=True).json
        self.assertTrue(first['hasMore']); self.assertEqual(len(first['events']),99)
        newer=self.insert()
        second=self.poll(first['cursor'],recovery=True).json
        self.assertTrue(second['recoveryComplete']); self.assertEqual(len(second['events']),3)
        self.assertEqual(second['cutoffAt'],first['cutoffAt'])
        self.assertEqual([e['orderId'] for e in self.poll(second['cursor']).json['events']],[newer])

    def test_cursor_session_tamper_expiry_and_input_validation(self):
        cursor=self.start()
        self.assertEqual(self.poll(cursor,'warehouse').status_code,409)
        self.assertEqual(self.poll(cursor+'bad').status_code,409)
        data=notifications._unpack(cursor,notifications._identity(self.tokens['admin'])); data['t']-=8*86400
        self.assertEqual(self.poll(notifications._pack(data)).status_code,409)
        self.assertEqual(self.call('order-notifications/validate','POST',{'cursor':cursor,'eventIds':[1]*101}).status_code,400)
        db.create_admin_session(1)
        self.assertEqual(self.poll(cursor).status_code,401)

    def test_migration_maintenance_and_cleanup_preserve_sequence(self):
        cursor=self.start(); first=self.insert(); before=self.poll(cursor).json
        with db._connect() as conn:
            schema.migrate(conn.cursor()); schema.migrate(conn.cursor())
        self.assertEqual(self.poll(cursor).json['events'],before['events'])
        with db._connect() as conn:
            conn.execute("SET LOCAL gingtto.notifications_paused='on'")
            conn.execute("INSERT INTO orders(store_user_id,contact_name,phone,shipping_address,order_no,status,total_amount) VALUES(1,$$Fixture$$,$$123$$,$$Fixture$$,'LM-HISTORICAL','paid',0)")
        db._fetch_one("UPDATE order_created_events SET recorded_at=clock_timestamp()-INTERVAL '8 days' WHERE order_id=%s RETURNING id",(first,))
        high=db._fetch_one('SELECT last_sequence FROM order_notification_state')['last_sequence']
        self.assertEqual(notifications.cleanup(),1)
        self.assertEqual(db._fetch_one('SELECT last_sequence FROM order_notification_state')['last_sequence'],high)
        new=self.insert(); self.assertEqual([e['orderId'] for e in self.poll(before['cursor']).json['events']],[new])

    def test_compatibility_and_storefront_creation(self):
        cursor=self.start()
        with self.app.test_client() as client:
            result=client.post('/api/internal/orders',json={'userId':1,'productId':1,'sizeCode':'M','quantity':1,'contactName':'Fixture','phone':'123','shippingAddress':'Fixture'},headers={'X-Service-Token':fixtures.application.SERVICE_TOKEN})
            self.assertIn(result.status_code,(200,201),result.json)
        storefront=Path(__file__).resolve().parents[2]/'shopify/storefront-backend'
        code="""import db; db.ensure_database_ready(); db.create_order({'userId':1,'contactName':'Fixture','phone':'123','country':'DE','shippingAddress':'Fixture','items':[{'productId':2,'sizeCode':'M','quantity':1}]})"""
        if storefront.exists():
            subprocess.run([sys.executable,'-c',code],cwd=storefront,check=True,capture_output=True,env=os.environ.copy())
            self.assertEqual(len(self.poll(cursor).json['events']),2)
        else:
            self.assertEqual(len(self.poll(cursor).json['events']),1) # storefront owns an additional isolated CI suite

    def test_concurrent_start_retry_and_publishers_share_one_progress(self):
        request_id=str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            cursors=list(pool.map(lambda _: self.start(request_id=request_id),range(2)))
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM order_notification_starts')['n'],1)
        self.insert();self.insert()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda c: self.poll(c).json,cursors))
        self.assertEqual(responses[0]['events'],responses[1]['events'])
        self.assertEqual(len(responses[0]['events']),2)
        self.assertEqual(db._fetch_one('SELECT COUNT(DISTINCT publish_sequence) AS n FROM order_created_events')['n'],2)

    def test_notification_requests_are_stock_order_and_audit_neutral(self):
        def snapshot():
            return db._fetch_one('''SELECT
                (SELECT md5(string_agg(row_to_json(o)::text,',' ORDER BY id)) FROM orders o) AS orders,
                (SELECT md5(string_agg(row_to_json(p)::text,',' ORDER BY id)) FROM product_size_prices p) AS stock,
                (SELECT COUNT(*) FROM admin_audit_logs) AS audit''')
        self.insert();before=snapshot();cursor=self.start();self.poll(cursor)
        self.call('order-notifications/validate','POST',{'cursor':cursor,'eventIds':[]})
        self.assertEqual(snapshot(),before)


if __name__ == '__main__': unittest.main()
