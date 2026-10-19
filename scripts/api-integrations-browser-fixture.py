"""Repeatable browser fixture. Never connects to the manual mirror database."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import secrets
import sys
import psycopg
from psycopg.sql import SQL, Identifier

if os.environ.get('PGHOST')!='127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')
# CI creates only the base regression DB, not this separately named fixture.
# Bootstrap only inside the same loopback + *_test guard, before app import.
with psycopg.connect(host='127.0.0.1',port=os.environ['PGPORT'],dbname='postgres',
        user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],autocommit=True) as conn:
    name=os.environ['PGDATABASE']
    if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
        conn.execute(SQL('CREATE DATABASE {} TEMPLATE template0').format(Identifier(name)))
os.environ.update(APP_ENV='test',DB_SCHEMA_AUTO_MIGRATE='1',SECURITY_ADMIN_CAPTCHA_ENABLED='0',ORDER_VOICE_ENABLED='0',EXTERNAL_API_ENABLED='0')
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'admin-backend'))
import test_workbench as fixtures
from werkzeug.security import generate_password_hash
from psycopg import sql

parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=5366)
parser.add_argument('--store-port',type=int,default=5367)
parser.add_argument('--store-backend',type=Path)
args=parser.parse_args()
if __name__=='__main__':
    os.environ.setdefault('EXTERNAL_API_DB_USER','api_browser_'+hashlib.sha256(fixtures.db.DB_NAME.encode()).hexdigest()[:12]+'_test')
    os.environ.setdefault('EXTERNAL_API_DB_PASSWORD',secrets.token_urlsafe(40))
    fixtures.seed()
    with fixtures.db._connect() as conn:
        conn.execute('TRUNCATE api_call_logs,api_rate_buckets,api_integration_events')
        conn.execute(sql.SQL('REVOKE CREATE,TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(fixtures.db.DB_NAME)))
        conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        conn.execute("UPDATE admin_users SET permissions='[\"api-integrations\",\"orders\"]' WHERE role='sales'")
        conn.execute("UPDATE product_size_prices SET stock=-5 WHERE product_id=1 AND size_code='M'")
    fixtures.db.create_admin_user({'name':'API only fixture','email':'api-only@gingtto.test',
        'passwordHash':generate_password_hash('Workbench-Test-2026',method='pbkdf2:sha256:1000'),
        'status':'active','role':'finance','permissions':['api-integrations']})
    standards=[['XS','S','M','L','XL'],['28','30','32','34','36'],['110','120','130','140'],['均码'],['S/28','M/30','L/32']]
    for index in range(1,55):
        sizes=standards[index%len(standards)];code=f'API-{index:03}'
        fixtures.db.create_product({'categoryKey':'outerwear','productCode':code,'sku':code,'slug':code.lower(),
            'familyCode':code,'colorGroup':code,'colorName':'Black','title':'API catalog fixture','image':'/uploads/fixture.jpg',
            'sizes':sizes,'sizePrices':[{'sizeCode':s,'price':7.5,'stock':index} for s in sizes]})
    result=subprocess.run([sys.executable,str(root/'scripts/provision-external-api-role.py'),
        '--expected-db',fixtures.db.DB_NAME,'--role',os.environ['EXTERNAL_API_DB_USER']],check=True)
    env={**os.environ,'DB_SCHEMA_AUTO_MIGRATE':'0','EXTERNAL_API_ENABLED':'1'}
    if args.store_backend:
        command="import sys;sys.path.insert(0,sys.argv[1]);import app;app.app.run(host='127.0.0.1',port=int(sys.argv[2]),threaded=True,use_reloader=False)"
        target=args.store_backend
    else:
        # Standalone repository CI exercises the identical external API engine;
        # actual storefront registration has its own test_external_api suite.
        command="import sys;sys.path.insert(0,sys.argv[1]);from flask import Flask;import db,security_core,external_api;a=Flask('external-api-browser-fixture');s=security_core.Security(a,db,'store');external_api.register(a,db,s);a.run(host='127.0.0.1',port=int(sys.argv[2]),threaded=True,use_reloader=False)"
        target=root/'admin-backend'
    store=subprocess.Popen([sys.executable,'-c',command,str(target),str(args.store_port)],env=env)
    try:fixtures.application.app.run(host='127.0.0.1',port=args.port,threaded=True,use_reloader=False)
    finally:store.terminate();store.wait(timeout=15)
