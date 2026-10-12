"""Presale integration. All writes inherit the strict local *_test fixture guard."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from psycopg.errors import CheckViolation
import test_workbench as fixtures
import style_catalog
import presale

db = fixtures.db


class PresaleTest(unittest.TestCase):
    call = fixtures.WorkbenchTest.call
    product_payload = fixtures.WorkbenchTest.product_payload

    def setUp(self):
        fixtures.WorkbenchTest.setUp(self)
        db._fetch_one("UPDATE presale_configs SET style_codes='[]',sort_mode='automatic',version=0 WHERE id=1 RETURNING id")

    def save(self, codes, mode='automatic', version=None, role='admin'):
        if version is None: version = presale.get_config()['version']
        return self.call('presale','PUT',{'styleCodes': codes,'sortMode':mode,'version':version},role=role)

    def test_empty_initial_config_and_entire_style(self):
        data=self.call('presale').json
        self.assertEqual(data['config']['styleCodes'],[])
        self.assertEqual(len(data['items']),1)
        self.assertEqual(len(data['items'][0]['variants']),3)
        self.assertEqual(data['items'][0]['sizeCodes'],['M','L','Tall XL'])
        self.assertEqual(self.save(['GT-2026']).status_code,200)
        self.assertEqual(self.call('presale').json['config']['styleCodes'],['GT-2026'])

    def test_default_sales_denied_explicit_grant_and_revocation(self):
        self.assertEqual(self.call('presale',role='sales').status_code,403)
        self.assertEqual(self.call('admin-users/2','PUT',{'permissions':['presale']}).status_code,200)
        self.assertEqual(self.call('presale',role='sales').status_code,200)
        self.assertEqual(self.save(['GT-2026'],role='sales').status_code,200)
        self.assertEqual(self.call('admin-users/2','PUT',{'permissions':[]}).status_code,200)
        self.assertEqual(self.save([],role='sales').status_code,403)
        for role in ('warehouse','customer'):
            self.assertEqual(self.call('presale',role=role).status_code,403)
            self.assertEqual(self.save([],role=role).status_code,403)
        self.assertEqual(self.call('admin-users/3','PUT',{'permissions':['presale']}).status_code,400)

    def test_concurrent_save_one_winner_one_conflict(self):
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.save(['GT-2026'],version=0),range(2)))
        self.assertEqual(sorted(r.status_code for r in results),[200,409])
        self.assertEqual(presale.get_config()['version'],1)
        self.assertEqual(len(db._fetch_all("SELECT id FROM admin_audit_logs WHERE entity_table='presale_configs' AND action='UPDATE'")),1)

    def test_audit_failure_rolls_back_config(self):
        with db._connect() as conn:
            conn.execute("ALTER TABLE admin_audit_logs ADD CONSTRAINT presale_fixture_fail CHECK(entity_table <> 'presale_configs')")
        try:
            with self.assertRaises(CheckViolation): self.save(['GT-2026'])
            self.assertEqual(presale.get_config(),{'styleCodes':[],'sortMode':'automatic','version':0})
        finally:
            with db._connect() as conn: conn.execute('ALTER TABLE admin_audit_logs DROP CONSTRAINT presale_fixture_fail')

    def test_inactive_and_changed_style_preserve_reference(self):
        self.assertEqual(self.save(['GT-2026']).status_code,200)
        db._fetch_one('UPDATE products SET is_active=FALSE RETURNING id')
        item=self.call('presale').json['items'][0]
        self.assertFalse(item['active'])
        db._fetch_one("UPDATE products SET style_code='RENAMED' RETURNING id")
        data=self.call('presale').json
        self.assertEqual(data['config']['styleCodes'],['GT-2026'])
        self.assertEqual(data['items'][0]['styleCode'],'RENAMED')
        self.assertEqual(self.save(['GT-2026']).status_code,200)
        self.assertEqual(self.save(['UNKNOWN']).status_code,400)

    def test_no_business_writes_and_omitted_featured_preserved(self):
        before=db._fetch_all('SELECT * FROM product_size_prices ORDER BY id')
        orders=db._fetch_all('SELECT * FROM orders ORDER BY id')
        self.assertEqual(self.save(['GT-2026'],'manual').status_code,200)
        self.assertEqual(db._fetch_all('SELECT * FROM product_size_prices ORDER BY id'),before)
        self.assertEqual(db._fetch_all('SELECT * FROM orders ORDER BY id'),orders)
        body=self.product_payload(1);body.pop('featured',None)
        self.assertEqual(self.call('products/1','PUT',body).status_code,200)
        self.assertTrue(db.get_product_by_id(1)['featured'])

    def test_invalid_payloads_leave_version(self):
        for codes in (None, 'GT', [1], [''], [' GT'], ['GT-2026','GT-2026'],['UNKNOWN']):
            self.assertEqual(self.save(codes).status_code,400)
        self.assertEqual(self.save([],'bogus').status_code,400)
        self.assertEqual(self.save([],version=True).status_code,400)
        self.assertEqual(presale.get_config()['version'],0)

    def test_repeated_migration_preserves_config_and_stock(self):
        self.save(['GT-2026'],'manual')
        before=presale.get_config(); balances=db._fetch_all('SELECT * FROM product_size_prices ORDER BY id')
        db.ensure_database_ready();db.ensure_database_ready()
        self.assertEqual(presale.get_config(),before)
        self.assertEqual(db._fetch_all('SELECT * FROM product_size_prices ORDER BY id'),balances)

    def test_identity_not_titles_and_initial_date_includes_inactive(self):
        self.assertEqual(db.normalize_style_code('STYLE-A_Black'), 'STYLE-A')
        db._fetch_one("UPDATE products SET style_code=CASE WHEN id=3 THEN 'SEPARATE' ELSE 'GT-2026' END,created_at=CASE WHEN id=1 THEN '2020-01-01 00:00:00+00'::timestamptz ELSE '2024-01-01 00:00:00+00'::timestamptz END,is_active=(id<>1) RETURNING id")
        items=presale.catalog()
        self.assertEqual([i['styleCode'] for i in items],['SEPARATE','GT-2026'])
        self.assertTrue(items[1]['firstListedAt'].startswith('2020-01-01'))
        self.assertEqual([v['id'] for v in items[1]['variants']],[1,2])


if __name__=='__main__': unittest.main()
