"""Order editing tests use the guarded synthetic database from test_workbench."""
import copy
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from test_workbench import seed, application, db


class AdminOrdersTest(unittest.TestCase):
    def test_matrix_exports_use_local_images_and_preserve_size_quantities(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from PIL import Image
        from openpyxl import load_workbook
        with TemporaryDirectory() as directory:
            Image.new('RGB', (600, 900), '#335577').save(Path(directory) / 'matrix.jpg')
            order = {'orderNo': 'MATRIX-FIXTURE', 'items': [
                {'productId': 1, 'sku': 'BLUE', 'sizeCode': size, 'quantity': qty,
                 'image': 'https://img.smawell.shop/uploads/matrix.jpg'}
                for size, qty in [('S', 2), ('30/M', 3), ('XXL', 4)]]}
            for builder in [application.build_orders_export, application.build_orders_sheet_export]:
                with patch.object(application, 'UPLOAD_DIR', Path(directory)), application.app.test_request_context('/api/admin/orders/export'):
                    sheet = load_workbook(builder([order])).active
                    self.assertEqual(len(sheet._images), 1)
                    self.assertEqual([sheet.cell(6, c).value for c in [3, 4, 7, 8]], [2, 3, 4, 9])

    def setUp(self):
        self.tokens, _ = seed()
        application.app.config['TESTING'] = True

    def call(self, path, method='GET', body=None, role='admin'):
        with application.app.test_client() as client:
            return client.open('/api/admin/'+path, method=method, json=body,
                               headers={'Authorization':'Bearer '+self.tokens[role]})

    def payload(self):
        return {'requestId':str(uuid.uuid4()), 'userId':1, 'contactName':'Alex', 'phone':'123456',
                'country':'Germany', 'address':'18 Market Street', 'city':'Berlin', 'shippingFee':12.5,
                'items':[{'productId':1,'sizeCode':'M','quantity':2,'unitPrice':20},
                         {'productId':1,'sizeCode':'L','quantity':3,'unitPrice':25}]}

    def create(self):
        response=self.call('orders','POST',self.payload())
        self.assertEqual(response.status_code,200,response.json)
        return self.call(f"orders/{response.json['order']['id']}").json['order']

    def stock(self):
        return self.call('inventory/1').json['product']

    def test_create_and_concurrent_replay(self):
        body=self.payload()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.call('orders','POST',body),range(2)))
        self.assertTrue(all(r.status_code==200 for r in results),[r.json for r in results])
        self.assertEqual(len({r.json['order']['id'] for r in results}),1)
        self.assertEqual(sum(r.json['replayed'] for r in results),1)
        self.assertEqual(results[0].json['order']['totalAmount'],127.5)
        self.assertEqual(self.stock()['stock'],25)
        self.assertEqual(sum(s['contractPending'] for s in self.stock()['sizePrices']),21)
        self.assertEqual(sum(s['pendingInbound'] for s in self.stock()['sizePrices']),6)
        self.assertEqual(db._fetch_one("SELECT COUNT(*) AS n FROM admin_audit_logs WHERE entity_table='orders' AND action='INSERT'")['n'],1)
        body['note']='changed body'
        self.assertEqual(self.call('orders','POST',body).status_code,400)

    def test_edit_delta_price_contact_and_stale_version(self):
        order=self.create();body=copy.deepcopy(order)
        body['items'][0]['quantity']=4
        body['items'][1]['quantity']=1
        body['items'][0]['unitPrice']=22
        body['address']='New address';body['contactName']='Updated contact';body['note']='updated'
        response=self.call(f"orders/{order['id']}/details",'PUT',body)
        self.assertEqual(response.status_code,200,response.json)
        updated=response.json['order']
        self.assertEqual(updated['totalAmount'],125.5)
        self.assertIn('New address',updated['shippingAddress'])
        self.assertEqual(updated['contactName'],'Updated contact')
        sizes={r['sizeCode']:r['stock'] for r in self.stock()['sizePrices']}
        self.assertEqual(sizes,{'M':6,'L':9,'Tall XL':10})
        self.assertEqual(self.stock()['stock'],25)
        self.assertEqual(self.call(f"orders/{order['id']}/details",'PUT',body).status_code,409)
        body=self.call(f"orders/{order['id']}").json['order'];body['items']=body['items'][:1]
        self.assertEqual(self.call(f"orders/{order['id']}/details",'PUT',body).status_code,200)
        self.assertEqual(self.stock()['stock'],26)

    def test_shortage_and_invalid_input_rollback(self):
        for modify in [lambda b:b['items'][1].update(quantity=100),
                       lambda b:b['items'][0].update(quantity=1.5),
                       lambda b:b['items'][0].update(sizeCode='UNKNOWN'),
                       lambda b:b['items'][0].update(unitPrice=-1),
                       lambda b:b['items'].append(dict(b['items'][0])),
                       lambda b:b.update(userId=999),lambda b:b.update(shippingFee=-1)]:
            body=self.payload();modify(body)
            response=self.call('orders','POST',body)
            self.assertEqual(response.status_code,400,response.json)
            self.assertEqual(self.stock()['stock'],30)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM orders')['n'],4)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM admin_audit_logs')['n'],0)

    def test_allocated_status_filter_export_and_migration(self):
        order=self.create()
        response=self.call(f"orders/{order['id']}",'PUT',{'status':'allocated','shippingFee':12.5,'version':order['version']},role='warehouse')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.stock()['stock'],25)
        result=self.call('orders?page=1&status=allocated').json
        self.assertEqual(result['total'],1)
        self.assertEqual(result['statusCounts']['allocated'],1)
        self.assertEqual(self.call('orders/export?view=workbench&status=allocated&includeImages=0').status_code,200)
        with db.get_connection() as conn:
            with conn.cursor() as cur: db._migrate_order_status_values(cur)
        self.assertEqual(self.call(f"orders/{order['id']}").json['order']['status'],'allocated')
        self.assertEqual(self.call(f"orders/{order['id']}",'PUT',{'status':'allocated','shippingFee':-1}).status_code,400)

    def test_permissions_and_fulfilled_lines(self):
        for role in ['warehouse','customer']:
            self.assertEqual(self.call('orders','POST',self.payload(),role).status_code,403)
            self.assertEqual(self.call('orders/1/details','PUT',self.payload(),role).status_code,403)
            self.assertEqual(self.call('orders/customers',role=role).status_code,403)
        self.assertEqual(self.call('orders/customers?keyword=Northline',role='sales').json['total'],1)
        order=self.create()
        self.assertEqual(self.call(f"orders/{order['id']}",'PUT',{'status':'shipped','trackingNo':'TEST-TRACK','shippingFee':12.5}).status_code,200)
        body=self.call(f"orders/{order['id']}").json['order'];body['items'][0]['quantity']=5
        self.assertEqual(self.call(f"orders/{order['id']}/details",'PUT',body).status_code,400)
        body['items'][0]['quantity']=2;body['note']='Contact update after shipment'
        self.assertEqual(self.call(f"orders/{order['id']}/details",'PUT',body).status_code,200)
        self.assertEqual(self.stock()['stock'],25)


if __name__=='__main__':
    unittest.main()
