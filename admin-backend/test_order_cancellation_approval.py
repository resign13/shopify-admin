import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
import test_orders as helpers
from test_workbench import db
import order_cancel_policy as policy


class CancellationApprovalTest(unittest.TestCase):
    setUp=helpers.AdminOrdersTest.setUp
    call=helpers.AdminOrdersTest.call
    payload=helpers.AdminOrdersTest.payload
    create=helpers.AdminOrdersTest.create
    stock=helpers.AdminOrdersTest.stock

    def detail(self,oid):
        return self.call(f'orders/{oid}').json['order']

    def stage(self,order,status):
        r=self.call(f'orders/{order["id"]}','PUT',{'version':order['version'],'status':status,'trackingNo':'TRACK'})
        self.assertEqual(r.status_code,200,r.json)
        return r.json['order']

    def submit(self,order):
        r=self.call(f'orders/{order["id"]}/cancellation-requests','POST',{'version':order['version'],'reason':'客户调整订单'})
        self.assertEqual(r.status_code,200,r.json)
        return r.json['item']

    def decision(self,item,action='approve',role='admin'):
        return self.call(f'orders/cancellation-requests/{item["id"]}/{action}','POST',{'version':item['version'],'reviewNote':'核对完成'},role)

    def test_status_direction_and_direct_cancel_restore(self):
        order=self.stage(self.create(),'partially_allocated')
        order=self.stage(order,'pending_payment')
        order=self.stage(order,'partially_allocated')
        order=self.stage(order,'cancelled')
        self.assertEqual(order['cancelledFromStatus'],'partially_allocated')
        self.assertEqual(self.call(f'orders/{order["id"]}','PUT',{'version':order['version'],'status':'pending_payment'}).status_code,400)
        order=self.stage(order,'partially_allocated')
        for status in ['paid','allocated','shipped','completed']:
            order=self.stage(order,status)
            stock=self.stock()
            for prior in policy.STAGES[:policy.STAGES.index(status)]:
                r=self.call(f'orders/{order["id"]}','PUT',{'version':order['version'],'status':prior})
                self.assertEqual(r.status_code,400,(status,prior,r.json))
            self.assertEqual(self.stock(),stock)

    def test_protected_cancellation_requires_review_and_restores_only_original(self):
        for status in ['allocated','paid','shipped','completed']:
            with self.subTest(status=status):
                order=self.stage(self.create(),status)
                before=self.stock()['stock']
                denied=self.call(f'orders/{order["id"]}','PUT',{'version':order['version'],'status':'cancelled','cancelNote':'direct'})
                self.assertEqual(denied.status_code,409,denied.json)
                item=self.submit(order)
                self.assertEqual(self.detail(order['id'])['status'],status)
                self.assertEqual(self.stock()['stock'],before)
                r=self.decision(item)
                self.assertEqual(r.status_code,200,r.json)
                cancelled=self.detail(order['id'])
                self.assertEqual(cancelled['status'],'cancelled')
                self.assertEqual(cancelled['cancelledFromStatus'],status)
                self.assertEqual(cancelled['totalAmount'],order['totalAmount'])
                self.assertEqual(self.stock()['stock'],before+5)
                self.assertEqual(self.decision(item).status_code,409)
                self.stage(cancelled,status)
                self.assertEqual(self.stock()['stock'],before)

    def test_paid_can_advance_to_partial_or_allocated_without_inventory_change(self):
        partial=self.stage(self.create(),'paid');before=self.stock()['stock']
        self.assertEqual(self.call(f'orders/{partial["id"]}','PUT',{'version':partial['version'],'status':'cancelled'}).status_code,409)
        partial=self.stage(partial,'partially_allocated')
        self.assertEqual(self.stock()['stock'],before)
        self.assertTrue(partial['canCancel'])
        cancelled=self.stage(partial,'cancelled')
        self.assertEqual(self.stock()['stock'],before+5)
        partial=self.stage(cancelled,'partially_allocated')
        self.assertEqual(self.stock()['stock'],before)
        paid=self.stage(partial,'paid');allocated=self.stage(paid,'allocated')
        self.assertEqual(self.stock()['stock'],before)
        for target in ('paid','partially_allocated'):
            self.assertEqual(self.call(f'orders/{allocated["id"]}','PUT',{'version':allocated['version'],'status':target}).status_code,400)

    def test_paid_to_allocation_through_full_edit(self):
        for target in ('partially_allocated','allocated'):
            with self.subTest(target=target):
                paid=self.stage(self.create(),'paid'); before=self.stock()['stock']
                body=copy.deepcopy(paid); body['status']=target
                response=self.call(f'orders/{paid["id"]}/details','PUT',body)
                self.assertEqual(response.status_code,200,response.json)
                self.assertEqual(response.json['order']['status'],target)
                self.assertEqual(self.stock()['stock'],before)

    def test_pending_freezes_all_mutation_paths_and_withdraw_restores_editing(self):
        order=self.stage(self.create(),'allocated');item=self.submit(order);balance=self.stock()
        body=copy.deepcopy(order);body['note']='must not save'
        requests=[(f'orders/{order["id"]}','PUT',{'version':order['version'],'status':'shipped','trackingNo':'TRACK'}),
                  (f'orders/{order["id"]}/details','PUT',body),('orders','DELETE',{'orderIds':[order['id']]}),
                  (f'orders/{order["id"]}/cancellation-requests','POST',{'version':order['version'],'reason':'duplicate'})]
        for path,method,data in requests:
            r=self.call(path,method,data);self.assertEqual(r.status_code,409,(path,r.json))
        self.assertEqual(self.stock(),balance)
        self.assertEqual(self.decision(item,'withdraw','warehouse').status_code,403)
        self.assertEqual(self.decision(item,'withdraw').status_code,200)
        body=self.detail(order['id']);body['note']='editable again'
        self.assertEqual(self.call(f'orders/{order["id"]}/details','PUT',body).status_code,200)

    def test_review_permission_company_scope_and_rejection(self):
        order=self.stage(self.create(),'paid');item=self.submit(order)
        self.assertEqual(self.call('orders/cancellation-requests',role='sales').status_code,403)
        self.assertEqual(self.decision(item,'approve','sales').status_code,403)
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\",\"orders.cancel.approve\"]'::jsonb WHERE role='sales' RETURNING id")
        self.assertEqual(self.call('orders/cancellation-requests',role='sales').json['pendingCount'],1)
        r=self.call(f'orders/cancellation-requests/{item["id"]}',role='sales')
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.call(f'orders/{order["id"]}',role='sales').status_code,404)
        r=self.call(f'orders/cancellation-requests/{item["id"]}/reject','POST',{'version':item['version'],'reviewNote':''},'sales')
        self.assertEqual(r.status_code,400)
        balance=self.stock()
        self.assertEqual(self.decision(item,'reject','sales').status_code,200)
        self.assertEqual(self.stock(),balance)
        self.assertEqual(self.detail(order['id'])['status'],'paid')
        self.assertEqual(self.decision(self.submit(self.detail(order['id'])),'approve','sales').status_code,200)

    def test_concurrent_review_and_withdraw_never_double_restore(self):
        for actions in [('approve','approve'),('approve','withdraw')]:
            order=self.stage(self.create(),'allocated');item=self.submit(order);before=self.stock()['stock']
            with ThreadPoolExecutor(2) as pool:
                responses=list(pool.map(lambda action:self.decision(item,action),actions))
            self.assertEqual(sorted(r.status_code for r in responses),[200,409],[r.json for r in responses])
            latest=self.detail(order['id'])
            self.assertEqual(self.stock()['stock'],before+(5 if latest['status']=='cancelled' else 0))

    def test_protected_delete_and_unknown_legacy_restore_are_rejected(self):
        order=self.stage(self.create(),'completed')
        self.assertEqual(self.call('orders','DELETE',{'orderIds':[order['id']]}).status_code,400)
        db._fetch_one("UPDATE orders SET status='cancelled',cancelled_from_status=NULL WHERE id=%s RETURNING id",(order['id'],))
        order=self.detail(order['id'])
        self.assertFalse(order['canRestore'])
        self.assertEqual(self.call(f'orders/{order["id"]}','PUT',{'version':order['version'],'status':'completed'}).status_code,400)

    def test_warehouse_reviewer_remains_financially_redacted_and_client_cannot_approve(self):
        order=self.stage(self.create(),'paid');item=self.submit(order)
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\",\"orders.cancel.approve\"]'::jsonb WHERE role='warehouse' RETURNING id")
        detail=self.call(f'orders/cancellation-requests/{item["id"]}',role='warehouse')
        self.assertEqual(detail.status_code,200,detail.json)
        self.assertNotIn('totalAmount',detail.json['order'])
        self.assertNotIn('unitPrice',detail.json['order']['items'][0])
        self.assertEqual(self.decision(item,'withdraw').status_code,200)
        order=self.detail(order['id'])
        forged=self.call(f'orders/{order["id"]}','PUT',{'version':order['version'],'status':'cancelled','approved':True,'approved_request_id':item['id']})
        self.assertEqual(forged.status_code,409,forged.json)

    def test_one_time_admin_grant_and_reliable_history_backfill(self):
        order=self.stage(self.create(),'partially_allocated');cancelled=self.stage(order,'cancelled')
        db._fetch_one('UPDATE orders SET cancelled_from_status=NULL WHERE id=%s RETURNING id',(order['id'],))
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\"]'::jsonb WHERE role IN ('admin','sales') RETURNING id")
        with db.get_connection() as conn,conn.cursor() as cur:
            cur.execute("DELETE FROM order_cancellation_migrations WHERE name IN ('restore-history-v1','admin-approval-grant-v1')")
            policy.migrate(cur)
        self.assertEqual(self.detail(cancelled['id'])['cancelledFromStatus'],'partially_allocated')
        self.assertIn(policy.APPROVE_PERMISSION,db._fetch_one("SELECT permissions FROM admin_users WHERE role='admin'")['permissions'])
        self.assertNotIn(policy.APPROVE_PERMISSION,db._fetch_one("SELECT permissions FROM admin_users WHERE role='sales'")['permissions'])
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\"]'::jsonb WHERE role='admin' RETURNING id")
        with db.get_connection() as conn,conn.cursor() as cur:policy.migrate(cur)
        self.assertNotIn(policy.APPROVE_PERMISSION,db._fetch_one("SELECT permissions FROM admin_users WHERE role='admin'")['permissions'])

    def test_pending_order_cannot_be_changed_indirectly_by_account_linking(self):
        order=self.detail(1);item=self.submit(order)
        response=self.call('store-users/1','PUT',{'linkedAdminId':2})
        self.assertEqual(response.status_code,409,response.json)
        self.assertIsNone(db._fetch_one('SELECT linked_admin_user_id FROM store_users WHERE id=1')['linked_admin_user_id'])
        self.assertEqual(self.decision(item,'withdraw').status_code,200)
        self.assertEqual(self.call('store-users/1','PUT',{'linkedAdminId':2}).status_code,200)

    def test_permission_removed_during_session_is_rechecked(self):
        order=self.stage(self.create(),'allocated');item=self.submit(order)
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\"]'::jsonb WHERE role='admin' RETURNING id")
        self.assertEqual(self.decision(item).status_code,403)
        self.assertEqual(self.detail(order['id'])['status'],'allocated')
