"""Regression of detached exports and product visibility; local *_test only."""
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from flask import g
from test_workbench import application, db, seed
import export_resources


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.tokens, self.products = seed()
        application.app.config['TESTING'] = True

    def call(self, path, role='admin', method='GET'):
        with application.app.test_client() as client:
            return client.open('/api/admin/'+path,method=method,
                headers={'Authorization':'Bearer '+self.tokens[role]})

    def test_detached_build_and_stale_order_rejected_without_print_mark(self):
        original = application.order_export_process.build
        def build(*args, **kwargs):
            self.assertIsNone(db.REQUEST_CONNECTION.get())
            db._fetch_one('UPDATE orders SET updated_at=clock_timestamp() WHERE id=1 RETURNING id')
            return original(*args, **kwargs)
        with patch.object(application.order_export_process,'build',side_effect=build):
            response=self.call('orders/export?view=workbench&orderIds=1&includeImages=0','warehouse','POST')
        self.assertEqual(response.status_code,409,response.json)
        self.assertEqual(db._fetch_one('SELECT count(*) AS n FROM order_warehouse_prints')['n'],0)

    def test_changed_role_blocks_old_sensitive_file(self):
        original = application.order_export_process.build
        def build(*args, **kwargs):
            db._fetch_one("UPDATE admin_users SET role='warehouse' WHERE id=1 RETURNING id")
            return original(*args, **kwargs)
        with patch.object(application.order_export_process,'build',side_effect=build):
            response=self.call('orders/export?view=workbench&orderIds=1&includeImages=0')
        self.assertEqual(response.status_code,409,response.json)

    def test_global_export_budget_rejects_other_account_then_releases(self):
        with db._connect(autocommit=True,coordination=True) as lock:
            lock.execute("SELECT pg_advisory_lock(hashtextextended('export:global:0',0))")
            response=self.call('orders/export?includeImages=0','warehouse','POST')
            self.assertEqual(response.status_code,429)
            self.assertEqual(response.json['code'],'export_capacity')
            self.assertEqual(response.headers['Retry-After'],'5')
            lock.execute("SELECT pg_advisory_unlock(hashtextextended('export:global:0',0))")
        self.assertEqual(self.call('orders/export?includeImages=0','warehouse','POST').status_code,200)

    def test_image_prefetch_preserves_more_than_128_images_and_cleanup(self):
        buffer=BytesIO();Image.new('RGB',(2,2),'white').save(buffer,format='PNG')
        urls=['https://images.example.test/'+str(i)+'.png' for i in range(140)]
        with application.app.test_request_context('/api/admin/orders/export'):
            g.export_sources={(url,False):None for url in urls}
            with patch.object(application,'_read_export_image',return_value=buffer.getvalue()):
                application.prefetch_export_images([{'items':[{'image':url} for url in urls]}])
            cache=export_resources.cache()
            self.assertEqual(len(cache.entries),140)
            self.assertTrue(all(cache[(url,False)] for url in urls))
            paths=list(cache.entries.values())
        self.assertTrue(all(not path.exists() for path in paths))

    def test_product_active_filter_and_exact_style_navigation(self):
        product=self.products[0]
        db._fetch_one('UPDATE products SET is_active=FALSE WHERE id=%s RETURNING id',(product['id'],))
        active=self.call('products?page=1').json['items']
        inactive=self.call('products?page=1&status=inactive').json['items']
        all_rows=self.call('products?page=1&status=all&styleCode=GT-2026').json['items']
        self.assertNotIn(product['id'],[r['id'] for r in active])
        self.assertEqual([r['id'] for r in inactive],[product['id']])
        self.assertFalse(inactive[0]['isActive'])
        self.assertEqual(len(all_rows),3)
        self.assertEqual(self.call('products/'+str(product['id'])).status_code,200)
