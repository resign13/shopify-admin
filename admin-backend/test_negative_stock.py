"""Signed-stock regressions; only the isolated database guarded by test_workbench."""
import copy
import importlib.util
import io
from pathlib import Path
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from openpyxl import load_workbook
from test_workbench import seed, application, db
import test_workbench as workbench_tests
import test_orders as order_tests
import inventory_policy


class NegativeStockTest(unittest.TestCase):
    call = order_tests.AdminOrdersTest.call
    payload = order_tests.AdminOrdersTest.payload
    stock = order_tests.AdminOrdersTest.stock
    workbook = workbench_tests.WorkbenchTest.workbook
    upload = workbench_tests.WorkbenchTest.upload

    def setUp(self):
        self.tokens, _ = seed()
        self.app = application.app
        self.app.config['TESTING'] = True

    def set_stock(self, **sizes):
        db.update_product_inventory(1, sizes)

    def balance(self, size='M'):
        return next(s['stock'] for s in self.stock()['sizePrices'] if s['sizeCode'] == size)

    def create(self, quantity=5, role='admin'):
        body = self.payload()
        body['items'] = [{'productId':1,'sizeCode':'M','quantity':quantity,'unitPrice':1}]
        response = self.call('orders', 'POST', body, role)
        self.assertEqual(response.status_code, 200, response.json)
        return self.call(f"orders/{response.json['order']['id']}").json['order']

    def update(self, order, **fields):
        response = self.call(f"orders/{order['id']}/details", 'PUT', {**order, **fields})
        self.assertEqual(response.status_code, 200, response.json)
        return self.call(f"orders/{order['id']}").json['order']

    def test_lifecycle_and_receipt_arithmetic(self):
        self.set_stock(M=0)
        order = self.create()
        self.assertEqual(self.balance(), -5)
        order['items'][0]['quantity'] = 8
        order = self.update(order)
        self.assertEqual(self.balance(), -8)
        order['items'][0]['quantity'] = 6
        order = self.update(order)
        self.assertEqual(self.balance(), -6)
        order = self.update(order, note='only metadata')
        self.assertEqual(self.balance(), -6)
        response = self.call('inventory/1/receive', 'POST', {'version':self.stock()['version'], 'requestId':str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.balance(), -2)
        order = self.update(order, status='cancelled')
        self.assertEqual(self.balance(), 4)
        order = self.update(order, note='cancelled metadata')
        self.assertEqual(self.balance(), 4)
        response = self.call(f"orders/{order['id']}", 'PUT', {'status':'paid'})
        self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(self.call('orders', 'DELETE', {'orderIds':[order['id']]}).status_code, 200)
        self.assertEqual(self.balance(), 4)

    def test_negative_continuation_size_switch_and_sales(self):
        self.set_stock(M=1)
        order = self.create(5, 'sales')
        self.assertEqual(self.balance(), -4)
        self.create(3)
        self.assertEqual(self.balance(), -7)
        order['items'][0]['sizeCode'] = 'Tall XL'
        order = self.update(order)
        self.assertEqual(self.balance(), -2)
        self.assertEqual(self.balance('Tall XL'), 5)
        self.assertEqual(self.stock()['stock'], 13)
        for role in ['warehouse','customer']:
            self.assertEqual(self.call('orders','POST',self.payload(),role).status_code,403)

    def test_concurrent_orders_and_replay(self):
        self.set_stock(M=0)
        bodies = [self.payload() for _ in range(2)]
        for b in bodies: b['items'] = [{'productId':1,'sizeCode':'M','quantity':5,'unitPrice':1}]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda b:self.call('orders','POST',b), [bodies[0],bodies[1],bodies[0],bodies[1]]))
        self.assertTrue(all(r.status_code==200 for r in results), [r.json for r in results])
        self.assertEqual(len({r.json['order']['id'] for r in results}),2)
        self.assertEqual(self.balance(),-10)

    def test_concurrent_cancel_edit_and_delete(self):
        self.set_stock(M=0)
        order = self.create()
        edit = copy.deepcopy(order);edit['items'][0]['quantity']=8
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda body:self.call(f"orders/{order['id']}/details",'PUT',body), [edit,{**order,'status':'cancelled'}]))
        self.assertEqual(sorted(r.status_code for r in results),[200,409])
        latest=self.call(f"orders/{order['id']}").json['order']
        expected = 0 if latest['status']=='cancelled' else -8
        self.assertEqual(self.balance(),expected)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(self.call,f"orders/{order['id']}",'PUT',{'status':'cancelled'})
            b=pool.submit(self.call,'orders','DELETE',{'orderIds':[order['id']]})
            results=[a.result(),b.result()]
        self.assertTrue(all(r.status_code in [200,400,404] for r in results),[r.json for r in results])
        self.assertEqual(self.balance(),0)

    def test_fulfilled_deletion_and_transition_guards(self):
        self.set_stock(M=0)
        for status in ['shipped','completed']:
            order=self.create(2)
            order=self.update(order,status=status,trackingNo='FIXTURE')
            before=self.balance()
            for target in ['paid','pending_payment','allocated','cancelled']:
                self.assertEqual(self.call(f"orders/{order['id']}",'PUT',{'status':target}).status_code,400)
            self.assertEqual(self.call('orders','DELETE',{'orderIds':[order['id']]}).status_code,200)
            self.assertEqual(self.balance(),before)
        order=self.create(3);before=self.balance()
        self.assertEqual(self.call('orders','DELETE',{'orderIds':[order['id']]}).status_code,200)
        self.assertEqual(self.balance(),before+3)

    def test_internal_metrics_public_boundary_and_dashboard(self):
        self.set_stock(M=-10,L=10,**{'Tall XL':0})
        internal=self.stock()
        self.assertEqual((internal['stock'],internal['availableStock'],internal['shortageUnits'],internal['shortageSizeCount']),(0,10,10,1))
        for path in ['inventory/1','inventory?page=1']:
            public=self.call(path,role='customer').json
            text=str(public)
            self.assertNotIn('shortageUnits',text)
            self.assertNotIn('shortageSizeCount',text)
            self.assertNotIn("'stock': -",text)
        self.assertEqual(self.call('inventory/1',role='customer').json['product']['stock'],10)
        filtered=self.call('inventory?stock=backordered').json
        self.assertEqual(filtered['total'],1)
        self.assertEqual(filtered['summary']['shortageUnits'],10)
        dashboard=self.call('dashboard?view=style-performance&dateFrom=2026-09-18&dateTo=2026-09-18&risk=backordered').json
        self.assertEqual(dashboard['items'][0]['risk'],'backordered')
        self.assertEqual(dashboard['summary']['availableStock'],70)
        self.assertEqual(dashboard['summary']['shortageUnits'],10)
        with application.app.test_request_context():
            public=application.serialize_product(internal,'en')
        self.assertEqual(public['stock'],10)
        self.assertEqual(next(s['stock'] for s in public['sizePrices'] if s['sizeCode']=='M'),0)

    def test_manual_excel_versions_audit_and_bounds(self):
        version=self.stock()['version']
        body={'version':version,'sizeStocks':{'M':-6}}
        self.assertEqual(self.call('inventory/1','PUT',body).status_code,200)
        self.assertEqual(self.call('inventory/1','PUT',body).status_code,409)
        raw=self.workbook(lambda sheet:setattr(sheet['H2'],'value',-9))
        preview=self.upload('preview',raw)
        self.assertEqual(preview.json['errors'],[],preview.json)
        response=self.upload('confirm',raw,preview.json['fileHash'])
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.balance(),-9)
        sheet=load_workbook(io.BytesIO(self.workbook())).active
        self.assertEqual(sheet['H2'].value,-9)
        self.assertEqual(sheet['J2'].value,-9)
        for field in ['contractPendingBySize','pendingInboundBySize','pendingInspectionBySize']:
            self.assertEqual(self.call('inventory/1','PUT',{'sizeStocks':{},field:{'M':-1}}).status_code,400)
        self.assertEqual(self.call('inventory/1','PUT',{'sizeStocks':{'M':-2147483649}}).status_code,400)
        self.set_stock(M=-2147483648,L=0,**{'Tall XL':0})
        self.assertEqual(self.call('orders','POST',self.payload()).status_code,400)
        self.assertEqual(self.balance(),-2147483648)
        self.assertGreater(db._fetch_one("SELECT COUNT(*) AS n FROM admin_audit_logs WHERE entity_table='product_size_prices'")['n'],0)

    def test_product_save_size_protection_and_hidden_debt(self):
        self.set_stock(M=-5)
        p=self.call('products/1').json['product'];p.update(title=p['name']['zh'],familyCode=p['colorGroup'])
        response=self.call('products/save-group','POST',{'products':[p],'versions':{'1':p['version']}})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.balance(),-5)
        db._fetch_one('UPDATE product_size_prices SET contract_pending=0,pending_inbound=0,pending_inspection=0 WHERE product_id=1 RETURNING id')
        p=self.call('products/1').json['product'];p.update(title=p['name']['zh'],familyCode=p['colorGroup'])
        for size in ['M','L']:
            # M has debt/order references; L is given an open order reference below.
            if size=='L':
                order=self.create(1);order['items'][0]['sizeCode']='L';self.update(order)
            modified=copy.deepcopy(p);modified['sizePrices']=[s for s in p['sizePrices'] if s['sizeCode']!=size];modified['sizes']=[s['sizeCode'] for s in modified['sizePrices']]
            with self.assertRaises(ValueError):db.update_product(1,modified)
        db.delete_product(1)
        self.assertEqual(self.call('inventory?stock=backordered').json['total'],1)
        self.assertEqual(self.balance(),-5)
        response=self.call('orders','POST',self.payload())
        self.assertEqual(response.status_code,400,response.json)

    def test_legacy_constraints_backfill_and_history_snapshot(self):
        with db.get_connection() as conn:
            conn.execute('ALTER TABLE products ADD CONSTRAINT fixture_stock_nonnegative CHECK(stock>=0)')
            conn.execute('ALTER TABLE product_size_prices ADD CONSTRAINT fixture_size_nonnegative CHECK(stock>=0)')
            conn.execute("DELETE FROM inventory_policy_versions WHERE version='signed-stock-v1'")
            conn.execute('TRUNCATE inventory_legacy_cancelled_orders')
        db.ensure_database_ready()
        self.assertEqual(self.balance(),10)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM inventory_legacy_cancelled_orders')['n'],1)
        self.set_stock(M=-10,L=10,**{'Tall XL':0})
        db.ensure_database_ready()
        self.assertEqual(self.balance(),-10)
        self.assertEqual(self.stock()['stock'],0)
        with db.get_connection() as conn:
            with self.assertRaises(Exception):
                conn.execute('UPDATE product_size_prices SET pending_inbound=-1 WHERE product_id=1')
        # Simulate a pre-size-stock database: only this first introduction may distribute stock.
        with db.get_connection() as conn:
            conn.execute('UPDATE products SET stock=30')
            conn.execute('ALTER TABLE product_size_prices DROP COLUMN stock')
        db.ensure_database_ready()
        self.assertEqual(self.balance(),10)
        self.assertEqual(self.stock()['stock'],30)

    def test_receipt_zero_surplus_parent_overflow_and_report(self):
        self.set_stock(M=-4)
        def receive():
            response=self.call('inventory/1/receive','POST',{'version':self.stock()['version'],'requestId':str(uuid.uuid4())})
            self.assertEqual(response.status_code,200,response.json)
        receive()
        self.assertEqual(self.balance(),0)
        p=self.stock()
        response=self.call('inventory/1','PUT',{'version':p['version'],'sizeStocks':{},'pendingInboundBySize':{'M':3}})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.balance(),0)
        receive()
        self.assertEqual(self.balance(),3)
        before=self.stock()['stock']
        response=self.call('inventory/1','PUT',{'sizeStocks':{'M':2147483647,'L':1}})
        self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(self.stock()['stock'],before)
        self.set_stock(M=-8)
        public=inventory_policy.public_inventory(self.stock())
        color=next(c for c in public['colorOptions'] if c['id']==1)
        self.assertEqual(color['stock'],22)
        from tempfile import TemporaryDirectory
        from report_legacy_cancelled_inventory import export_report
        with TemporaryDirectory() as directory:
            output=Path(directory)/'report.csv'
            export_report(output)
            self.assertIn('review_note',output.read_text('utf-8-sig'))
        self.assertEqual(self.balance(),-8)

    def test_repeated_migrations_and_storefront_purchase(self):
        self.set_stock(M=-10,L=10,**{'Tall XL':0})
        source=Path(__file__).resolve().parents[2]/'shopify'/'storefront-backend'
        if not source.exists():self.skipTest('Sibling storefront checkout required for cross-service regression')
        self.assertEqual((source/'inventory_policy.py').read_bytes(),Path(inventory_policy.__file__).read_bytes())
        spec=importlib.util.spec_from_file_location('storefront_test_db',source/'db.py')
        store=importlib.util.module_from_spec(spec);spec.loader.exec_module(store)
        for _ in range(2):
            db.ensure_database_ready();store.ensure_database_ready()
            self.assertEqual(self.balance(),-10)
            self.assertEqual(self.balance('L'),10)
        public=store.get_product_by_slug('gt-2026-1')
        self.assertEqual(public['stock'],10)
        payload={'userId':1,'contactName':'Fixture','phone':'123','country':'Germany','shippingAddress':'Fixture','items':[{'productId':1,'sizeCode':'L','quantity':2}]}
        order=store.create_order(payload)
        self.assertEqual(self.balance('L'),8)
        for size in ['M','','INVALID']:
            body=copy.deepcopy(payload);body['items'][0]['sizeCode']=size;body['allowNegativeStock']=True
            with self.assertRaises((ValueError,RuntimeError,LookupError)):store.create_order(body)
        store.cancel_order(order['id'],user_id=1);store.cancel_order(order['id'],user_id=1)
        self.assertEqual(self.balance('L'),10)
        legacy={**payload,'productId':1,'sizeCode':'L','quantity':2}
        db.create_order(legacy)
        self.assertEqual(self.balance('L'),8)
        for size in ['M','']:
            with self.assertRaises((ValueError,RuntimeError,LookupError)):db.create_order({**legacy,'sizeCode':size,'allowNegativeStock':True})


if __name__=='__main__':unittest.main()
