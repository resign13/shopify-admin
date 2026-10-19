"""Bounded real-HTTP acceptance/benchmark; every write stays in a local *_test DB.

Run with explicit local PostgreSQL credentials in the environment. Catalog-only
input comes from the local synchronized mirror via a READ ONLY transaction.
No accounts, orders, sessions or financial data are copied from the mirror.
Keys/passwords remain in process memory; reports contain aggregate data only.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, UTC
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import statistics
import subprocess
import sys
import threading
import time
from urllib.parse import urlencode, urlsplit, urljoin
import uuid

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import requests
from flask.testing import FlaskClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-db', required=True, choices=['lumiere_admin'])
parser.add_argument('--store-backend', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--port', type=int, default=5372)
parser.add_argument('--samples', type=int, default=30)
parser.add_argument('--reuse-catalog', action='store_true', help='Reuse only after exact source/fixture catalog comparison')
parser.add_argument('--idle-baseline', action='store_true', help='Record that other test/build jobs finished before this run')
parser.add_argument('--image-samples', type=int, default=4, choices=range(0, 5))
parser.add_argument('--image-origin', action='append', default=[], help='Explicit trusted public HTTPS image origin; repeatable')
parser.add_argument('--image-proxy-from-env', action='store_true', help='Explicitly use the operator HTTPS proxy for public-image samples only')
parser.add_argument('--soak-seconds',type=int,default=0,choices=range(0,181))
args = parser.parse_args()
for origin in args.image_origin:
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise SystemExit('Trusted image origin must be an HTTPS origin without path or credentials')
name = os.environ.get('PGDATABASE', '')
if os.environ.get('PGHOST') != '127.0.0.1' or os.environ.get('PGPORT') != '55439' or not name.endswith('_test'):
    raise SystemExit('Explicit local 127.0.0.1:55439 *_test target required')
if not 10 <= args.samples <= 100 or not 1024 <= args.port <= 65533:
    raise SystemExit('Bounded samples/ports required')
args.output.parent.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'admin-backend'))
config = dict(host='127.0.0.1', port=55439, user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'])
for port in (args.port, args.port+1):
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            raise SystemExit('Benchmark port already occupied; existing process left untouched')
with psycopg.connect(dbname='postgres', autocommit=True, **config) as conn:
    if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))

# Only white-listed, already-public product material fields leave the source DB.
with psycopg.connect(dbname=args.source_db, row_factory=dict_row, **config) as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    source_products = conn.execute('SELECT * FROM external_api_products_v ORDER BY id').fetchall()
    source_sizes = conn.execute('SELECT product_id,size_code,stock FROM external_api_sizes_v ORDER BY product_id,sort_order,id').fetchall()
    source_images = conn.execute('SELECT product_id,image_url FROM external_api_images_v ORDER BY product_id,sort_order,id').fetchall()
    source_read_at = conn.execute('SELECT transaction_timestamp()').fetchone()['transaction_timestamp'].astimezone(UTC).isoformat()
assert source_products, 'Local synchronized catalog is empty'

os.environ.update(APP_ENV='test', DB_SCHEMA_AUTO_MIGRATE='1', EXTERNAL_API_ENABLED='0',
    SECURITY_ADMIN_CAPTCHA_ENABLED='0', SECURITY_LOGIN_PROTECTION_ENABLED='0', ORDER_VOICE_ENABLED='0',
    SECURITY_ATTACHMENT_MODE='legacy', EXTERNAL_API_PUBLIC_ORIGIN='https://gingtto.store')
if args.image_origin:
    os.environ['PUBLIC_IMAGE_ORIGINS']=','.join(args.image_origin)
import test_workbench as fixtures
db = fixtures.db
assert db.DB_NAME == name and db.DB_HOST == '127.0.0.1'
category_ids = {}
sizes_by_id = {}
images_by_id = {}
for row in source_sizes: sizes_by_id.setdefault(row['product_id'], []).append(row)
for row in source_images: images_by_id.setdefault(row['product_id'], []).append(row['image_url'])
expected = {}
if not args.reuse_catalog:
    fixtures.seed()
    with db._connect() as conn:
        conn.execute('TRUNCATE products,product_categories RESTART IDENTITY CASCADE')
        conn.execute('TRUNCATE api_call_logs,api_integration_events,api_rate_buckets')
        conn.execute(sql.SQL('REVOKE CREATE,TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
        conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    for row in source_products:
        if row['category_key'] not in category_ids:
            db.create_category({'key':row['category_key'], 'sortOrder':len(category_ids),
                'labels':{'en':row['category_name'], 'zh':row['category_name']}})
            category_ids[row['category_key']] = row['category_id']
    for row in source_products:
        sizes = sizes_by_id.get(row['id'], [])
        product = db.create_product({'categoryKey':row['category_key'], 'productCode':row['style_code'],
            'sku':row['sku'], 'slug':'api-benchmark-'+str(row['id']), 'familyCode':row['style_code'],
            'colorGroup':row['style_code'], 'colorName':row['color_name'], 'title':row['title'],
            'image':row['main_image_url'], 'gallery':images_by_id.get(row['id'], []),
            'sizeChartImage':row['size_chart_image_url'], 'descriptionImage':row['description_image_url'],
            'sizes':[s['size_code'] for s in sizes],
            'sizePrices':[{'sizeCode':s['size_code'],'stock':s['stock'],'price':0} for s in sizes]})
        with db._connect() as conn:
            # Fixture creation helpers normalize style codes for editing. A
            # catalog snapshot must instead preserve the exact saved identifier.
            conn.execute('UPDATE products SET style_code=%s WHERE id=%s',(row['style_code'],product['id']))
            conn.execute("UPDATE product_translations SET name=%s,summary=%s,description=%s WHERE product_id=%s AND lang_code='en'",
                (row['title'], row['summary'], row['description'], product['id']))
        expected[product['id']] = {'sizes':[{'size':s['size_code'],'stock':s['stock']} for s in sizes],
            'gallery':images_by_id.get(row['id'], []), 'row':row}
else:
    with db._connect() as conn:
        targets=conn.execute('SELECT * FROM external_api_products_v ORDER BY id').fetchall()
        target_sizes=conn.execute('SELECT product_id,size_code,stock FROM external_api_sizes_v ORDER BY product_id,sort_order,id').fetchall()
        target_images=conn.execute('SELECT product_id,image_url FROM external_api_images_v ORDER BY product_id,sort_order,id').fetchall()
        conn.execute('TRUNCATE api_call_logs,api_integration_events,api_rate_buckets')
    assert len(targets)==len(source_products), 'Catalog changed; run again without --reuse-catalog'
    for row,target in zip(source_products,targets):
        fields=set(row)-{'id','category_id'}
        assert all(row[field]==target[field] for field in fields), 'Catalog changed; rebuild fixture. Fields: '+','.join(sorted(field for field in fields if row[field]!=target[field]))
        sizes=[{'size':s['size_code'],'stock':s['stock']} for s in sizes_by_id.get(row['id'],[])]
        actual=[{'size':s['size_code'],'stock':s['stock']} for s in target_sizes if s['product_id']==target['id']]
        assert actual==sizes, 'Size configuration changed; rebuild fixture'
        gallery=images_by_id.get(row['id'],[])
        assert gallery==[i['image_url'] for i in target_images if i['product_id']==target['id']], 'Images changed; rebuild fixture'
        expected[target['id']]={'sizes':sizes,'gallery':gallery,'row':row}
        category_ids[row['category_key']]=row['category_id']
with db._connect() as conn:
    conn.execute('ANALYZE')

# Obtain a real key through the unchanged Cookie+CSRF management handlers.
client = FlaskClient(fixtures.application.app, fixtures.application.app.response_class)
csrf = client.get('/api/auth/csrf').json['csrfToken']
login = client.post('/api/auth/admin/login', json={'email':'admin@gingtto.test','password':'Workbench-Test-2026'},
    headers={'Origin':'http://localhost','X-CSRF-Token':csrf})
assert login.status_code == 200
headers = {'Origin':'http://localhost','X-CSRF-Token':login.json['csrfToken'],'X-Auth-Session':login.json['sessionId']}
meta = client.get('/api/admin/api-integrations/me').json['item']
operation='reset' if meta['keyId'] else 'generate'
generated = client.post('/api/admin/api-integrations/me/'+operation, json={'version':meta['version']}, headers=headers)
assert generated.status_code == 200
token = generated.json['key']
key_id = generated.json['item']['keyId']
owner_id = db._fetch_one('SELECT admin_user_id FROM api_integrations WHERE key_id=%s', (key_id,))['admin_user_id']
role = 'api_perf_' + hashlib.sha256(name.encode()).hexdigest()[:12] + '_test'
env = {**os.environ, 'DB_SCHEMA_AUTO_MIGRATE':'0', 'EXTERNAL_API_ENABLED':'1',
    'EXTERNAL_API_DB_USER':role, 'EXTERNAL_API_DB_PASSWORD':secrets.token_urlsafe(40)}
subprocess.run([sys.executable, str(root/'scripts/provision-external-api-role.py'), '--expected-db', name, '--role', role], env=env, check=True)

def fingerprint():
    with db._connect() as conn:
        result = {}
        for table in ('products','product_sizes','product_size_prices','orders','order_items','admin_users','store_users'):
            row = conn.execute(sql.SQL("SELECT count(*) AS n,md5(COALESCE(string_agg(md5(row_to_json(t)::text),'' ORDER BY id),'')) AS hash FROM {} t").format(sql.Identifier(table))).fetchone()
            result[table] = dict(row)
        return result

report = {'startedAt':datetime.now(UTC).isoformat(),'status':'running','environment':{
    'host':'127.0.0.1','port':args.port,'database':name,'sourceCatalogReadOnly':True,
    'sourceLocalReadAt':source_read_at, 'sourceLastSuccessfulSyncAt':os.environ.get('API_SOURCE_SYNC_AT'),
    'server':'Flask/Werkzeug threaded development server; real storefront application',
    'platform':platform.platform(),'python':platform.python_version(),'cpuCount':os.cpu_count(),
    'configuredPublicImageOrigins':args.image_origin,
    'baselineOtherRegressionsFinished':args.idle_baseline,
    'network':'HTTP loopback; not public HTTPS/CDN deployment capacity',
    'writes':'isolated *_test fixture and API metadata only; no production writes',
    'apiRole':role,'samplesPerEndpoint':args.samples,'rawCredentialsPersisted':False},
    'dataset':{'products':len(expected),'sizeRows':len(source_sizes),'galleryImages':len(source_images),
        'categories':len(category_ids),'zeroSaleableSizeRows':sum(row['stock']==0 for row in source_sizes),
        'distinctSizeConfigurations':len({tuple(s['size_code'] for s in sizes_by_id.get(row['id'],[])) for row in source_products}),
        'catalogOnlyCopy':True,'pricesOrdersCustomersSessionsCopied':False},'checks':{},'endpoints':[], 'concurrency':[], 'fullSync':[], 'images':[]}
before = fingerprint()
processes = []
monitor_stop=threading.Event()
monitor_thread=None
monitor_observations=[]
monitor_errors=[]
log_path = args.output.with_suffix('.server.log')
log = log_path.open('w', encoding='utf-8')
thread_local = threading.local()

def session():
    if not hasattr(thread_local, 'session'):
        thread_local.session = requests.Session()
        thread_local.session.trust_env = False
    return thread_local.session

def call(path, port=None, auth=True):
    started = time.perf_counter()
    response = session().get('http://127.0.0.1:'+str(port or args.port)+path,
        headers={'Authorization':'Bearer '+token} if auth else {}, timeout=(3, 15), allow_redirects=False)
    elapsed = (time.perf_counter()-started)*1000
    return response, elapsed

def stop_servers():
    for process in processes:
        if process.poll() is None: process.terminate()
    for process in processes: process.wait(timeout=15)
    processes.clear()

def start_servers(limit, count):
    active_env = {**env, 'EXTERNAL_API_LIMIT':str(limit), 'EXTERNAL_API_IP_LIMIT':'10000' if limit>60 else '300',
        **({'EXTERNAL_API_GLOBAL_RPS':'10000','EXTERNAL_API_GLOBAL_CONCURRENCY':'64','EXTERNAL_API_KEY_CONCURRENCY':'64'} if limit>60 else {})}
    command = "import sys;sys.path.insert(0,sys.argv[1]);import app;app.app.run(host='127.0.0.1',port=int(sys.argv[2]),threaded=True,use_reloader=False)"
    for index in range(count):
        process = subprocess.Popen([sys.executable,'-c',command,str(args.store_backend),str(args.port+index)],
            env=active_env, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        processes.append(process)
        deadline = time.monotonic()+60
        while time.monotonic()<deadline:
            if process.poll() is not None: raise RuntimeError('Benchmark server startup failed; see redacted server log')
            try:
                # A missing namespace route confirms readiness without consuming quota.
                r,_ = call('/api/external/v1/unknown',port=args.port+index,auth=False)
                if r.status_code==404: break
            except requests.RequestException: pass
            time.sleep(.25)
        else: raise RuntimeError('Benchmark server startup timeout')

def percentile(values, percent):
    values = sorted(values)
    position = (len(values)-1)*percent/100
    lo = int(position); hi = min(lo+1,len(values)-1)
    return values[lo] + (values[hi]-values[lo])*(position-lo)

def metrics(rows, wall):
    times = [r[1] for r in rows]; statuses = Counter(str(r[0]) for r in rows)
    return {'requests':len(rows),'success':statuses.get('200',0),'statuses':dict(statuses),
        'meanMs':round(statistics.mean(times),2),'p50Ms':round(percentile(times,50),2),
        'p95Ms':round(percentile(times,95),2),'p99Ms':round(percentile(times,99),2),
        'maxMs':round(max(times),2),'wallSeconds':round(wall,3),
        'requestsPerSecond':round(len(rows)/wall,2),'meanResponseBytes':round(statistics.mean(r[2] for r in rows)),
        'transportErrors':sum(r[0]==0 for r in rows)}

def measure(path, count, workers=1):
    def one(_):
        started=time.perf_counter()
        try:
            r,t = call(path)
            return r.status_code,t,len(r.content)
        except requests.RequestException:
            return 0,(time.perf_counter()-started)*1000,0
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool: rows=list(pool.map(one,range(count)))
    return metrics(rows,time.perf_counter()-started)

def monitor_connections():
    # One monitoring connection, read-only and restricted to this test DB/role.
    try:
        with psycopg.connect(dbname=name,autocommit=True,**config) as conn:
            conn.execute('SET default_transaction_read_only=on')
            while not monitor_stop.wait(.1):
                monitor_observations.append(conn.execute("SELECT count(*),count(*) FILTER(WHERE state='idle in transaction') FROM pg_stat_activity WHERE datname=current_database() AND usename=%s AND application_name='gingtto-external-api'",(role,)).fetchone())
    except Exception as error:monitor_errors.append(type(error).__name__)

try:
    start_servers(60,2)
    response,cold=call('/api/external/v1/products')
    assert response.status_code==200
    report['firstRequestMs']=round(cold,2)
    assert call('/api/external/v1/products',auth=False)[0].status_code==401
    report['checks']['missingKey401']=True
    assert response.headers.get('Cache-Control')=='no-store'
    report['checks']['noStore']=True

    # Same Key, two actual processes, one PostgreSQL-backed quota. Pre-filling
    # the isolated fixture avoids a 60-request burst against any real service.
    bucket = hashlib.sha256(('key:'+key_id).encode()).hexdigest()
    with db._connect() as conn:
        conn.execute("UPDATE api_rate_buckets SET ticks=array_fill(clock_timestamp(),ARRAY[59]) WHERE bucket_key=%s", (bucket,))
    with ThreadPoolExecutor(max_workers=2) as pool:
        quota = list(pool.map(lambda p:call('/api/external/v1/products',port=p)[0], [args.port,args.port+1]))
    assert sorted(r.status_code for r in quota)==[200,429]
    assert int(next(r.headers['Retry-After'] for r in quota if r.status_code==429))>=1
    report['checks']['default60QuotaSharedAcrossProcesses']=True
    report['checks']['rateLimitedRetryAfter']=True
    with db._connect() as conn: conn.execute('TRUNCATE api_rate_buckets')
    # Exercise a realistic default-quota overlap, separately from the raised-
    # quota capacity phase. The administration side also uses this *_test DB.
    def paced_api():
        result=[];started=time.perf_counter()
        for index in range(30):
            r,elapsed=call('/api/external/v1/products?limit=50')
            result.append((r.status_code,elapsed,len(r.content)))
            time.sleep(max(0,started+(index+1)*.5-time.perf_counter()))
        return result,time.perf_counter()-started
    def paced_backoffice():
        result=[];started=time.perf_counter()
        for index in range(15):
            tick=time.perf_counter();r=client.get('/api/admin/orders?page=1&pageSize=25')
            result.append((r.status_code,(time.perf_counter()-tick)*1000,len(r.data)))
            time.sleep(max(0,started+index+1-time.perf_counter()))
        return result,time.perf_counter()-started
    with ThreadPoolExecutor(max_workers=2) as pool:
        api_future=pool.submit(paced_api);admin_future=pool.submit(paced_backoffice)
        api_rows,api_wall=api_future.result();admin_rows,admin_wall=admin_future.result()
    report['defaultQuotaMixedWorkload']={'apiTargetRequestsPerSecond':2,'backofficeTargetRequestsPerSecond':1,
        'keyQuotaPerMinute':180,'api':metrics(api_rows,api_wall),'backoffice':metrics(admin_rows,admin_wall)}
    assert all(row[0]==200 for row in api_rows+admin_rows), 'Default-quota mixed workload errors'
    report['checks']['defaultQuotaApiAndBackofficeOverlap']=True
    stop_servers()
    with db._connect() as conn: conn.execute('TRUNCATE api_rate_buckets')
    start_servers(10000,1)
    monitor_thread=threading.Thread(target=monitor_connections,daemon=True)
    monitor_thread.start()
    report['environment']['capacityQuotaPerKeyPerMinute']=10000
    report['environment']['capacityQuotaPerIPPerMinute']=10000
    ids=list(expected)
    scanned=[]; cursor=None; public_urls=[]
    while True:
        r,_=call('/api/external/v1/products?'+urlencode({'limit':100,**({'cursor':cursor} if cursor else {})}))
        assert r.status_code==200
        data=r.json(); assert data['readAt'] and data['requestId']
        for item in data['items']:
            fields={'productId','styleCode','sku','sizes','color','category','title','summary','description','images'}
            assert set(item)==fields, 'Material fields differ: '+str(sorted(set(item)^fields))
            wanted=expected[item['productId']]
            assert item['sizes']==wanted['sizes'], 'Real size order/stock differs for test product '+str(item['productId'])
            assert item['title']==wanted['row']['title'] and item['description']==wanted['row']['description'], 'Material text differs for test product '+str(item['productId'])
            assert item['images']['gallery']==[urljoin('https://gingtto.store/',v) for v in wanted['gallery']], 'Gallery differs for test product '+str(item['productId'])
            for kind in ('main','sizeChart','detail'):
                if item['images'][kind]: public_urls.append((kind,item['images'][kind]))
            public_urls.extend(('gallery',v) for v in item['images']['gallery'] if v)
            scanned.append(item['productId'])
        cursor=data['nextCursor']
        if not cursor: break
    assert scanned==sorted(ids) and len(set(scanned))==len(expected)
    report['checks']['completePaginationWithoutDuplicates']=True
    report['checks']['materialWhitelistContentImageOrderAndRealSizes']=True
    report['checks']['noPriceOrInternalFields']=True
    missing=max(ids)+100000
    r,_=call('/api/external/v1/inventory?productIds='+str(ids[0])+','+str(missing))
    assert r.status_code==200 and r.json()['notFoundIds']==[missing]
    assert r.json()['items'][0]['sizes']==expected[ids[0]]['sizes']
    report['checks']['missingDistinctFromZeroStock']=True
    assert call('/api/external/v1/products/'+str(missing))[0].status_code==404
    assert call('/api/external/v1/products?limit=101')[0].status_code==400
    assert call('/api/external/v1/inventory?productIds='+','.join(str(x) for x in range(1,102)))[0].status_code==400
    report['checks']['boundsAndNotFound']=True
    first=expected[ids[0]]['row']
    first_category=db._fetch_one('SELECT category_id FROM products WHERE id=%s',(ids[0],))['category_id']
    cases=[('materials50','/api/external/v1/products?limit=50'),
        ('materials100','/api/external/v1/products?limit=100'),
        ('singleProduct','/api/external/v1/products/'+str(ids[0])),
        ('inventory1','/api/external/v1/inventory?productIds='+str(ids[0])),
        ('inventory50','/api/external/v1/inventory?productIds='+','.join(map(str,ids[:50]))),
        ('inventory100','/api/external/v1/inventory?productIds='+','.join(map(str,ids[:100]))),
        ('styleFilter','/api/external/v1/products?'+urlencode({'styleCodes':first['style_code']})),
        ('skuFilter','/api/external/v1/products?'+urlencode({'skus':first['sku']})),
        ('keywordFilter','/api/external/v1/products?'+urlencode({'keyword':first['style_code']})),
        ('categoryFilter','/api/external/v1/products?'+urlencode({'categoryId':first_category})),
        ('multipleStyles','/api/external/v1/products?'+urlencode({'styleCodes':','.join(dict.fromkeys(x['row']['style_code'] for x in list(expected.values())[:100]))}))]
    for label,path in cases:
        for _ in range(3): assert call(path)[0].status_code==200
        result=measure(path,args.samples)
        report['endpoints'].append({'case':label,**result})
        print(label,json.dumps(result),flush=True)
        assert result['success']==result['requests'], 'Endpoint benchmark errors: '+label
    for label,path in cases[:2]+cases[5:6]:
        for workers in (1,4,8):
            result=measure(path,max(40,args.samples*2),workers)
            report['concurrency'].append({'case':label,'clients':workers,**result})
            print('concurrency',label,workers,json.dumps(result),flush=True)
            assert result['success']==result['requests'], 'Concurrency benchmark errors'
    for limit in (50,100):
        runs=[]
        for _ in range(10):
            started=time.perf_counter(); cursor=None; seen=[]; pages=0; byte_count=0
            while True:
                response,_=call('/api/external/v1/products?'+urlencode({'limit':limit,**({'cursor':cursor} if cursor else {})}))
                assert response.status_code==200
                data=response.json(); pages+=1;byte_count+=len(response.content)
                seen.extend(item['productId'] for item in data['items']);cursor=data['nextCursor']
                if not cursor: break
            assert seen==ids
            runs.append((time.perf_counter()-started)*1000)
        report['fullSync'].append({'resource':'products','pageSize':limit,'products':len(ids),'pages':pages,'runs':len(runs),
            'p50Ms':round(percentile(runs,50),2),'p95Ms':round(percentile(runs,95),2),'responseBytes':byte_count})
    runs=[]
    for _ in range(10):
        started=time.perf_counter();seen=[];byte_count=0
        for start in range(0,len(ids),100):
            response,_=call('/api/external/v1/inventory?productIds='+','.join(map(str,ids[start:start+100])))
            assert response.status_code==200 and not response.json()['notFoundIds']
            data=response.json();byte_count+=len(response.content)
            for item in data['items']:
                assert set(item)=={'productId','styleCode','sku','sizes'}
                assert item['sizes']==expected[item['productId']]['sizes']
                seen.append(item['productId'])
        assert seen==ids
        runs.append((time.perf_counter()-started)*1000)
    report['fullSync'].append({'resource':'inventory','batchSize':100,'products':len(ids),'requests':(len(ids)+99)//100,
        'runs':10,'p50Ms':round(percentile(runs,50),2),'p95Ms':round(percentile(runs,95),2),'responseBytes':byte_count})
    if args.soak_seconds:
        def traffic(worker):
            started=time.perf_counter();rows=[];index=0
            while time.perf_counter()-started<args.soak_seconds:
                r,t=call('/api/external/v1/products?limit=100' if index%2==0 else '/api/external/v1/inventory?productIds='+','.join(map(str,ids[:100])))
                rows.append((r.status_code,t,len(r.content)));index+=1
                time.sleep(max(0,started+index*.4-time.perf_counter()))
            return rows
        def business():
            started=time.perf_counter();rows=[];index=0
            while time.perf_counter()-started<args.soak_seconds:
                tick=time.perf_counter();r=client.get('/api/admin/orders?page=1&pageSize=25')
                rows.append((r.status_code,(time.perf_counter()-tick)*1000,len(r.data)));index+=1
                time.sleep(max(0,started+index*.5-time.perf_counter()))
            return rows
        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=9) as executor:
            jobs=[executor.submit(traffic,i) for i in range(8)]
            admin_job=executor.submit(business)
            api_rows=[row for job in jobs for row in job.result()];admin_rows=admin_job.result()
        elapsed=time.perf_counter()-started
        report['sustainedMixedWorkload']={'durationSeconds':round(elapsed,3),'apiClients':8,'apiTargetRps':20,
            'api':metrics(api_rows,elapsed),'backoffice':metrics(admin_rows,elapsed)}
        assert all(row[0]==200 for row in api_rows+admin_rows),'Sustained mixed-workload errors'
        report['checks']['sustainedMixedWorkloadPassed']=True
    time.sleep(.2)
    monitor_stop.set();monitor_thread.join(timeout=5)
    with psycopg.connect(dbname=name,**config) as conn:
        current=conn.execute("SELECT count(*),count(*) FILTER(WHERE state='idle in transaction') FROM pg_stat_activity WHERE datname=current_database() AND usename=%s AND application_name='gingtto-external-api'",(role,)).fetchone()
    report['connectionBudget']={'perProcessExternalApiMax':2,'observedPeak':max((r[0] for r in monitor_observations),default=0),
        'monitorSamples':len(monitor_observations),'idleTransactionsAfterLoad':current[1],'connectionsAfterLoad':current[0]}
    assert monitor_observations and not monitor_errors and not monitor_thread.is_alive()
    assert report['connectionBudget']['observedPeak']<=2 and current[1]==0,'Connection budget/leaked transaction regression'
    report['checks']['boundedPhysicalConnectionsAndNoIdleTransactions']=True
    assert before==fingerprint()
    report['checks']['testBusinessTablesUnchangedByApiCalls']=True
    with db._connect() as conn:
        logged=conn.execute('SELECT count(*) AS n FROM api_call_logs WHERE admin_user_id=%s',(owner_id,)).fetchone()['n']
        # Values must never leak into application/request logs or log rows.
        raw=conn.execute('SELECT row_to_json(l)::text AS value FROM api_call_logs l').fetchall()
        assert all(token not in row['value'] for row in raw)
    report['authenticatedCallsLogged']=logged
    report['checks']['credentialsAbsentFromCallRecords']=True
    stop_servers()
    log.flush()
    assert token not in log_path.read_text(encoding='utf-8',errors='replace')
    report['checks']['credentialsAbsentFromServerLog']=True

    # Separate connection setup from read-only SQL time. This is a diagnostic,
    # not a pooled/cached replacement for the actual HTTP measurements above.
    connection_times=[];read_times=[]
    for _ in range(20):
        started=time.perf_counter()
        with psycopg.connect(host=config['host'],port=config['port'],dbname=name,user=role,
                password=env['EXTERNAL_API_DB_PASSWORD'],connect_timeout=5,row_factory=dict_row) as conn:
            connection_times.append((time.perf_counter()-started)*1000)
            started=time.perf_counter()
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            rows=conn.execute('SELECT * FROM external_api_products_v ORDER BY id LIMIT 100').fetchall()
            selected=[row['id'] for row in rows]
            conn.execute('SELECT * FROM external_api_sizes_v WHERE product_id=ANY(%s) ORDER BY product_id,sort_order,id',(selected,)).fetchall()
            conn.execute('SELECT * FROM external_api_images_v WHERE product_id=ANY(%s) ORDER BY product_id,sort_order,id',(selected,)).fetchall()
            read_times.append((time.perf_counter()-started)*1000)
    report['databaseDiagnostic']={'samples':20,
        'freshConnectionP50Ms':round(percentile(connection_times,50),2),
        'freshConnectionP95Ms':round(percentile(connection_times,95),2),
        'read100WithSizesAndImagesP50Ms':round(percentile(read_times,50),2),
        'read100WithSizesAndImagesP95Ms':round(percentile(read_times,95),2),
        'databaseLeasesPerAuthenticatedRead':5,'physicalConnectionsReused':True}

    # Public CDN samples are low-frequency read-only, NOT an online load test.
    # API JSON latency does not include downloading these binary files.
    picked=[];seen_urls=set()
    for kind in ('main','gallery','sizeChart','detail'):
        match=next(((k,u) for k,u in public_urls if k==kind and u not in seen_urls),None)
        if match: picked.append(match);seen_urls.add(match[1])
    from api_image_probe import ImageProbe
    proxy=(os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')) if args.image_proxy_from_env else None
    report['imageOutboundProxyExplicitlySelected']=bool(proxy)
    image_client=ImageProbe({'https://gingtto.store',*args.image_origin},proxy_url=proxy)
    try:
        for kind,url in picked[:args.image_samples]:
            report['images'].append(image_client.sample(url,kind))
            time.sleep(.5)
    finally:image_client.close()
    report['imageSamplingNote']='External network/CDN samples are separate from API acceptance; failures do not invalidate read-only API tests.'
    report['status']='passed'
except Exception as error:
    report['status']='failed'
    report['failureType']=type(error).__name__
    raise
finally:
    monitor_stop.set()
    if monitor_thread:monitor_thread.join(timeout=5)
    stop_servers();log.close()
    report['completedAt']=datetime.now(UTC).isoformat()
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Benchmark report:',args.output,flush=True)
