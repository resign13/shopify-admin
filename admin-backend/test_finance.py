"""Finance regression writes are restricted by test_workbench to local *_test databases."""
import copy
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import BytesIO
import unittest
import uuid
from unittest.mock import patch
from openpyxl import load_workbook
from werkzeug.security import generate_password_hash
import test_orders as helpers
from test_workbench import db, application
import finance


class FinanceTest(unittest.TestCase):
    call=helpers.AdminOrdersTest.call
    payload=helpers.AdminOrdersTest.payload
    stock=helpers.AdminOrdersTest.stock

    def clear(self):
        with db.get_connection() as conn:
            conn.execute('TRUNCATE finance_cost_history,finance_cost_versions,finance_cost_audit,finance_cost_receipts,finance_settings RESTART IDENTITY')

    def setUp(self):
        self.clear();helpers.AdminOrdersTest.setUp(self)
        user=db.create_admin_user({'name':'Finance fixture','email':'finance@gingtto.test','passwordHash':generate_password_hash('Fixture-only',method='pbkdf2:sha256:1000'),'status':'active','role':'finance'})
        self.finance_id=user['id'];self.tokens['finance']=db.create_admin_session(user['id'])

    def tearDown(self): self.clear()

    def post(self,path,body,role='finance'):
        return self.call('finance/'+path,'POST',body,role)

    def change(self,pid=1,size='M',cost='10.00',when='2026-09-01'):
        row=db._fetch_one('SELECT revision FROM finance_cost_versions WHERE product_id=%s AND size_code=%s',(pid,size))
        return {'effectiveDate':when,'changes':[{'productId':pid,'sizeCode':size,'costCny':cost,'version':str(row['revision'] if row else 0)}]}

    def prepared(self,body):
        response=self.post('costs/preview',body)
        self.assertEqual(response.status_code,200,response.json)
        return {**body,'previewHash':response.json['previewHash'],'requestId':str(uuid.uuid4())}

    def save_cost(self,**kwargs):
        response=self.post('costs/save',self.prepared(self.change(**kwargs)))
        self.assertEqual(response.status_code,200,response.json)

    def query(self,**kwargs):
        body={'dateFrom':'2026-09-01','dateTo':'2026-09-30','exchangeRate':'7.123456',**kwargs}
        response=self.post('reports/query',body)
        self.assertEqual(response.status_code,200,response.json)
        return response.json

    def test_roles_permissions_and_private_options(self):
        for role in ('sales','warehouse','customer'):
            for path in ('options','costs','costs/history?productId=1&sizeCode=M','costs/history?styleCode=GT-2026'):
                self.assertEqual(self.call('finance/'+path,role=role).status_code,403)
            for path in ('costs/preview','costs/save','reports/query','reports/export'):
                self.assertEqual(self.post(path,{},role).status_code,403)
        self.assertEqual(self.call('finance/options',role='finance').status_code,200)
        for path in ('orders','inventory','products','admin-users','store-users'):
            self.assertEqual(self.call(path,role='finance').status_code,403)
        self.assertEqual(self.call('orders','POST',self.payload(),'finance').status_code,403)
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE id=%s RETURNING id",(self.finance_id,))
        self.assertEqual(self.call('finance/options',role='finance').status_code,403)
        self.assertEqual(self.call('finance/options').status_code,200)
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\"]'::jsonb WHERE id=1 RETURNING id")
        self.assertEqual(self.call('finance/options').status_code,403)

    def test_dates_missing_zero_and_corrected_history(self):
        initial=self.query();self.assertEqual(initial['summary']['quantity'],9)
        self.assertEqual(initial['summary']['missingQuantity'],9);self.assertIsNone(initial['summary']['profitCny'])
        self.save_cost(cost='0.00',when='2026-09-17')
        self.save_cost(cost='11.25',when='2026-09-18')
        self.save_cost(pid=2,cost='5',when='2026-09-01')
        result=self.query();summary=result['summary']
        self.assertEqual(summary['knownCostCny'],'60.00')
        self.assertEqual(summary['missingQuantity'],2)  # completed Sept 16 predates first cost
        group=next(r for r in result['items'] if r['productId']==1)
        self.assertEqual(group['minCostCny'],'11.25')  # UTC Sept 17 16:30 is Sept 18 Beijing
        self.save_cost(cost='8',when='2026-09-01')
        result=self.query();self.assertEqual(result['summary']['totalCostCny'],'76.00')
        self.save_cost(cost='12',when='2026-09-18')
        self.assertEqual(self.query()['summary']['totalCostCny'],'79.00')
        history=self.call('finance/costs/history?productId=1&sizeCode=M',role='finance').json
        self.assertEqual(history['total'],4);self.assertEqual(len(history['timeline']),3)
        self.assertEqual(history['items'][0]['before']['costCny'],'11.25')

    def test_shared_exchange_rate_save_validation_retry_and_migration(self):
        initial={'exchangeRate':None,'version':'0'}
        self.assertEqual(self.call('finance/preferences',role='finance').json,initial)
        stock=self.stock();orders=db._fetch_one('SELECT count(*) AS n FROM orders')['n']
        for value in ('0','-1','NaN','Infinity','7.1234567',True,None,'', '10000000000'):
            response=self.call('finance/preferences','PUT',{'exchangeRate':value,'version':'0'},'finance')
            self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(self.call('finance/preferences','PUT',[], 'finance').status_code,400)
        first={'exchangeRate':'7.123456','version':'0'}
        response=self.call('finance/preferences','PUT',first,'finance')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json,{'exchangeRate':'7.123456','version':'1'})
        self.assertEqual(self.call('finance/preferences').json,response.json)  # Other account, same setting.
        self.assertEqual(self.call('finance/preferences','PUT',first,'finance').json,response.json)  # Lost response retry.
        changed=self.call('finance/preferences','PUT',{'exchangeRate':'7.000001','version':'1'})
        self.assertEqual(changed.status_code,200,changed.json)
        self.assertEqual(self.call('finance/preferences',role='finance').json,changed.json)
        self.assertEqual(self.call('finance/preferences','PUT',{'exchangeRate':'6.90','version':'1'},'finance').status_code,409)
        with db.get_connection() as conn:finance.migrate(conn.cursor());finance.migrate(conn.cursor())
        self.assertEqual(self.call('finance/preferences',role='finance').json,{'exchangeRate':'7.000001','version':'2'})
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM finance_settings')['n'],1)
        self.assertEqual(self.stock(),stock);self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM orders')['n'],orders)

    def test_shared_exchange_rate_concurrency_and_permissions(self):
        for role in ('sales','warehouse','customer'):
            self.assertEqual(self.call('finance/preferences',role=role).status_code,403)
            self.assertEqual(self.call('finance/preferences','PUT',{'exchangeRate':'7','version':'0'},role).status_code,403)
        def write(row):return self.call('finance/preferences','PUT',{'exchangeRate':row[1],'version':'0'},row[0])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(write,[('admin','7.1'),('finance','7.2')]))
        self.assertEqual(sorted(r.status_code for r in results),[200,409])
        winner=next(r.json for r in results if r.status_code==200)
        self.assertEqual(self.call('finance/preferences').json,winner)
        self.assertEqual(self.call('finance/preferences',role='finance').json,winner)
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE id=%s RETURNING id",(self.finance_id,))
        self.assertEqual(self.call('finance/preferences',role='finance').status_code,403)
        self.assertEqual(self.call('finance/preferences','PUT',{'exchangeRate':'8','version':'1'},'finance').status_code,403)
        self.assertEqual(self.call('finance/preferences').json,winner)

    def test_style_history_all_colors_sizes_and_saved_old_values(self):
        self.save_cost(cost='10');self.save_cost(size='L',cost='11');self.save_cost(pid=2,cost='12')
        self.save_cost(cost='15',when='2026-09-18');self.save_cost(cost='0',when='2026-09-18')
        response=self.call('finance/costs/history?styleCode=GT-2026',role='finance')
        self.assertEqual(response.status_code,200,response.json)
        history=response.json
        self.assertEqual(history['total'],5);self.assertEqual(history['pageSize'],20)
        self.assertEqual(len(history['options']['variants']),3);self.assertIn('Tall XL',history['options']['sizes'])
        self.assertEqual((history['items'][0]['oldCostCny'],history['items'][0]['costCny']),('15.00','0.00'))
        self.assertEqual((history['items'][1]['oldCostCny'],history['items'][1]['costCny']),('10.00','15.00'))
        self.assertIsNone(history['items'][-1]['oldCostCny'])
        filtered=self.call('finance/costs/history?styleCode=GT-2026&productId=1&sizeCode=M',role='finance').json
        self.assertEqual(filtered['total'],3)
        self.assertTrue(all(r['productId']==1 and r['sizeCode']=='M' for r in filtered['items']))
        self.assertEqual(len(filtered['options']['variants']),3)  # Filtering does not erase other choices.
        legacy=self.call('finance/costs/history?productId=1&sizeCode=M',role='finance').json
        self.assertEqual(legacy['total'],3);self.assertEqual(legacy['timeline'][0]['costCny'],'0.00')
        self.assertEqual(self.call('finance/costs?keyword=长标题测试',role='finance').json['total'],0)
        self.assertEqual(self.call('finance/costs?keyword=GT-2026-1',role='finance').json['total'],1)

    def test_style_history_removed_sizes_deleted_colors_and_canonical_scope(self):
        self.save_cost(size='L',cost='19');self.save_cost(pid=2,cost='20');self.save_cost(pid=3,cost='21')
        with db.get_connection() as conn:
            conn.execute("DELETE FROM product_size_prices WHERE product_id=1 AND size_code='L'")
            conn.execute("UPDATE products SET style_code='OTHER-STYLE' WHERE id=2")
            conn.execute('DELETE FROM products WHERE id=3')
        history=self.call('finance/costs/history?styleCode=GT-2026',role='finance').json
        self.assertEqual(history['total'],2)
        self.assertEqual({r['productId'] for r in history['items']},{1,3})
        self.assertIn('L',history['options']['sizes'])
        deleted=next(v for v in history['options']['variants'] if v['productId']==3)
        self.assertTrue(deleted['deleted']);self.assertEqual(deleted['sku'],'GT-2026-3')
        moved=self.call('finance/costs/history?styleCode=OTHER-STYLE',role='finance').json
        self.assertEqual(moved['total'],1);self.assertEqual(moved['items'][0]['productId'],2)
        self.assertEqual(self.call('finance/costs/history?styleCode=GT-2026&productId=2',role='finance').status_code,400)
        # A deleted-only scope still has archived identity and size options.
        with db.get_connection() as conn:conn.execute("UPDATE products SET style_code='OTHER-STYLE' WHERE id=1")
        archived=self.call('finance/costs/history?styleCode=GT-2026',role='finance')
        self.assertEqual(archived.status_code,200,archived.json);self.assertEqual(archived.json['total'],1)
        self.assertTrue(all(v['deleted'] for v in archived.json['options']['variants']))

    def test_style_history_paging_validation_empty_and_read_only(self):
        for n in range(21):self.save_cost(cost=str(n))
        stock=self.stock()
        versions=db._fetch_all('SELECT * FROM finance_cost_versions ORDER BY product_id,size_code')
        first=self.call('finance/costs/history?styleCode=GT-2026',role='finance').json
        second=self.call('finance/costs/history?styleCode=GT-2026&page=2',role='finance').json
        self.assertEqual(first['total'],21);self.assertEqual(len(first['items']),20);self.assertEqual(len(second['items']),1)
        self.assertGreater(first['items'][-1]['id'],second['items'][0]['id'])
        empty=self.call('finance/costs/history?styleCode=NO-SUCH-STYLE',role='finance').json
        self.assertEqual(empty['total'],0);self.assertEqual(empty['options']['variants'],[])
        for query in ('styleCode=','styleCode=GT-2026&page=0','styleCode=GT-2026&pageSize=100','styleCode=GT-2026&productId=bad'):
            self.assertEqual(self.call('finance/costs/history?'+query,role='finance').status_code,400)
        self.assertEqual(self.stock(),stock)
        self.assertEqual(db._fetch_all('SELECT * FROM finance_cost_versions ORDER BY product_id,size_code'),versions)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM finance_cost_audit')['n'],21)

    def test_same_day_boundary_future_and_interval_preview(self):
        self.save_cost(when='2026-09-19',cost='20')
        body=self.change(when='2026-09-18',cost='15')
        r=self.post('costs/preview',body).json
        self.assertEqual(r['changes'][0]['untilExclusive'],'2026-09-19')
        self.assertEqual(r['affectedOrders'],2)
        self.assertEqual(self.query()['summary']['missingQuantity'],9)
        self.save_cost(when='2026-09-18',cost='15')
        response=self.query(dateFrom='2026-09-18',dateTo='2026-09-18')
        self.assertEqual(response['summary']['quantity'],6)
        self.assertEqual(response['summary']['knownCostCny'],'60.00')

    def test_decimal_sales_are_order_prices_and_shipping_excluded(self):
        self.save_cost(cost='10');self.save_cost(pid=2,cost='5')
        result=self.query();s=result['summary']
        self.assertEqual(s['salesUsd'],'269.10');self.assertEqual(s['totalCostCny'],'75.00')
        self.assertEqual(s['salesCny'],'1916.91');self.assertEqual(s['profitCny'],'1841.91')
        db._fetch_one('UPDATE product_size_prices SET price=900 WHERE product_id=1 RETURNING id')
        self.assertEqual(self.query()['summary'],s)

    def test_combined_customer_owner_multistyle_filters_only_matching_lines(self):
        db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id=1 RETURNING id')
        db._fetch_one("UPDATE products SET style_code='STYLE-A' WHERE id=1 RETURNING id")
        db._fetch_one("UPDATE products SET style_code='STYLE-B' WHERE id=2 RETURNING id")
        r=self.query(customerName='Alex',customerId=1,salespersonIds=[2],styleCodes='STYLE-A，NOT-HERE')
        self.assertEqual(r['summary']['quantity'],2);self.assertEqual(r['summary']['salesUsd'],'59.80')
        self.assertEqual(self.query(styleCodes=['STYLE-A','STYLE-B'])['summary']['quantity'],9)
        self.assertEqual(self.query(salespersonIds=['unassigned'])['summary']['quantity'],6)
        self.assertEqual(self.query(customerName='No match')['summary']['quantity'],0)
        self.assertEqual(self.query(statuses=['completed'])['summary']['quantity'],3)

    def test_save_is_atomic_idempotent_and_versioned_without_business_changes(self):
        stock=self.stock();count=db._fetch_one('SELECT count(*) AS n FROM orders')['n']
        body=self.prepared(self.change())
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:self.post('costs/save',body),range(2)))
        self.assertTrue(all(r.status_code==200 for r in responses),[r.json for r in responses])
        self.assertEqual(sum(r.json['replayed'] for r in responses),1)
        stale={**body,'requestId':str(uuid.uuid4())}
        self.assertEqual(self.post('costs/save',stale).status_code,409)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM finance_cost_audit')['n'],1)
        self.assertEqual(self.stock(),stock);self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM orders')['n'],count)
        batch=self.change(size='L');batch['changes']+=self.change(size='M')['changes'];batch['changes'][1]['version']='0'
        self.assertEqual(self.post('costs/save',{**batch,'requestId':str(uuid.uuid4())}).status_code,409)
        self.assertIsNone(db._fetch_one("SELECT * FROM finance_cost_history WHERE size_code='L'"))

    def test_save_audit_failure_rolls_back_every_finance_write(self):
        body=self.prepared(self.change());original=db._fetch_one
        def call(sql,*args,**kwargs):
            if 'INSERT INTO finance_cost_audit' in sql:raise ValueError('fixture audit failure')
            return original(sql,*args,**kwargs)
        with patch.object(db,'_fetch_one',side_effect=call):
            self.assertEqual(self.post('costs/save',body).status_code,400)
        for table in ('finance_cost_versions','finance_cost_history','finance_cost_receipts','finance_cost_audit'):
            self.assertEqual(db._fetch_one(f'SELECT count(*) AS n FROM {table}')['n'],0)

    def test_cost_matrix_preserves_groups_real_sizes_and_history_after_removed_sizes(self):
        self.save_cost();r=self.call('finance/costs?effectiveDate=2026-09-18',role='finance').json
        self.assertEqual(r['total'],1);self.assertEqual(len(r['items'][0]['variants']),3)
        self.assertIn('Tall XL',r['items'][0]['sizes'])
        with db.get_connection() as conn:
            conn.execute("DELETE FROM product_size_prices WHERE product_id=1 AND size_code='M'")
            conn.execute('UPDATE products SET is_active=false WHERE id=1')
        self.assertEqual(self.query()['summary']['knownCostCny'],'60.00')
        self.assertEqual(self.post('costs/preview',self.change()).status_code,409)
        with db.get_connection() as conn:finance.migrate(conn.cursor());finance.migrate(conn.cursor())
        self.assertEqual(self.query()['summary']['knownCostCny'],'60.00')

    def test_invalid_money_dates_sizes_and_preview_are_rejected(self):
        for value in ('-1','1.001','NaN','Infinity',True,''):
            self.assertEqual(self.post('costs/preview',self.change(cost=value)).status_code,400)
        omitted=self.change();del omitted['changes'][0]['costCny']
        self.assertEqual(self.post('costs/preview',omitted).status_code,400)
        body=self.prepared(self.change());body['previewHash']='wrong'
        self.assertEqual(self.post('costs/save',body).status_code,409)
        for rate in ('0','-1','NaN','7.1234567',None):
            self.assertEqual(self.post('reports/query',{'exchangeRate':rate}).status_code,400)
        self.assertEqual(self.post('reports/query',{'exchangeRate':'7','statuses':['cancelled']}).status_code,400)
        self.assertEqual(self.post('reports/query',{'exchangeRate':'7','dateFrom':'2026-10-20','dateTo':'2026-10-19'}).status_code,400)

    def test_exports_all_rows_decimal_cells_untrusted_text_and_missing(self):
        self.save_cost()
        db._fetch_one("UPDATE orders SET contact_name='=1+1',order_no=%s WHERE id=1 RETURNING id",('PO0918-'+('Long Buyer '*12)+'-000001',))
        payload={'dateFrom':'2026-09-01','dateTo':'2026-09-30','exchangeRate':'7.123456','page':99}
        response=self.post('reports/export',payload)
        self.assertEqual(response.status_code,200)
        book=load_workbook(BytesIO(response.data))
        self.assertEqual(book.sheetnames,['核算汇总','订单明细','成本缺失'])
        self.assertEqual(book['订单明细'].max_row,7);self.assertEqual(book['成本缺失'].max_row,4)
        self.assertTrue(any(c.value=='=1+1' and c.data_type=='s' for row in book['订单明细'] for c in row))
        self.assertTrue(all(c.data_type!='f' for sheet in book for row in sheet for c in row))
        self.assertEqual(book['订单明细']['J2'].data_type,'n')
        self.assertTrue(book['订单明细']['A2'].alignment.wrap_text)

    def test_public_product_and_order_responses_do_not_include_cost(self):
        self.save_cost(cost='123.45')
        for route,role in [('products','sales'),('inventory/1','warehouse'),('orders','sales')]:
            response=self.call(route,role=role)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('costCny',response.get_data(as_text=True))
            self.assertNotIn('finance_cost',response.get_data(as_text=True))

    def test_product_rebuild_and_deletion_keep_independent_history(self):
        self.save_cost(pid=3,cost='22.50')
        original=self.call('products/3').json['product']
        body={**original,'title':'Edited fixture','version':original['version']}
        response=self.call('products/3','PUT',body)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(db._fetch_one('SELECT cost_cny FROM finance_cost_history WHERE product_id=3')['cost_cny'],Decimal('22.50'))
        with db.get_connection() as conn: conn.execute('DELETE FROM products WHERE id=3')
        self.assertEqual(self.call('finance/costs/history?productId=3&sizeCode=M',role='finance').json['timeline'][0]['costCny'],'22.50')

    def test_preview_change_requires_reconfirmation(self):
        body=self.prepared(self.change())
        db._fetch_one("UPDATE orders SET status='cancelled' WHERE id=1 RETURNING id")
        self.assertEqual(self.post('costs/save',body).status_code,409)
        self.assertIsNone(db._fetch_one('SELECT * FROM finance_cost_history'))
        body=self.prepared(self.change())
        self.assertEqual(self.post('costs/save',body).status_code,200)

    def test_pagination_and_export_include_all_matching_groups(self):
        # Enough logical styles and variants to span both page sizes. Fixture database only.
        for n in range(30):
            code=f'PAGE{1000+n}'
            p=db.create_product({'categoryKey':'denim','productCode':code,'sku':code,'slug':code.lower(),
                'familyCode':code,'styleCode':code,'colorName':'Black','title':code,'image':'/uploads/fixture.jpg',
                'sizes':['M'],'sizePrices':[{'sizeCode':'M','price':1,'stock':0}]})
            db._fetch_one('INSERT INTO order_items(order_id,product_id,product_name,sku,size_code,quantity,unit_price,total_price) VALUES(1,%s,%s,%s,\'M\',1,1,1) RETURNING id',(p['id'],code,code))
        page=self.call('finance/costs?page=1&pageSize=12',role='finance').json
        self.assertEqual(page['total'],31);self.assertEqual(len(page['items']),12)
        last=self.call('finance/costs?page=3&pageSize=12',role='finance').json
        self.assertEqual(len(last['items']),7)
        first=self.query();second=self.query(page=2)
        self.assertEqual(first['total'],32);self.assertEqual(len(first['items']),25)
        self.assertEqual(len(second['items']),7);self.assertEqual(first['summary'],second['summary'])
        exported=self.post('reports/export',{**first['filters'],'page':2})
        self.assertEqual(exported.status_code,200)
        book=load_workbook(BytesIO(exported.data))
        self.assertEqual(book['订单明细'].max_row,37)

    def test_clear_cost_effective_window_missing_report_export_and_no_fallback(self):
        self.save_cost(cost='10');self.save_cost(pid=2,cost='5');self.save_cost(cost='25',when='2026-09-19')
        stock=self.stock();order_count=db._fetch_one('SELECT count(*) AS n FROM orders')['n']
        self.assertEqual(self.query()['summary']['totalCostCny'],'75.00')
        body=self.prepared(self.change(cost=None,when='2026-09-18'))
        preview=self.post('costs/preview',body).json['changes'][0]
        self.assertEqual(preview['oldCostCny'],'10.00');self.assertIsNone(preview['costCny'])
        self.assertEqual(preview['untilExclusive'],'2026-09-19')
        self.assertEqual(self.post('costs/save',body).status_code,200)
        result=self.query();summary=result['summary']
        self.assertEqual(summary['missingQuantity'],4);self.assertEqual(summary['knownCostCny'],'35.00')
        self.assertIsNone(summary['totalCostCny']);self.assertIsNone(summary['profitCny'])
        self.assertEqual(self.query(dateFrom='2026-09-16',dateTo='2026-09-16')['summary']['missingQuantity'],0)
        for date,cost in [('2026-09-17','10.00'),('2026-09-18',None),('2026-09-19','25.00')]:
            groups=self.call('finance/costs?effectiveDate='+date,role='finance').json['items']
            variant=next(v for g in groups for v in g['variants'] if v['id']==1)
            self.assertEqual(next(s for s in variant['sizes'] if s['sizeCode']=='M')['costCny'],cost)
        history=self.call('finance/costs/history?styleCode=GT-2026&productId=1&sizeCode=M',role='finance').json
        self.assertEqual(history['total'],3);self.assertIsNone(history['items'][0]['costCny'])
        self.assertEqual(history['items'][0]['oldCostCny'],'10.00')
        exported=self.post('reports/export',result['filters'])
        self.assertEqual(exported.status_code,200)
        book=load_workbook(BytesIO(exported.data));self.assertEqual(book['成本缺失'].max_row,3)
        self.assertEqual(self.stock(),stock);self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM orders')['n'],order_count)

    def test_clear_same_day_zero_cost_idempotency_conflict_and_restore(self):
        self.save_cost(cost='0')
        body=self.prepared(self.change(cost=None));self.assertEqual(self.post('costs/save',body).status_code,200)
        repeated=self.post('costs/save',body);self.assertEqual(repeated.status_code,200);self.assertTrue(repeated.json['replayed'])
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM finance_cost_history')['n'],1)
        self.assertIsNone(db._fetch_one('SELECT cost_cny FROM finance_cost_history')['cost_cny'])
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM finance_cost_audit')['n'],2)
        stale={**body,'requestId':str(uuid.uuid4())};self.assertEqual(self.post('costs/save',stale).status_code,409)
        self.save_cost(cost='20')
        history=self.call('finance/costs/history?styleCode=GT-2026',role='finance').json['items']
        self.assertEqual(history[0]['costCny'],'20.00');self.assertIsNone(history[0]['oldCostCny'])
        self.assertIsNone(history[1]['costCny']);self.assertEqual(history[1]['oldCostCny'],'0.00')
        self.assertEqual(history[2]['costCny'],'0.00')

    def test_clear_atomic_rollback_permissions_and_old_schema_migration(self):
        self.save_cost(cost='10');body=self.prepared(self.change(cost=None));original=db._fetch_one
        for role in ('sales','warehouse','customer'):
            self.assertEqual(self.post('costs/preview',body,role).status_code,403)
            self.assertEqual(self.post('costs/save',body,role).status_code,403)
        def call(sql,*args,**kwargs):
            if 'INSERT INTO finance_cost_audit' in sql:raise ValueError('fixture clear audit failure')
            return original(sql,*args,**kwargs)
        with patch.object(db,'_fetch_one',side_effect=call):self.assertEqual(self.post('costs/save',body).status_code,400)
        self.assertEqual(db._fetch_one('SELECT cost_cny FROM finance_cost_history')['cost_cny'],Decimal('10'))
        self.assertEqual(db._fetch_one('SELECT revision FROM finance_cost_versions')['revision'],1)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM finance_cost_receipts')['n'],1)
        with db.get_connection() as conn:
            conn.execute('ALTER TABLE finance_cost_history ALTER COLUMN cost_cny SET NOT NULL')
            finance.migrate(conn.cursor());finance.migrate(conn.cursor())
        self.assertEqual(self.post('costs/save',body).status_code,200)
        with db.get_connection() as conn:finance.migrate(conn.cursor());finance.migrate(conn.cursor())
        self.assertIsNone(db._fetch_one('SELECT cost_cny FROM finance_cost_history')['cost_cny'])
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM finance_cost_audit')['n'],2)


if __name__=='__main__':unittest.main()
