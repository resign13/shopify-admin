"""Opt-in real PostgreSQL transactions, confined to a dedicated local *_test DB.

The runner supplies a connection factory in memory with configure(). No runtime
application environment, production credentials or application schema startup.
Object storage remains fake; PostgreSQL locks and JSON adapters are real.
"""
import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from psycopg.types.json import Jsonb

from image_library_normalization import FIELDS,LibraryMigration,ReferenceDatabase,references
from test_image_library_normalization import A,B,FakeProviders,rows
import test_image_library_normalization as fixtures

_CONNECT=None
_NAME=None


def configure(factory,name):
    global _CONNECT,_NAME
    if not name.startswith('gingtto_image_library_') or not name.endswith('_test'):
        raise ValueError('Dedicated image migration test database required')
    _CONNECT,_NAME=factory,name


DDL = '''
CREATE TABLE security_files(id bigint PRIMARY KEY);
CREATE TABLE products(id bigint PRIMARY KEY, main_image_url text, size_chart_image_url text,
 description_image_url text, updated_at timestamptz NOT NULL, price numeric NOT NULL DEFAULT 17, stock integer NOT NULL DEFAULT 8);
CREATE TABLE product_images(id bigint PRIMARY KEY, product_id bigint REFERENCES products(id), image_url text,sort_order integer DEFAULT 0);
CREATE TABLE banners(id bigint PRIMARY KEY,image_url text,updated_at timestamptz NOT NULL);
CREATE TABLE orders(id bigint PRIMARY KEY,label_image_urls text,label_pdf_url text,updated_at timestamptz NOT NULL,
 total_amount numeric NOT NULL DEFAULT 85,status text NOT NULL DEFAULT 'pending_payment');
CREATE TABLE order_items(id bigint PRIMARY KEY,order_id bigint REFERENCES orders(id),quantity integer DEFAULT 5,unit_price numeric DEFAULT 17);
CREATE TABLE admin_order_drafts(id bigint PRIMARY KEY,document jsonb,revision bigint,updated_at timestamptz,
 last_save_hash text NOT NULL DEFAULT 'existing-request-receipt');
CREATE TABLE order_customer_templates(id bigint PRIMARY KEY,customer_info jsonb,revision bigint,updated_at timestamptz);
CREATE TABLE purchase_contracts(id bigint PRIMARY KEY,snapshot jsonb,quantity bigint NOT NULL DEFAULT 5,
 payload_hash text NOT NULL DEFAULT 'existing-contract-receipt');
CREATE TABLE homepage_configs(id bigint PRIMARY KEY,hero_banner_images text,updated_at timestamptz);
CREATE TABLE presale_configs(id bigint PRIMARY KEY,style_codes jsonb,version bigint DEFAULT 1);
'''


class RealPostgresLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if _CONNECT is None: raise unittest.SkipTest('Dedicated local PostgreSQL runner not configured')
        with _CONNECT() as connection:
            assert connection.info.dbname==_NAME and _NAME.endswith('_test')
            assert connection.info.host in {'127.0.0.1','localhost'}
            connection.execute(DDL)
        fixtures.LibraryMigrationTest.setUpClass()

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        with _CONNECT() as connection:
            assert connection.info.dbname==_NAME and _NAME.startswith('gingtto_image_library_') and _NAME.endswith('_test')
            connection.execute('TRUNCATE '+','.join([*FIELDS,'security_files','order_items','presale_configs'])+' CASCADE')
            for row in rows():
                values={'id':row['id'],**row['values'],**{key:row[key] for key in ('updated_at','revision','product_id') if key in row}}
                columns=list(values)
                params=[Jsonb(value) if FIELDS[row['table']].get(key)=='json' else value for key,value in values.items()]
                connection.execute('INSERT INTO '+row['table']+' ('+','.join(columns)+') VALUES ('+','.join(['%s']*len(columns))+')',params)
            connection.execute('INSERT INTO order_items(id,order_id) VALUES(1,1)')
            connection.execute("INSERT INTO presale_configs(id,style_codes) VALUES(1,'[\"style-kept\"]')")
        self.provider=FakeProviders(fixtures.LibraryMigrationTest.large,fixtures.LibraryMigrationTest.small)
        self.database=ReferenceDatabase(_CONNECT,_NAME,'legacy',target='127.0.0.1/'+_NAME)
        self.migration=LibraryMigration(self.database,self.provider,self.temporary.name)

    def stage(self):
        self.migration.audit(); self.migration.stage()

    def business(self):
        with _CONNECT() as connection:
            return {
                'products':dict(connection.execute('SELECT price,stock FROM products WHERE id=1').fetchone()),
                'orders':dict(connection.execute('SELECT total_amount,status FROM orders WHERE id=1').fetchone()),
                'items':dict(connection.execute('SELECT quantity,unit_price FROM order_items WHERE id=1').fetchone()),
                'contract':dict(connection.execute('SELECT quantity,payload_hash FROM purchase_contracts WHERE id=1').fetchone()),
                'draft':dict(connection.execute('SELECT last_save_hash FROM admin_order_drafts WHERE id=1').fetchone()),
                'presale':dict(connection.execute('SELECT style_codes,version FROM presale_configs WHERE id=1').fetchone()),
            }

    def test_real_json_text_jsonb_versions_and_forward_only_rollback(self):
        original,_=self.database.snapshot(); business=self.business(); self.stage()
        report=self.migration.apply()
        self.assertEqual(report['statuses'],{'applied':1,'unchanged':1})
        applied,_=self.database.snapshot()
        self.assertNotIn(A,references(applied))
        self.assertEqual(self.business(),business)
        for before,after in zip(original,applied):
            if 'updated_at' in before: self.assertGreater(datetime.fromisoformat(after['updated_at']),datetime.fromisoformat(before['updated_at']))
            if 'revision' in before: self.assertEqual(after['revision'],before['revision']+1)
        draft=next(row for row in applied if row['table']=='admin_order_drafts')['values']['document']
        self.assertEqual((draft['note'],draft['items'][0]['quantity'],draft['items'][0]['unitPrice']),(A,5,17))
        report=self.migration.rollback(); self.assertEqual(report['statuses'],{'rolled_back':1,'unchanged':1})
        restored,_=self.database.snapshot()
        self.assertEqual(references(restored),references(original))
        self.assertEqual(self.business(),business)
        for before,after in zip(applied,restored):
            if 'updated_at' in before: self.assertGreater(datetime.fromisoformat(after['updated_at']),datetime.fromisoformat(before['updated_at']))
            if 'revision' in before: self.assertEqual(after['revision'],before['revision']+1)
        snapshot=next(row for row in restored if row['table']=='purchase_contracts')['values']['snapshot']
        self.assertEqual(snapshot['revision'],9)

    def test_real_nowait_conflict_keeps_all_old_references(self):
        self.stage(); original,_=self.database.snapshot()
        blocker=_CONNECT()
        try:
            blocker.execute('UPDATE orders SET total_amount=total_amount WHERE id=1')
            report=self.migration.apply()
            journal=self.migration.journal(next(entry for entry in self.migration.manifest['entries'] if entry['original_url']==A))
            self.assertEqual(journal['last_error_type'],'LockNotAvailable')
            self.assertEqual(report['statuses'],{'switching:attention':1,'unchanged':1})
        finally:
            blocker.rollback(); blocker.close()
        actual,_=self.database.snapshot(); self.assertEqual(actual,original)

    def test_real_late_json_edit_conflicts_whole_url(self):
        self.stage()
        with _CONNECT() as connection:
            connection.execute("UPDATE admin_order_drafts SET document=jsonb_set(document,'{items,0,quantity}','99'),revision=revision+1 WHERE id=1")
        before,_=self.database.snapshot(); self.migration.apply(); after,_=self.database.snapshot()
        self.assertEqual(after,before)
        self.assertIn(A,references(after))

    def test_real_failure_after_first_update_rolls_back_every_table(self):
        self.stage(); before,_=self.database.snapshot()
        with _CONNECT() as connection:
            connection.execute("ALTER TABLE banners ADD CONSTRAINT reject_fixture_derivative CHECK(image_url NOT LIKE '%/normalized/%')")
        try:
            self.migration.apply()
            journal=self.migration.journal(next(entry for entry in self.migration.manifest['entries'] if entry['original_url']==A))
            self.assertEqual(journal['last_error_type'],'CheckViolation')
        finally:
            with _CONNECT() as connection: connection.execute('ALTER TABLE banners DROP CONSTRAINT reject_fixture_derivative')
        actual,_=self.database.snapshot(); self.assertEqual(actual,before)

    def test_real_rollback_refuses_subsequent_contract_business_revision(self):
        self.stage(); self.migration.apply()
        with _CONNECT() as connection:
            connection.execute("UPDATE purchase_contracts SET snapshot=jsonb_set(jsonb_set(snapshot,'{items,0,quantity}','23'),'{revision}',to_jsonb((snapshot->>'revision')::bigint+1)) WHERE id=1")
        before,_=self.database.snapshot(); report=self.migration.rollback(); after,_=self.database.snapshot()
        self.assertEqual(after,before)
        self.assertEqual(report['statuses'],{'rolling_back:attention':1,'unchanged':1})

    def test_real_two_images_rebase_same_json_and_rollback(self):
        self.provider.originals[B]=fixtures.LibraryMigrationTest.large
        self.stage(); report=self.migration.apply()
        self.assertEqual(report['statuses'],{'applied':2})
        current,_=self.database.snapshot()
        self.assertFalse(set(references(current))&{A,B})
        self.assertEqual(self.migration.rollback()['statuses'],{'rolled_back':2})
        current,_=self.database.snapshot()
        self.assertEqual(references(current),references(rows()))


if __name__=='__main__': unittest.main()
