import io
import os
import unittest
import uuid
from unittest.mock import patch
from openpyxl import load_workbook
import test_contracts as helpers
from test_workbench import db,application,fixture_file
import contracts

class ContractBatchExportTest(unittest.TestCase):
    setUp=helpers.ContractsTest.setUp
    call=helpers.ContractsTest.call
    payload=helpers.ContractsTest.payload
    inventory=helpers.ContractsTest.inventory

    def make(self,at,**extra):
        body=self.payload();body.update(styleImage='',sizeChartImage='');body.update(extra)
        response=self.call(method='POST',body=body)
        self.assertEqual(response.status_code,200,response.json)
        item=response.json['item']
        db._fetch_one('UPDATE purchase_contracts SET created_at=%s WHERE id=%s RETURNING id',(at,item['id']))
        return item

    def test_creation_month_uses_beijing_half_open_bounds_and_keyword(self):
        old=self.make('2026-10-31 15:59:59+00',contractNo='BOUNDARY-OLD')
        first=self.make('2026-10-31 16:00:00+00',contractNo='BOUNDARY-NOV')
        last=self.make('2026-11-30 15:59:59+00',contractNo='BOUNDARY-LAST')
        after=self.make('2026-11-30 16:00:00+00',contractNo='BOUNDARY-DEC')
        result=self.call('contracts?createdMonth=2026-11').json
        self.assertEqual(result['total'],2)
        self.assertEqual([r['id'] for r in result['items']],[last['id'],first['id']])
        self.assertEqual(self.call('contracts?createdMonth=2026-11&keyword=NOV').json['total'],1)
        self.assertEqual(self.call('contracts?createdMonth=2026-10').json['items'][0]['id'],old['id'])
        self.assertEqual(self.call('contracts?createdMonth=2026-12').json['items'][0]['id'],after['id'])
        self.assertEqual(self.call().json['total'],4)

    def test_year_boundary_and_leap_february(self):
        leap=self.make('2024-02-29 15:59:59+00')
        march=self.make('2024-02-29 16:00:00+00')
        january=self.make('2026-12-31 16:00:00+00')
        self.assertEqual([r['id'] for r in self.call('contracts?createdMonth=2024-02').json['items']],[leap['id']])
        self.assertEqual([r['id'] for r in self.call('contracts?createdMonth=2024-03').json['items']],[march['id']])
        self.assertEqual([r['id'] for r in self.call('contracts?createdMonth=2027-01').json['items']],[january['id']])

    def test_invalid_period_and_selection_are_rejected(self):
        item=self.make('2026-11-01 00:00:00+00')
        for value in ['2026-13','2026-00','2026-1','0000-01','9999-12','today']:
            for path in ['contracts?','contracts/export?']:
                response=self.call(path+'createdMonth='+value)
                self.assertEqual(response.status_code,400,(path,value,response.json))
        for value in ['', '-1','0','1,a','9223372036854775808','99999']:
            self.assertEqual(self.call('contracts/export?contractIds='+value).status_code,400)
        self.assertEqual(self.call('contracts/export?createdMonth=2026-10&contractIds='+str(item['id'])).status_code,400)
        self.assertEqual(self.call('contracts/export?keyword=no-match').status_code,400)

    def test_selected_multi_sheet_export_preserves_template_images_and_inventory(self):
        image=fixture_file('/uploads/contract-batch.png')
        name="=duplicate/contract["+'长合同'*12+']'
        first=self.make('2026-11-01 00:00:00+00',contractNo=name,styleImage=image,sizeChartImage=image)
        second=self.make('2026-11-02 00:00:00+00',contractNo=name,styleImage=image,sizeChartImage=image)
        self.make('2026-10-01 00:00:00+00',contractNo='EXCLUDED')
        before=self.inventory();snapshots=db._fetch_all('SELECT id,snapshot FROM purchase_contracts ORDER BY id')
        response=self.call(f'contracts/export?createdMonth=2026-11&contractIds={first["id"]},{second["id"]},{first["id"]}')
        self.assertEqual(response.status_code,200,response.json if response.is_json else '')
        book=load_workbook(io.BytesIO(response.data))
        self.assertEqual(len(book.sheetnames),2)
        self.assertEqual(len(set(n.lower() for n in book.sheetnames)),2)
        self.assertTrue(all(len(n)<=31 and not any(c in n for c in '[]:*?/\\') for n in book.sheetnames))
        for sheet in book:
            self.assertIn(name,sheet['A1'].value)
            self.assertEqual(sheet['A1'].data_type,'s')
            self.assertEqual(len(sheet._images),2)
            self.assertIn('合同合计：12 件',[c.value for row in sheet for c in row])
            self.assertIsNone(sheet.freeze_panes)
        self.assertEqual(self.inventory(),before)
        self.assertEqual(db._fetch_all('SELECT id,snapshot FROM purchase_contracts ORDER BY id'),snapshots)
        self.assertEqual(self.call('contracts/1/export').status_code,200)

    def test_filtered_export_covers_all_pages_and_existing_module_permissions(self):
        for number in range(3):self.make('2026-11-01 00:00:00+00',contractNo='ALL-'+str(number))
        self.make('2026-10-01 00:00:00+00',contractNo='OLD')
        response=self.call('contracts/export?createdMonth=2026-11&page=2&pageSize=25',role='sales')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(load_workbook(io.BytesIO(response.data)).sheetnames),3)
        for role in ['warehouse','customer']:
            self.assertEqual(self.call('contracts/export',role=role).status_code,403)
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE role='sales' RETURNING id")
        self.assertEqual(self.call('contracts/export',role='sales').status_code,403)

    def test_change_during_export_prevents_releasing_stale_workbook(self):
        self.make('2026-11-01 00:00:00+00')
        def changed(*args,**kwargs):
            db._fetch_one("UPDATE purchase_contracts SET snapshot=jsonb_set(snapshot,'{revision}','2') WHERE id=1 RETURNING id")
            return io.BytesIO(b'stale')
        with patch.object(application.order_export_process,'build',side_effect=changed):
            response=self.call('contracts/export')
        self.assertEqual(response.status_code,409,response.json)

    def test_batch_joins_existing_export_queue(self):
        self.make('2026-11-01 00:00:00+00');ticket=str(uuid.uuid4())
        def request():
            with application.app.test_client() as client:
                return client.get('/api/admin/contracts/export',headers={'Authorization':'Bearer '+self.tokens['admin'],'X-Export-Ticket':ticket})
        with patch.dict(os.environ,{'SECURITY_EXPORT_GLOBAL_CONCURRENT':'1'}):
            with db._connect(autocommit=True,coordination=True) as locks:
                locks.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',('export:global:0',))
                try:
                    response=request();self.assertEqual(response.status_code,429,response.json)
                    self.assertEqual(response.json['code'],'export_queued')
                finally:locks.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',('export:global:0',))
            self.assertEqual(request().status_code,200)
        self.assertEqual(db._fetch_one('SELECT state FROM security_export_queue WHERE ticket=%s',(ticket,))['state'],'finished')
