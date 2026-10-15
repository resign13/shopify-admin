import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_orders as helpers
from test_workbench import db, fixture_file


class OrderDraftsTest(unittest.TestCase):
    setUp = helpers.AdminOrdersTest.setUp
    call = helpers.AdminOrdersTest.call
    payload = helpers.AdminOrdersTest.payload
    create = helpers.AdminOrdersTest.create
    stock = helpers.AdminOrdersTest.stock

    def save(self, document=None, role='sales', key=None):
        body={'draftKey':key or str(uuid.uuid4()),'draft':document or {'contactName':'Partial','note':'尚未选品\n辅料备注'}}
        response=self.call('orders/drafts','POST',body,role)
        self.assertEqual(response.status_code,200,response.json)
        return response.json,body

    def totals(self):
        return [db._fetch_one(f'SELECT COUNT(*) AS n FROM {t}')['n'] for t in ['orders','order_created_events','admin_order_requests']]

    def test_partial_draft_server_persistence_without_order_or_inventory(self):
        before=self.totals(); stock=self.stock()
        saved,_=self.save()
        result=self.call(f"orders/drafts/{saved['id']}",role='sales')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['draft']['note'],'尚未选品\n辅料备注')
        self.assertEqual(result.json['draft']['items'],[])
        self.assertIsNone(result.json['draft']['userId'])
        self.assertFalse(result.json['customerUnavailable'])
        self.assertTrue(result.json['draft']['ownerConfirmed'])
        self.assertEqual(self.totals(),before);self.assertEqual(self.stock(),stock)
        self.assertEqual(self.call('orders/drafts',role='sales').json['total'],1)

    def test_scope_readonly_admin_and_role_permission(self):
        saved,_=self.save(); sid=saved['id']
        self.assertEqual(self.call('orders/drafts').json['total'],0)
        self.assertEqual(self.call('orders/drafts?scope=all').json['total'],1)
        self.assertFalse(self.call(f'orders/drafts/{sid}').json['canEdit'])
        for method in ['PUT','DELETE']:
            self.assertEqual(self.call(f'orders/drafts/{sid}',method,{'version':saved['version'],'draft':{}}).status_code,404)
        other,_=self.save(role='admin')
        self.assertEqual(self.call('orders/drafts?scope=all',role='sales').json['total'],1)
        self.assertEqual(self.call(f"orders/drafts/{other['id']}",role='sales').status_code,404)
        for role in ['warehouse','customer']:
            self.assertEqual(self.call('orders/drafts',role=role).status_code,403)
            self.assertEqual(self.call('orders/drafts','POST',{'draft':{}},role).status_code,403)
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE id=2 RETURNING id")
        self.assertEqual(self.call(f'orders/drafts/{sid}',role='sales').status_code,403)

    def test_versions_retries_and_delete_tombstone(self):
        saved,body=self.save(); sid=saved['id']
        replay=self.call('orders/drafts','POST',body,'sales')
        self.assertEqual(replay.json['id'],sid)
        self.assertEqual(replay.json['submitRequestId'],saved['submitRequestId'])
        changes={'version':saved['version'],'draft':{'contactName':'Changed'}}
        updated=self.call(f'orders/drafts/{sid}','PUT',changes,'sales')
        self.assertEqual(updated.status_code,200,updated.json)
        self.assertEqual(self.call(f'orders/drafts/{sid}','PUT',changes,'sales').json['version'],updated.json['version'])
        changes['draft']['contactName']='Competing edit'
        self.assertEqual(self.call(f'orders/drafts/{sid}','PUT',changes,'sales').status_code,409)
        self.assertEqual(self.call(f'orders/drafts/{sid}','DELETE',{'version':saved['version']},'sales').status_code,409)
        self.assertEqual(self.call(f'orders/drafts/{sid}','DELETE',{'version':updated.json['version']},'sales').status_code,200)
        self.assertEqual(self.call('orders/drafts',role='sales').json['total'],0)
        self.assertEqual(self.call('orders/drafts','POST',body,'sales').status_code,409)

    def test_concurrent_first_save_only_one_draft(self):
        body={'draftKey':str(uuid.uuid4()),'draft':{'contactName':'Concurrent'}}
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:self.call('orders/drafts','POST',body,'sales'),range(2)))
        self.assertTrue(all(r.status_code==200 for r in responses),[r.json for r in responses])
        self.assertEqual(len({r.json['id'] for r in responses}),1)
        self.assertEqual(self.call('orders/drafts',role='sales').json['total'],1)

    def test_first_draft_save_keeps_submission_identity_and_cannot_duplicate_committed_form(self):
        form=self.payload(); request_id=form['requestId']
        body={'draftKey':str(uuid.uuid4()),'submitRequestId':request_id,'draft':form}
        saved=self.call('orders/drafts','POST',body,'sales')
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['submitRequestId'],request_id)
        self.assertEqual(self.call('orders/drafts','POST',body,'sales').json['id'],saved.json['id'])
        another={**body,'draftKey':str(uuid.uuid4())}
        self.assertEqual(self.call('orders/drafts','POST',another,'sales').status_code,409)
        # A direct creation can have committed even if its response was lost.
        self.assertEqual(self.call('orders','POST',form,'sales').status_code,200)
        before=self.totals();stock=self.stock()
        self.assertEqual(self.call('orders/drafts','POST',body,'sales').status_code,409)
        self.assertEqual(self.totals(),before);self.assertEqual(self.stock(),stock)

    def submit_body(self, saved):
        document=self.call(f"orders/drafts/{saved['id']}",role='sales').json['draft']
        return {**document,'draftId':saved['id'],'draftVersion':saved['version'],
                'requestId':saved['submitRequestId']}

    def test_convert_and_network_retry_atomic_once(self):
        saved,_=self.save(self.payload()); body=self.submit_body(saved); before=self.totals(); stock=self.stock()['stock']
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:self.call('orders','POST',body,'sales'),range(2)))
        self.assertEqual([r.status_code for r in responses],[200,200],[r.json for r in responses])
        self.assertEqual(sum(r.json['replayed'] for r in responses),1)
        self.assertEqual(self.stock()['stock'],stock-5)
        self.assertEqual(self.totals(),[n+1 for n in before])
        self.assertEqual(self.call('orders/drafts',role='sales').json['total'],0)
        self.assertEqual(db._fetch_one('SELECT state,document FROM admin_order_drafts WHERE id=%s',(saved['id'],)),{'state':'converted','document':{}})

    def test_price_conflict_preserves_draft_and_failed_conversion_rolls_back(self):
        saved,_=self.save(self.payload()); body=self.submit_body(saved); stock=self.stock()['stock']; before=self.totals()
        db._fetch_one("UPDATE product_size_prices SET price=32 WHERE product_id=1 AND size_code='M' RETURNING id")
        result=self.call('orders','POST',body,'sales');self.assertEqual(result.status_code,409,result.json)
        self.assertEqual(self.call('orders/drafts',role='sales').json['total'],1)
        self.assertEqual(self.stock()['stock'],stock);self.assertEqual(self.totals(),before)
        body['items'][0]['unitPrice']=32
        body['items'][0]['referencePriceUsd']=result.json['changes'][0]['referencePriceUsd']
        with patch('order_drafts.converted',side_effect=ValueError('fixture conversion failure')):
            self.assertEqual(self.call('orders','POST',body,'sales').status_code,400)
        self.assertEqual(self.stock()['stock'],stock);self.assertEqual(self.totals(),before)
        self.assertEqual(self.call('orders','POST',body,'sales').status_code,200)

    def test_stale_version_and_other_owner_submit_rejected(self):
        saved,_=self.save(self.payload()); body=self.submit_body(saved)
        other=self.call('orders','POST',body)
        self.assertEqual(other.status_code,404)
        update=self.call(f"orders/drafts/{saved['id']}",'PUT',{'version':saved['version'],'draft':{'contactName':'Another window'}},'sales')
        self.assertEqual(update.status_code,200,update.json)
        self.assertEqual(self.call('orders','POST',body,'sales').status_code,409)

    def test_reorder_source_attachments_and_current_refresh(self):
        source=self.create();oid=source['id']
        fixture_file('/uploads/old.pdf','order',oid)
        db._fetch_one("UPDATE orders SET owner_admin_id=2,label_image_urls='[\"/uploads/old.pdf\"]' WHERE id=%s RETURNING id",(oid,))
        data=self.call(f'orders/{oid}/reorder-draft',role='sales').json['draft']
        saved,_=self.save({**data,'sourceOrderId':oid})
        db._fetch_one("DELETE FROM product_size_prices WHERE product_id=1 AND size_code='L' RETURNING id")
        refreshed=self.call(f"orders/drafts/{saved['id']}",role='sales').json
        self.assertEqual(refreshed['draft']['inheritedAttachmentUrls'],[fixture_file('/uploads/old.pdf','order',oid)])
        self.assertEqual(refreshed['sourceOrderId'],oid)
        self.assertEqual(refreshed['draft']['pendingItems'][0]['reason'],'原尺码已移除')
        db._fetch_one("UPDATE orders SET owner_admin_id=NULL WHERE id=%s RETURNING id",(oid,))
        body=self.submit_body(saved)
        self.assertEqual(self.call('orders','POST',body,'sales').status_code,404)

    def test_repeat_migration_and_pagination(self):
        import order_drafts
        for n in range(11): self.save({'contactName':f'Buyer {n}'})
        before=self.call('orders/drafts',role='sales').json
        with db.get_connection() as conn,conn.cursor() as cur: order_drafts.migrate(cur)
        after=self.call('orders/drafts',role='sales').json
        self.assertEqual(before,after);self.assertEqual(len(after['items']),10)
        self.assertEqual(len(self.call('orders/drafts?page=2',role='sales').json['items']),1)


if __name__=='__main__': unittest.main()
