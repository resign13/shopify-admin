import copy
import json
import os
import uuid
import unittest
from io import BytesIO
from unittest.mock import patch
from openpyxl import load_workbook
import test_orders as helpers
from test_workbench import db,application,fixture_file
import order_drafts


class DraftInvoiceTest(unittest.TestCase):
    setUp=helpers.AdminOrdersTest.setUp
    call=helpers.AdminOrdersTest.call
    payload=helpers.AdminOrdersTest.payload
    create=helpers.AdminOrdersTest.create
    stock=helpers.AdminOrdersTest.stock

    def draft(self,role='admin',**changes):
        data=self.payload();data.update(shippingFee=0,contactName='',phone='',country='',address='',**changes)
        r=self.call('orders/drafts','POST',{'draftKey':str(uuid.uuid4()),'draft':data},role)
        self.assertEqual(r.status_code,200,r.json)
        return r.json,data

    def export(self,saved,role='admin',ticket=None):
        with application.app.test_client() as client:
            headers={'Authorization':'Bearer '+self.tokens[role]}
            if ticket:headers['X-Export-Ticket']=ticket
            return client.get(f'/api/admin/orders/drafts/{saved["id"]}/invoice?version={saved["version"]}',headers=headers)

    def test_zero_freight_incomplete_draft_export_preserves_business(self):
        saved,data=self.draft();before=self.stock()
        counts=[db._fetch_one(f'SELECT count(*) AS n FROM {t}')['n'] for t in ['orders','order_created_events','order_warehouse_prints']]
        r=self.export(saved)
        self.assertEqual(r.status_code,200,r.json if r.is_json else '')
        book=load_workbook(BytesIO(r.data));sheet=book['PI']
        self.assertIn('草稿',sheet['B5'].value);self.assertIn('DRAFT-',sheet['B5'].value)
        self.assertIn(20,[c.value for row in sheet.iter_rows(max_col=10) for c in row if isinstance(c.value,(int,float))])
        self.assertEqual(self.stock(),before)
        self.assertEqual(counts,[db._fetch_one(f'SELECT count(*) AS n FROM {t}')['n'] for t in ['orders','order_created_events','order_warehouse_prints']])
        self.assertEqual(db._fetch_one('SELECT document FROM admin_order_drafts WHERE id=%s',(saved['id'],))['document']['shippingFee'],0)

    def test_saved_price_pending_lines_and_scope(self):
        saved,data=self.draft(role='sales',pendingItems=[{'productId':None,'sku':'REMOVED','productName':'Original name','quantity':2,'unitPrice':7,'reason':'商品已删除'}])
        db._fetch_one('UPDATE product_size_prices SET price=999 RETURNING id')
        with application.app.test_request_context('/'):
            from flask import g
            g.current_user={'id':2,'role':'sales'}
            snap=order_drafts.invoice_snapshot(saved['id'],saved['version'])
        self.assertEqual(snap['items'][0]['unitPrice'],20)
        self.assertTrue(any('[待核对]' in r['productName'] and r['quantity']==2 for r in snap['items']))
        self.assertEqual(self.export(saved,role='warehouse').status_code,403)
        self.assertEqual(self.export(saved).status_code,200)  # Admin can view/export, not edit another user's draft.
        other,_=self.draft()
        self.assertEqual(self.export(other,role='sales').status_code,404)

    def test_empty_stale_and_formal_invoice_validation(self):
        saved,_=self.draft(items=[])
        self.assertEqual(self.export(saved).status_code,400)
        saved,_=self.draft()
        wrong={**saved,'version':'999'}
        self.assertEqual(self.export(wrong).status_code,409)
        order=self.create()
        db._fetch_one('UPDATE orders SET shipping_fee=0 WHERE id=%s RETURNING id',(order['id'],))
        self.assertEqual(self.call(f'orders/{order["id"]}/invoice').status_code,400)

    def test_unavailable_saved_lines_and_saved_cny_terms_are_not_repriced(self):
        data=self.payload()
        data['items'][0].update(productId=999999,sku='REMOVED',productName='Saved removed line',unitPrice=68,priceSource='manual')
        saved,_=self.draft(items=data['items'])
        # Legacy saved CNY drafts remain exportable; new drafts are still USD-only.
        db._fetch_one('UPDATE admin_order_drafts SET document=document||%s::jsonb WHERE id=%s RETURNING id',
                      (json.dumps({'currency':'CNY','exchangeRate':'6.80'}),saved['id']))
        with application.app.test_request_context('/'):
            from flask import g
            g.current_user={'id':1,'role':'admin'}
            snap=order_drafts.invoice_snapshot(saved['id'],saved['version'])
        self.assertEqual((snap['currency'],snap['exchangeRate']),('CNY','6.80'))
        self.assertEqual((snap['items'][0]['unitPrice'],snap['items'][0]['quantity']),(68,2))
        self.assertIn('[待核对]',snap['items'][0]['productName'])
        result=self.export(saved)
        self.assertEqual(result.status_code,200)
        book=load_workbook(BytesIO(result.data))
        values=[c.value for row in book['PI'].iter_rows() for c in row]
        self.assertTrue(any(isinstance(v,str) and 'Saved removed line' in v and '[待核对]' in v for v in values))
        self.assertIn(10,values)  # Saved 68 CNY / 6.80, not today's catalog price.

    def test_deleted_and_submitted_drafts_invalidate_recovery(self):
        for state in ['deleted','converted']:
            saved,_=self.draft();ticket=str(uuid.uuid4())
            self.assertEqual(self.export(saved,ticket=ticket).status_code,200)
            db._fetch_one('UPDATE admin_order_drafts SET state=%s,revision=revision+1 WHERE id=%s RETURNING id',(state,saved['id']))
            self.assertEqual(self.call(f'orders/export-results/{ticket}/download').status_code,409)
            self.assertEqual(self.export(saved).status_code,409)

    def test_change_during_generation_does_not_publish(self):
        saved,_=self.draft()
        def changed(*args,**kwargs):
            db._fetch_one('UPDATE admin_order_drafts SET revision=revision+1 WHERE id=%s RETURNING id',(saved['id'],))
            return BytesIO(b'not released')
        with patch('order_export_process.build',side_effect=changed):
            r=self.export(saved)
        self.assertEqual(r.status_code,409,r.json)

    def test_images_notes_and_pdf_attachments_are_preserved(self):
        image=fixture_file('/uploads/draft-note.png');pdf=fixture_file('/uploads/draft-label.pdf')
        saved,_=self.draft(note='Saved draft packing note',labelImageUrls=[image],labelPdfUrl=pdf)
        response=self.export(saved)
        self.assertEqual(response.status_code,200,response.json if response.is_json else '')
        book=load_workbook(BytesIO(response.data))
        values='\n'.join(str(c.value or '') for sheet in book for row in sheet for c in row)
        self.assertIn('Saved draft packing note',values)
        self.assertIn('draft-label.pdf',values)
        self.assertGreaterEqual(sum(len(sheet._images) for sheet in book),2)

    def test_draft_uses_existing_queue_expiry_timeout_and_result_recovery(self):
        saved,_=self.draft();ticket=str(uuid.uuid4())
        with patch.dict(os.environ,{'SECURITY_EXPORT_GLOBAL_CONCURRENT':'1'}):
            with db._connect(autocommit=True,coordination=True) as locks:
                locks.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',('export:global:0',))
                try:
                    waiting=self.export(saved,ticket=ticket)
                    self.assertEqual(waiting.json['code'],'export_queued')
                    self.assertEqual(self.call(f'orders/export-results/{ticket}').json['status'],'waiting')
                    db._fetch_one("UPDATE security_export_queue SET created_at=clock_timestamp()-interval '121 seconds' WHERE ticket=%s RETURNING seq",(ticket,))
                    self.assertEqual(self.call(f'orders/export-results/{ticket}').json['status'],'expired')
                finally:locks.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',('export:global:0',))
        ticket=str(uuid.uuid4())
        with patch.object(application.order_export_process,'build',side_effect=application.order_export_process.ExportTimeout()):
            timed=self.export(saved,ticket=ticket)
        self.assertEqual((timed.status_code,timed.json['code']),(504,'export_timeout'))
        failed=self.call(f'orders/export-results/{ticket}')
        self.assertEqual((failed.json['status'],failed.json['code']),('failed','export_timeout'))
        ticket=str(uuid.uuid4());self.assertEqual(self.export(saved,ticket=ticket).status_code,200)
        self.assertEqual(self.call(f'orders/export-results/{ticket}/download').status_code,200)

    def test_cached_result_binds_draft_revision_without_formal_order_ids(self):
        saved,data=self.draft();ticket=str(uuid.uuid4());r=self.export(saved,ticket=ticket)
        self.assertEqual(r.status_code,200,r.json if r.is_json else '')
        self.assertTrue(r.is_json)
        self.assertEqual(r.json['status'],'ready')
        row=db._fetch_one('SELECT result_orders,result_draft_id,result_draft_revision FROM security_export_queue WHERE ticket=%s',(ticket,))
        self.assertEqual(row['result_orders'],[])
        self.assertEqual(row['result_draft_id'],saved['id'])
        self.assertEqual(self.call(f'orders/export-results/{ticket}/download').status_code,200)
        self.assertEqual(self.call(f'orders/export-results/{ticket}/download',role='sales').status_code,404)
        db._fetch_one('UPDATE admin_order_drafts SET revision=revision+1 WHERE id=%s RETURNING id',(saved['id'],))
        self.assertEqual(self.call(f'orders/export-results/{ticket}/download').status_code,409)
