"""Unified undelivered-balance regression. All writes use guarded *_test fixtures."""
import io
import json
from pathlib import Path
import subprocess
import sys
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from openpyxl import load_workbook
import test_workbench as fixtures
import inventory_overdelivery as policy
db = fixtures.db


class OverdeliveryTest(unittest.TestCase):
    setUp = fixtures.WorkbenchTest.setUp
    call = fixtures.WorkbenchTest.call
    detail = fixtures.WorkbenchTest.detail
    product_payload = fixtures.WorkbenchTest.product_payload
    upload = fixtures.WorkbenchTest.upload

    def prepare(self, quantities=None, *, legacy=None):
        quantities = quantities or {'M':100}
        db._fetch_one('UPDATE product_size_prices SET contract_pending=0,pending_inspection=0,pending_inbound=0 WHERE product_id=1 RETURNING id')
        if legacy:
            response = self.save(contractPendingBySize=legacy)
            self.assertEqual(response.status_code, 200, response.json)
        body={'requestId':str(uuid.uuid4()),'partyA':'采购','partyB':'工厂','contractNo':'EXTRA-TEST',
              'styleImage':'/uploads/fixture.jpg','sizeChartImage':'/uploads/fixture.jpg','deliveryDate':'2026-10-20',
              'items':[{'productId':1,'quantities':quantities}]}
        result=self.call('contracts','POST',body)
        self.assertEqual(result.status_code,200,result.json)
        return result.json['item']

    def size(self, code='M'): return next(s for s in self.detail()['sizePrices'] if s['sizeCode']==code)
    def save(self, **fields):
        return self.call('inventory/1','PUT',{'version':self.detail()['version'],'sizeStocks':{},**fields})
    def receive(self, source='normal', body=None):
        path='receive' if source=='normal' else 'temporary/receive' if source=='temporary' else 'defective/return'
        return self.call('inventory/1/'+path,'POST',body or {'version':self.detail()['version'],'requestId':str(uuid.uuid4())})

    def test_100_accepts_115_not_116_then_receives_stock(self):
        self.prepare(); stock=self.size()['stock']
        self.assertEqual(self.save(pendingInspectionBySize={'M':116}).status_code,400)
        r=self.save(pendingInspectionBySize={'M':115});self.assertEqual(r.status_code,200,r.json)
        s=self.size();self.assertEqual((s['contractPending'],s['pendingInspection'],s['overdeliveryUsed'],s['overdeliveryInspection']),(0,115,15,15))
        self.assertGreater(db._fetch_one("SELECT count(*) AS n FROM admin_audit_logs WHERE entity_table='inventory_overdelivery'")['n'],0)
        self.assertEqual(s['stock'],stock)
        self.assertEqual(self.save(pendingInboundBySize={'M':115}).status_code,200)
        self.assertEqual(self.size()['overdeliveryQualified'],15)
        body={'version':self.detail()['version'],'requestId':str(uuid.uuid4())}
        self.assertEqual(self.receive(body=body).status_code,200)
        self.assertEqual(self.size()['stock'],stock+115)
        self.assertEqual(self.size()['overdeliveryUsed'],15)
        self.assertEqual(self.size()['overdeliveryQualified'],0)
        self.assertTrue(self.receive(body=body).json['replayed'])


    def test_each_arrival_recomputes_from_live_balance(self):
        self.prepare()
        self.assertEqual(self.save(pendingInspectionBySize={'M':90}).status_code,200)
        self.assertEqual((self.size()['contractPending'],self.size()['overdeliveryLimit']),(10,1))
        self.assertEqual(self.save(pendingInspectionBySize={'M':102}).status_code,400)
        self.assertEqual(self.save(pendingInspectionBySize={'M':101}).status_code,200)
        self.assertEqual((self.size()['contractPending'],self.size()['overdeliveryUsed']),(0,1))
        self.assertEqual(self.save(pendingInspectionBySize={'M':102}).status_code,400)

    def test_return_extra_first_never_replenishes_allowance(self):
        self.prepare();self.save(pendingInspectionBySize={'M':115})
        self.save(defectivePendingBySize={'M':20})
        before=self.size(); body={'version':self.detail()['version'],'requestId':str(uuid.uuid4())}
        result=self.receive('defective',body)
        self.assertEqual(result.status_code,200,result.json)
        s=self.size();self.assertEqual((s['contractPending'],s['pendingInspection'],s['overdeliveryUsed'],s['overdeliveryInspection']),(5,95,15,0))
        self.assertEqual(result.json['changes'][0]['extraReturned'],15)
        self.assertTrue(self.receive('defective',body).json['replayed'])
        self.assertEqual(s['stock'],before['stock'])
        self.assertEqual(self.save(pendingInspectionBySize={'M':101}).status_code,400)
        self.assertEqual(self.save(pendingInspectionBySize={'M':100}).status_code,200)

    def test_reserve_qualified_reverse_and_manual_correction(self):
        self.prepare();self.save(pendingInspectionBySize={'M':115});self.save(defectivePendingBySize={'M':10})
        self.assertEqual(self.save(pendingInboundBySize={'M':106}).status_code,400)
        self.assertEqual(self.save(pendingInboundBySize={'M':105}).status_code,200)
        self.assertEqual((self.size()['overdeliveryInspection'],self.size()['overdeliveryQualified']),(10,5))
        self.assertEqual(self.save(pendingInboundBySize={'M':0},pendingInspectionBySize={'M':0},defectivePendingBySize={'M':0}).status_code,200)
        self.assertEqual((self.size()['contractPending'],self.size()['overdeliveryUsed']),(100,15))
        self.assertEqual(self.save(pendingInspectionBySize={'M':101}).status_code,200)

    def test_rounding_size_isolation_and_manual_balance_allowance(self):
        self.prepare({'M':6,'L':7})
        self.assertEqual(self.save(pendingInspectionBySize={'M':7}).status_code,400)
        self.assertEqual(self.save(pendingInspectionBySize={'L':8}).status_code,200)
        self.assertEqual(self.size('L')['overdeliveryUsed'],1)
        self.assertEqual(self.save(contractPendingBySize={'Tall XL':100}).status_code,200)
        self.assertEqual(self.size('Tall XL')['overdeliveryLimit'],15)
        self.assertEqual(self.save(pendingInspectionBySize={'Tall XL':101}).status_code,200)

    def test_multi_size_rollback_and_concurrency(self):
        self.prepare({'M':100,'L':100});before=self.detail()
        self.assertEqual(self.save(pendingInspectionBySize={'M':115,'L':116}).status_code,400)
        self.assertEqual(self.detail(),before)
        body={'version':before['version'],'sizeStocks':{},'pendingInspectionBySize':{'M':115}}
        with ThreadPoolExecutor(max_workers=2) as pool:
            rs=list(pool.map(lambda _:self.call('inventory/1','PUT',body),range(2)))
        self.assertEqual(sorted(r.status_code for r in rs),[200,409])
        self.assertEqual(self.size()['overdeliveryUsed'],15)

    def test_audit_failure_rolls_back_ledger_and_stock(self):
        self.prepare();before=self.detail()
        with patch('workbench.record_inventory_registration',side_effect=ValueError('audit failure')):
            self.assertEqual(self.save(pendingInspectionBySize={'M':115}).status_code,400)
        self.assertEqual(self.detail(),before)


    def test_contract_edit_applies_delta_even_with_historical_extra(self):
        contract=self.prepare()
        self.assertEqual(self.save(pendingInspectionBySize={'M':115}).status_code,200)
        self.assertEqual(self.save(pendingInspectionBySize={'M':0}).status_code,200)
        body={**contract,'requestId':str(uuid.uuid4()),'revision':contract['revision']}
        body['items'][0]['quantities']['M']=90
        r=self.call('contracts/1','PUT',body)
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual((self.size()['contractPending'],self.size()['overdeliveryLimit'],self.size()['overdeliveryUsed']),(90,13,15))

    def test_product_edits_preserve_ledger_and_customer_omits_fields(self):
        self.prepare();self.save(pendingInspectionBySize={'M':115})
        response=self.call('products/1','PUT',self.product_payload(1))
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.size()['overdeliveryUsed'],15)
        for route in ['inventory/1','inventory?page=1']:
            public=self.call(route,role='customer')
            self.assertNotIn('overdelivery',str(public.json))
            self.assertNotIn('originalContractQuantity',str(public.json))
        self.save(pendingInspectionBySize={'M':0})
        payload=self.product_payload(1);payload['sizes']=['L','Tall XL'];payload['sizePrices']=[s for s in payload['sizePrices'] if s['sizeCode']!='M']
        self.assertEqual(self.call('products/1','PUT',payload).status_code,400)

    def test_excel_v7_and_legacy_balance_limit(self):
        self.prepare()
        raw=self.call('inventory/export').data
        book=load_workbook(io.BytesIO(raw)); sheet=book.active
        self.assertEqual(sheet['A2'].value,'inventory-v7');self.assertEqual(sheet['T2'].value,115)
        sheet['O2']=115;sheet['T2']=999999;sheet['U2']=999999
        out=io.BytesIO();book.save(out)
        r=self.upload('preview',out.getvalue());self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(r.json['errors'],[])
        r=self.upload('confirm',out.getvalue(),r.json['fileHash'])
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(self.size()['overdeliveryUsed'],15)
        book=load_workbook(io.BytesIO(self.call('inventory/export').data));sheet=book.active
        sheet['O2']=116;sheet.delete_cols(20,6)
        for row in range(2,sheet.max_row+1):sheet.cell(row,1,'inventory-v5')
        out=io.BytesIO();book.save(out)
        r=self.upload('preview',out.getvalue());self.assertTrue(r.json['errors'])

    def test_repeated_migration_preserves_ledger(self):
        self.prepare();self.save(pendingInspectionBySize={'M':115})
        before=self.size()
        with db.get_connection() as conn,conn.cursor() as cur:
            policy.migrate(cur);policy.migrate(cur)
        self.assertEqual(self.size(),before)

    def test_readonly_runtime_startup_accepts_migrated_ledger(self):
        # Detached Excel/PDF workers disable runtime migrations before importing app.
        with patch.dict('os.environ', {'DB_SCHEMA_AUTO_MIGRATE':'0'}):
            db.ensure_database_ready()


    def test_manual_and_contract_share_allowance_and_full_defect_return(self):
        self.assertEqual(self.save(contractPendingBySize={'M':100}).status_code,200)
        db._fetch_one("UPDATE product_size_prices SET pending_inspection=0,pending_inbound=0 WHERE product_id=1 AND size_code='M' RETURNING id")
        before=self.size()['stock']
        self.assertEqual(self.save(pendingInspectionBySize={'M':116}).status_code,400)
        self.assertEqual(self.save(pendingInspectionBySize={'M':115},defectivePendingBySize={'M':115}).status_code,200)
        self.assertEqual(self.size()['contractPending'],0)
        result=self.receive('defective')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['changes'][0]['extraReturned'],15)
        s=self.size()
        self.assertEqual((s['contractPending'],s['pendingInspection'],s['defectivePending'],s['stock']),(100,0,0,before))

    def test_zm4744_and_zm4745_legacy_pending_is_received_without_a_duplicate_contract(self):
        contract = self.prepare({'M':75,'L':60}, legacy={'M':100,'L':87})
        db._fetch_one("UPDATE product_size_prices SET pending_inspection=CASE size_code WHEN 'M' THEN 1 ELSE 2 END "
                      "WHERE product_id=1 AND size_code IN ('M','L') RETURNING id")
        stocks = {code:self.size(code)['stock'] for code in ('M','L')}
        response = self.save(pendingInspectionBySize={'M':101,'L':89})
        self.assertEqual(response.status_code, 200, response.json)
        for code, pending, inspection, limit in [('M',75,101,11),('L',60,89,9)]:
            s = self.size(code)
            self.assertEqual((s['contractPending'],s['pendingInspection'],s['overdeliveryUsed'],s['overdeliveryLimit'],s['stock']),
                             (pending,inspection,0,limit,stocks[code]))
            self.assertNotIn('contractInspection', s)
        # A real contract with no arrivals is still cancellable; the old
        # inspection stage must survive independently, with no second add.
        cancelled = self.call('contracts/1/cancel','POST',{'revision':contract['revision'],'deductions':[
            {'productId':1,'sizeCode':'M','balance':75,'quantity':75},
            {'productId':1,'sizeCode':'L','balance':60,'quantity':60}]})
        self.assertEqual(cancelled.status_code, 200, cancelled.json)
        self.assertEqual([(self.size(k)['contractPending'],self.size(k)['pendingInspection']) for k in ('M','L')],
                         [(0,101),(0,89)])


    def test_explicit_extra_does_not_spend_new_contract_balance(self):
        self.prepare({'M':100},legacy={'M':100})
        self.assertEqual(self.save(pendingInspectionBySize={'M':110},receiptExtraBySize={'M':31}).status_code,400)
        result=self.save(pendingInspectionBySize={'M':110},receiptExtraBySize={'M':10})
        self.assertEqual(result.status_code,200,result.json)
        s=self.size()
        self.assertEqual((s['contractPending'],s['pendingInspection'],s['overdeliveryInspection']),(100,110,10))
        self.assertEqual(self.save(defectivePendingBySize={'M':10}).status_code,200)
        self.assertEqual(self.receive('defective').status_code,200)
        self.assertEqual(self.size()['contractPending'],100)

    def test_excel_moves_existing_pending_without_using_new_contract_or_extra_quota(self):
        self.prepare({'M':75}, legacy={'M':100})
        book = load_workbook(io.BytesIO(self.call('inventory/export').data))
        book.active['O2'] = 100
        out = io.BytesIO(); book.save(out)
        preview = self.upload('preview', out.getvalue())
        self.assertEqual(preview.status_code,200,preview.json)
        self.assertEqual(preview.json['errors'],[])
        result = self.upload('confirm', out.getvalue(), preview.json['fileHash'])
        self.assertEqual(result.status_code,200,result.json)
        s = self.size()
        self.assertEqual((s['contractPending'],s['pendingInspection'],s['overdeliveryUsed']), (75,100,0))

    def test_excel_optional_extra_preserves_already_entered_new_balance(self):
        self.prepare({'M':100},legacy={'M':100})
        book=load_workbook(io.BytesIO(self.call('inventory/export').data))
        book.active['O2'],book.active['Y2']=110,10
        out=io.BytesIO();book.save(out)
        preview=self.upload('preview',out.getvalue())
        self.assertEqual(preview.json['errors'],[])
        self.assertEqual(preview.json['rows'][0]['contractPending'],100)
        confirmed=self.upload('confirm',out.getvalue(),preview.json['fileHash'])
        self.assertEqual(confirmed.status_code,200,confirmed.json)
        s=self.size()
        self.assertEqual((s['contractPending'],s['pendingInspection'],s['overdeliveryInspection']),(100,110,10))

    def test_active_contract_protects_ordered_size_after_manual_clear(self):
        self.prepare({'Tall XL':100})
        self.assertEqual(self.save(contractPendingBySize={'Tall XL':0}).status_code,200)
        payload=self.product_payload(1)
        payload['sizes']=[size for size in payload['sizes'] if size!='Tall XL']
        payload['sizePrices']=[size for size in payload['sizePrices'] if size['sizeCode']!='Tall XL']
        denied=self.call('products/1','PUT',payload)
        self.assertEqual(denied.status_code,400,denied.json)
        self.assertEqual(self.size('Tall XL')['contractPending'],0)

    def test_legacy_stages_do_not_spend_first_contract_quantity(self):
        # CS5402: thirteen old inspection pieces existed before a new 70-piece
        # contract. Qualifying/receiving those old pieces must not consume it.
        db._fetch_one('UPDATE product_size_prices SET contract_pending=0,pending_inspection=0,pending_inbound=0 WHERE product_id=1 RETURNING id')
        db._fetch_one("UPDATE product_size_prices SET pending_inspection=13 WHERE product_id=1 AND size_code='M' RETURNING id")
        body={'requestId':str(uuid.uuid4()),'partyA':'采购','partyB':'工厂','contractNo':'LEGACY-CS5402',
              'styleImage':'/uploads/fixture.jpg','sizeChartImage':'/uploads/fixture.jpg','deliveryDate':'2026-11-20',
              'items':[{'productId':1,'quantities':{'M':70}}]}
        result=self.call('contracts','POST',body)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(self.size()['contractPending'],70)
        self.assertEqual(self.save(pendingInboundBySize={'M':13}).status_code,200)
        self.assertEqual(self.receive().status_code,200)
        self.assertNotIn('contractReceived',self.size())
        # Absolute target corrections are reversible, and never charge old stock.
        for amount, pending in [(60,10),(68,2),(0,70),(70,0)]:
            result=self.save(pendingInspectionBySize={'M':amount})
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual((self.size()['pendingInspection'],self.size()['contractPending']),(amount,pending))


    def test_stock_only_workbook_ignores_new_inspection_stage(self):
        self.prepare()
        book=load_workbook(io.BytesIO(self.call('inventory/export').data))
        book.active['H2']=11
        out=io.BytesIO();book.save(out)
        self.assertEqual(self.save(pendingInspectionBySize={'M':20}).status_code,200)
        preview=self.upload('preview',out.getvalue())
        self.assertEqual(preview.json['errors'],[])
        self.assertEqual(preview.json['summary']['changedFieldCount'],1)
        result=self.upload('confirm',out.getvalue(),preview.json['fileHash'])
        self.assertEqual(result.status_code,200,result.json)
        s=self.size()
        self.assertEqual((s['stock'],s['contractPending'],s['pendingInspection']),(11,80,20))

    def test_contract_extension_adds_only_delta_to_real_pending(self):
        contract=self.prepare({'M':70})
        self.assertEqual(self.save(pendingInspectionBySize={'M':20}).status_code,200)
        body={**contract,'requestId':str(uuid.uuid4()),'revision':contract['revision']}
        body['items'][0]['quantities']['M']=100
        result=self.call('contracts/1','PUT',body)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual((self.size()['pendingInspection'],self.size()['contractPending']),(20,80))

    def test_contract_adds_to_pending_and_does_not_count_other_color_or_old_qualified(self):
        db._fetch_one("UPDATE product_size_prices SET contract_pending=12,pending_inspection=7,pending_inbound=6 WHERE product_id=1 AND size_code='M' RETURNING id")
        other=db.get_product_by_id(2,include_contract_pending=True)
        body={'requestId':str(uuid.uuid4()),'partyA':'采购','partyB':'工厂','contractNo':'ADDITIVE',
              'styleImage':'/uploads/fixture.jpg','sizeChartImage':'/uploads/fixture.jpg','deliveryDate':'2026-11-20',
              'items':[{'productId':1,'quantities':{'M':70,'L':10}}]}
        result=self.call('contracts','POST',body)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(self.size()['contractPending'],82)
        self.assertEqual((self.size()['pendingInspection'],self.size()['pendingInbound']),(7,6))
        self.assertEqual(db.get_product_by_id(2,include_contract_pending=True),other)
        # Editing unrelated stock must not initialize the counter from old WIP.
        self.assertEqual(self.save(sizeStocks={'M':20}).status_code,200)
        self.assertNotIn('contractReceived',self.size())
        cancel=self.call('contracts/1/cancel','POST',{'revision':result.json['item']['revision'],'deductions':[{'productId':1,'sizeCode':'M','balance':82,'quantity':70},{'productId':1,'sizeCode':'L','balance':16,'quantity':10}]})
        self.assertEqual(cancel.status_code,200,cancel.json)
        self.assertEqual(self.size()['contractPending'],12)

    def test_existing_null_counter_and_repaired_counter_survive_registration(self):
        self.prepare({'M':70})
        db._fetch_one("UPDATE product_size_prices SET pending_inspection=13 WHERE product_id=1 AND size_code='M' RETURNING id")
        db._fetch_one("UPDATE inventory_overdelivery SET normal_received=NULL WHERE product_id=1 AND size_code='M' RETURNING product_id")
        self.assertNotIn('contractReceived',self.size())
        self.assertEqual(self.save(sizeStocks={'M':20}).status_code,200)
        self.assertNotIn('contractReceived',self.size())
        self.assertEqual(self.save(pendingInboundBySize={'M':13}).status_code,200)
        self.assertEqual(self.receive().status_code,200)
        self.assertEqual(self.save(pendingInspectionBySize={'M':68}).status_code,200)
        self.assertEqual(self.size()['contractPending'],2)

    def test_combined_arrival_and_qualification_matches_preview_and_is_atomic(self):
        self.prepare({'M':70,'L':7})
        before=self.detail()
        # Paired absolute targets are essential when inspection ends at zero.
        result=self.save(contractPendingBySize={'M':10},pendingInspectionBySize={'M':0},pendingInboundBySize={'M':60})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual((self.size()['contractPending'],self.size()['pendingInspection'],self.size()['pendingInbound']),(10,0,60))
        saved=self.detail()
        result=self.save(pendingInspectionBySize={'M':8,'L':9},pendingInboundBySize={'M':60,'L':0})
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.detail(),saved)
        stale=self.call('inventory/1','PUT',{'version':before['version'],'sizeStocks':{},'pendingInspectionBySize':{'M':0},'pendingInboundBySize':{'M':68}})
        self.assertEqual(stale.status_code,409)
        self.assertEqual(self.detail(),saved)
        self.assertEqual(self.save(pendingInspectionBySize={'M':0},pendingInboundBySize={'M':0}).status_code,200)
        self.assertEqual(self.size()['contractPending'],70)

    def test_first_contract_failure_rolls_back_initialized_counters(self):
        db._fetch_one('UPDATE product_size_prices SET contract_pending=0 WHERE product_id=1 RETURNING id')
        before=self.detail()
        ledgers=db._fetch_all('SELECT * FROM inventory_overdelivery WHERE product_id=1 ORDER BY size_code')
        body={'requestId':str(uuid.uuid4()),'partyA':'采购','partyB':'工厂','contractNo':'ROLLBACK',
              'styleImage':'/uploads/fixture.jpg','sizeChartImage':'/uploads/fixture.jpg','deliveryDate':'2026-11-20',
              'items':[{'productId':1,'quantities':{'M':70}}]}
        with patch('private_media.bind_current',side_effect=ValueError('attachment validation failed')):
            result=self.call('contracts','POST',body)
        self.assertEqual(result.status_code,400,result.json)
        self.assertEqual(self.detail(),before)
        self.assertEqual(db._fetch_all('SELECT * FROM inventory_overdelivery WHERE product_id=1 ORDER BY size_code'),ledgers)

    def test_empty_product_deletion_preserves_cumulative_history(self):
        self.prepare();self.save(pendingInspectionBySize={'M':115})
        self.save(pendingInspectionBySize={'M':0},sizeStocks={'M':0,'L':0,'Tall XL':0})
        self.assertEqual(self.save(contractPendingBySize={'M':0}).status_code,200)
        db._fetch_one('DELETE FROM order_items WHERE product_id=1 RETURNING id')
        self.assertEqual(self.call('products/1','DELETE').status_code,400)
        self.assertTrue(db._fetch_one('SELECT is_active FROM products WHERE id=1')['is_active'])
        self.assertEqual(self.call('contracts/1/cancel','POST',{'revision':1,'deductions':[]}).status_code,200)
        result=self.call('products/1','DELETE')
        self.assertEqual(result.status_code,200,result.json)
        self.assertFalse(db._fetch_one('SELECT is_active FROM products WHERE id=1')['is_active'])
        self.assertEqual(db._fetch_one("SELECT used FROM inventory_overdelivery WHERE product_id=1 AND size_code='M'")['used'],15)
        self.assertEqual(self.size()['overdeliveryUsed'],15)

    def test_release_probe_is_read_only_with_populated_ledger(self):
        self.prepare();self.save(pendingInspectionBySize={'M':115})
        before=self.detail()
        audit=db._fetch_one('SELECT count(*) AS n FROM admin_audit_logs')['n']
        probe=Path(__file__).resolve().parents[1]/'scripts/verify-inventory-overdelivery.py'
        result=subprocess.run([sys.executable,str(probe),'admin-backend'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['readOnly'])
        self.assertEqual(self.detail(),before)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM admin_audit_logs')['n'],audit)


class ReachablePolicyTest(unittest.TestCase):
    def test_all_small_reachable_states_conserve_normal_and_extra_sources(self):
        # Exhaustive real transitions, not a second copy of the policy algorithm.
        # Includes corrections, qualified reversals, receipts and defect returns.
        names=('contract_pending','pending_inspection','pending_inbound','overdeliveryUsed',
               'overdeliveryInspection','overdeliveryQualified')
        start=(7,0,0,0,0,0);pending=[(start,0)];seen={start};transitions=0
        def accept(values, previous, depth, stock_added=0):
            nonlocal transitions
            p,i,b,u,ei,eb=values
            self.assertTrue(all(v>=0 for v in values),values)
            self.assertLessEqual(ei,i);self.assertLessEqual(eb,b)
            self.assertLessEqual(ei+eb,u)
            self.assertGreaterEqual(u,previous[3])
            self.assertEqual(p+i+b-ei-eb+stock_added,previous[0]+previous[1]+previous[2]-previous[4]-previous[5])
            transitions+=1
            if depth < 4 and values not in seen:seen.add(values);pending.append((values,depth+1))
        while pending:
            previous,depth=pending.pop();row=dict(zip(names,previous))
            for ni in range(9):
                for nb in range(9):
                    try:p,i,b,state=policy.transition(row,{'pendingInspection':ni,'pendingInbound':nb})
                    except ValueError:continue
                    accept((p,i,b,state['overdeliveryUsed'],state['overdeliveryInspection'],state['overdeliveryQualified']),previous,depth)
            if row['pending_inbound']:
                values=list(previous);values[2]=0;values[5]=0
                accept(tuple(values),previous,depth,previous[2]-previous[5])
            for quantity in range(1,row['pending_inspection']+1):
                state=policy.return_preview(row,quantity)
                accept((state['contractAfter'],state['inspectionAfter'],row['pending_inbound'],
                        state['overdeliveryUsed'],state['overdeliveryInspection'],state['overdeliveryQualified']),previous,depth)
        self.assertGreater(len(seen),50);self.assertGreater(transitions,1000)


if __name__=='__main__': unittest.main()
