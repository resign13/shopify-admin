"""Exercise real runtime DB roles and checkout, only on a disposable *_test DB."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import psycopg

parser=argparse.ArgumentParser()
parser.add_argument('--expected-db',required=True)
parser.add_argument('--prefix',required=True)
args=parser.parse_args()
if os.environ.get('PGHOST')!='127.0.0.1' or not args.expected_db.endswith('_test') or os.environ.get('PGDATABASE')!=args.expected_db:
    raise SystemExit('Explicit isolated local *_test target required')
if not args.prefix.endswith('_test'): raise SystemExit('Isolated test role prefix required')
root=Path(__file__).resolve().parents[1]
store=root.parent/'shopify'/'storefront-backend'
if not store.is_dir(): raise SystemExit('Sibling storefront checkout required')
os.environ.update(APP_ENV='test',DB_SCHEMA_AUTO_MIGRATE='1',PRIVATE_STORAGE_BUCKET='')
sys.path.insert(0,str(root/'admin-backend'))
import test_workbench as fixtures
fixtures.seed()
base=dict(host='127.0.0.1',port=int(os.environ['PGPORT']),dbname=args.expected_db)
passwords={kind:secrets.token_urlsafe(40) for kind in ['migrator','admin','store']}
env=os.environ.copy()
for kind,value in passwords.items(): env['SECURITY_DB_'+kind.upper()+'_PASSWORD']=value
result=subprocess.run([sys.executable,str(root/'scripts/provision-db-roles.py'),'--expected-db',args.expected_db,'--prefix',args.prefix],env=env,capture_output=True)
if result.returncode: raise SystemExit('Test role provisioning failed')
for kind in ['admin','store']:
    with psycopg.connect(**base,user=args.prefix+'_'+kind,password=passwords[kind],autocommit=True) as conn:
        role=conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert not any(role), 'Runtime role has excessive privileges'
        try: conn.execute('CREATE TABLE public.security_forbidden_fixture(id INTEGER)')
        except psycopg.errors.InsufficientPrivilege: pass
        else: raise AssertionError('Runtime DDL succeeded')
        if kind=='store':
            assert not conn.execute("SELECT has_table_privilege(current_user,'orders','UPDATE')").fetchone()[0]
            assert conn.execute("SELECT has_column_privilege(current_user,'orders','cancellation_note','UPDATE')").fetchone()[0]
            for column in ('total_amount','shipping_fee','payment_link','owner_admin_id','note'):
                try: conn.execute('UPDATE orders SET '+column+'='+column+' WHERE FALSE')
                except psycopg.errors.InsufficientPrivilege: pass
                else: raise AssertionError('Store runtime can modify a restricted order column')
            for table in ['finance_cost_history','finance_style_costs','finance_style_cost_audit','admin_users','admin_sessions','admin_audit_logs','security_export_queue']:
                try: conn.execute('SELECT 1 FROM '+table+' LIMIT 1')
                except psycopg.errors.InsufficientPrivilege: pass
                else: raise AssertionError('Store runtime accessed a forbidden table')
            waiting=conn.execute('SELECT * FROM security_export_waiting')
            assert [column.name for column in waiting.description] == ['has_waiting']
            assert isinstance(waiting.fetchone()[0], bool)

code=r'''
import io,json,uuid
from flask.testing import FlaskClient
import app,db
is_store=app.security.channel=='store'
client=FlaskClient(app.app,app.app.response_class)
csrf=client.get('/api/auth/csrf').json['csrfToken']
login=client.post('/api/auth/'+('store' if is_store else 'admin')+'/login',
    json={'email':'buyer@gingtto.test' if is_store else 'admin@gingtto.test','password':'Fixture-Only' if is_store else 'Workbench-Test-2026'},
    headers={'Origin':'http://localhost','X-CSRF-Token':csrf})
assert login.status_code==200,'Runtime login failed'
headers={'Origin':'http://localhost','X-CSRF-Token':login.json['csrfToken'],'X-Auth-Session':login.json['sessionId']}
with db._connect() as conn: before=conn.execute("SELECT stock FROM product_size_prices WHERE product_id=1 AND size_code='M'").fetchone()['stock']
if is_store:
    body={'contact':{'value':'buyer@gingtto.test'},'delivery':{'country':'DE','lastName':'Fixture','address':'Fixture Street','city':'Berlin','state':'Berlin','zip':'10000'},'items':[{'productId':1,'sizeCode':'M','quantity':2}]}
    created=client.post('/api/orders',json=body,headers=headers)
else:
    body={'requestId':str(uuid.uuid4()),'userId':1,'contactName':'Fixture','phone':'123456','country':'DE','address':'Fixture Street','items':[{'productId':1,'sizeCode':'M','quantity':2,'unitPrice':20}]}
    created=client.post('/api/admin/orders',json=body,headers=headers)
assert created.status_code in {200,201},'Runtime order creation failed: '+str(created.status_code)
assert created.json['order']['orderNo'].startswith('LM-'),'Final order number was not assigned'
with db._connect() as conn: after=conn.execute("SELECT stock FROM product_size_prices WHERE product_id=1 AND size_code='M'").fetchone()['stock']
assert before-after==2,'Stock deduction mismatch'
if is_store:
    oid=created.json['order']['id']
    cancelled=client.post('/api/store/orders/'+str(oid)+'/cancel',headers=headers)
    assert cancelled.status_code==200,'Runtime cancellation failed'
    assert 'cancelNote' not in cancelled.json['order'] and 'cancellation_note' not in cancelled.json['order']
    again=client.post('/api/store/orders/'+str(oid)+'/cancel',headers=headers)
    assert again.status_code==200,'Repeated runtime cancellation failed'
    with db._connect() as conn: restored=conn.execute("SELECT stock FROM product_size_prices WHERE product_id=1 AND size_code='M'").fetchone()['stock']
    assert restored==before,'Cancellation did not restore stock'
    assert client.get('/api/catalog/styles').status_code==200
else:
    assert client.get('/api/admin/finance/options').status_code==200
    costs=client.get('/api/admin/finance/costs')
    assert costs.status_code==200,'Admin runtime cannot read style costs'
    change={'changes':[{'styleCode':costs.json['items'][0]['styleCode'],'costCny':'10.25','version':'0'}]}
    preview=client.post('/api/admin/finance/costs/preview',json=change,headers=headers)
    assert preview.status_code==200,'Admin runtime cannot preview style costs'
    saved=client.post('/api/admin/finance/costs/save',json={**change,'previewHash':preview.json['previewHash'],'requestId':str(uuid.uuid4())},headers=headers)
    assert saved.status_code==200 and saved.json['saved']==1,'Admin runtime cannot save style costs/audit'
print(json.dumps({'runtime':app.security.channel,'login':True,'create':True,'stock':True,'cancel':is_store}))
'''
for kind,directory in [('store',store),('admin',root/'admin-backend')]:
    child=env.copy();child.update(PGUSER=args.prefix+'_'+kind,PGPASSWORD=passwords[kind],DB_SCHEMA_AUTO_MIGRATE='0')
    result=subprocess.run([sys.executable,'-c',code],cwd=directory,env=child,capture_output=True,text=True,timeout=90)
    if result.returncode:
        # Child data is synthetic, but report only the last assertion/error type.
        final=result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'runtime probe failed'
        raise SystemExit(kind+': '+final)
    print(result.stdout.strip())
print('Runtime DB boundaries and real order transactions passed')
