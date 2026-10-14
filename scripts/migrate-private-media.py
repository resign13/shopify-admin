"""Explicit local/staged backfill. Never discovers files by anonymous listing.

Only saved database references are classified. Originals are not deleted. The
completion marker is written only after ALL references have valid private copies.
External-object/CDN closure is a separate mandatory deployment gate.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import re
import ssl
import http.client
import time
from threading import Lock
from urllib.parse import unquote, urlsplit

parser=argparse.ArgumentParser()
parser.add_argument('--backend',default='admin-backend')
parser.add_argument('--expected-db',required=True)
parser.add_argument('--report',required=True)
parser.add_argument('--workers',type=int,default=4)
parser.add_argument('--download-timeout',type=int,default=60,help='Bounded timeout for offline migration only; runtime export limits stay unchanged')
parser.add_argument('--network-attempts',type=int,default=1,help='Bounded retries for interrupted static downloads')
parser.add_argument('--local-only',action='store_true',help='Forbid remote targets and private object-store writes')
parser.add_argument('--source-db',help='Read verified local file copies from the preserved sync backup; local-only mode required')
parser.add_argument('--use-configured-proxy',action='store_true',help='Local-only: explicitly tunnel validated public IPs through this computer\'s configured HTTP proxy')
args=parser.parse_args()
if args.source_db and (not args.local_only or not re.fullmatch(re.escape(args.expected_db)+r'_backup_\d{8}_\d{6}',args.source_db)):
    raise SystemExit('Source database must be a preserved local sync backup')
proxy_url=None
if args.use_configured_proxy:
    if not args.local_only: raise SystemExit('Configured migration proxy requires local-only mode')
    proxy_url=os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if not proxy_url: raise SystemExit('This computer has no configured HTTPS proxy')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/args.backend))
import db
if db.DB_NAME!=args.expected_db: raise SystemExit('Database confirmation does not match')
if not 1 <= args.workers <= 6: raise SystemExit('Worker count must be between 1 and 6')
if not 15 <= args.download_timeout <= 90: raise SystemExit('Download timeout must be between 15 and 90 seconds')
if not 1 <= args.network_attempts <= 3: raise SystemExit('Network attempts must be between 1 and 3')
if args.local_only:
    if db.DB_HOST != '127.0.0.1': raise SystemExit('Local-only migration requires a loopback database')
    os.environ['PRIVATE_STORAGE_BUCKET']=''
from flask import Flask
from private_media import Media
db.load_env_file(Path(__file__).resolve().parents[1]/args.backend/".env.security")
if args.local_only: os.environ['PRIVATE_STORAGE_BUCKET']=''
from private_media import attachment_urls, file_id
from safe_images import fetch_file, MAX_BYTES
media=Media(Flask('media-migration'),db,'admin',Path(__file__).resolve().parents[1]/args.backend)
references=[]
with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    for row in conn.execute('SELECT id,main_image_url,size_chart_image_url,description_image_url FROM products'):
        for key in ('main_image_url','size_chart_image_url','description_image_url'):
            if row[key]: references.append((row[key],'product',row['id'],'product'))
    for row in conn.execute('SELECT product_id,image_url FROM product_images'):
        if row['image_url']: references.append((row['image_url'],'product',row['product_id'],'product'))
    for row in conn.execute('SELECT id,label_image_urls,label_pdf_url FROM orders'):
        for url in attachment_urls({'labelImageUrls':row['label_image_urls'],'labelPdfUrl':row['label_pdf_url']}): references.append((url,'order',row['id'],'legacy-private'))
    for row in conn.execute('SELECT id,document FROM admin_order_drafts'):
        for url in attachment_urls(row['document']): references.append((url,'draft',row['id'],'legacy-private'))
    for row in conn.execute('SELECT id,customer_info FROM order_customer_templates'):
        for url in attachment_urls(row['customer_info']): references.append((url,'template',row['id'],'legacy-private'))
    for row in conn.execute('SELECT id,snapshot FROM purchase_contracts'):
        data=row['snapshot']; urls=attachment_urls(data)+[data.get('styleImage'),data.get('sizeChartImage')]
        for item in data.get('items',[]): urls.extend([item.get('image'),item.get('sizeChartImage')])
        for url in set(u for u in urls if u): references.append((url,'contract',row['id'],'legacy-private'))

# A fixed sync replaces the mirror, but its backup retains the previously
# classified registry. Reuse only checksum-verified bytes, not old ownership or
# business references. The backup is never migrated, modified or deleted.
local_sources={}
if args.source_db:
    with db._connect(args.source_db) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if conn.execute("SELECT to_regclass('public.security_files') AS present").fetchone()['present']:
            hashes=list({hashlib.sha256(str(url).strip().encode()).hexdigest() for url,_,_,_ in references})
            for row in conn.execute('SELECT * FROM security_files WHERE origin_hash=ANY(%s)',(hashes,)):
                local_sources.setdefault(row['origin_hash'],[]).append(row)
cache_hits=0
cache_lock=Lock()

def download(url):
    for attempt in range(args.network_attempts):
        try:
            return fetch_file(url,image_only=False,timeout_seconds=args.download_timeout,
                              request_timeout_seconds=min(30,args.download_timeout),proxy_url=proxy_url)
        except (TimeoutError,ConnectionError,ssl.SSLEOFError,http.client.RemoteDisconnected,http.client.IncompleteRead):
            if attempt+1 == args.network_attempts: raise
            time.sleep(attempt+1)

def source(url):
    global cache_hits
    registered=media.find(url)
    if registered:
        try: return media.read(registered),registered['storage_channel']
        except FileNotFoundError: pass
    key=hashlib.sha256(str(url).strip().encode()).hexdigest()
    for row in local_sources.get(key,[]):
        try:
            raw=media.read(row)
        except (FileNotFoundError,ValueError):
            continue
        with cache_lock: cache_hits+=1
        return raw,row['storage_channel']
    p=urlsplit(url)
    if p.path.startswith('/uploads/'):
        name=unquote(p.path[len('/uploads/'):])
        for channel,root in media.uploads.items():
            candidate=(root/name).resolve()
            if root in candidate.parents and candidate.is_file() and candidate.stat().st_size<=MAX_BYTES:
                return candidate.read_bytes(),channel
        # Absolute legacy public URLs are already a verified delivery route.
        # Do not force them through an unavailable object-store endpoint just
        # because their path starts with /uploads/. DNS pinning, TLS, origin,
        # redirect, content and size validation still apply to every download.
        if p.scheme == 'https' and p.hostname:
            return download(url),'admin'
        # Object storage is addressed by an owned key, never a caller's URL.
        if os.environ.get('R2_BUCKET'):
            from image_delivery import r2_client
            obj=r2_client().get_object(Bucket=os.environ['R2_BUCKET'],Key=name)
            body=obj['Body']
            try: raw=body.read(MAX_BYTES+1)
            finally: body.close()
            if len(raw)>MAX_BYTES: raise ValueError('Attachment exceeds size limit')
            return raw,'admin'
    return download(url),'admin'

groups={}
for url,kind,identity,purpose in dict.fromkeys(references):
    groups.setdefault(url,[]).append((kind,identity,purpose))
reference_count=sum(len(refs) for refs in groups.values())

def classify(item):
    url,refs=item
    failed=[];verified=0
    try:
        if file_id(url):
            row=media.find(url)
            if not row: raise ValueError('Registered file is missing')
            media.read(row)
            with db.get_connection() as conn:
                for kind,identity,_ in refs:
                    conn.execute('INSERT INTO security_file_refs VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(row['id'],kind,identity))
        else:
            raw,channel=source(url)
            # A shared old URL is fetched once, but public and private purposes
            # still create independent storage objects and reference lists.
            for kind,identity,purpose in refs:
                media.register_legacy(url,raw,purpose=purpose,entity_type=kind,entity_id=identity,storage_channel=channel)
        verified=len(refs)
    except Exception as exc:
        # Identifiers are hashes; report contains no URLs, customer names or bodies.
        failed=[{'referenceHash':hashlib.sha256(url.encode()).hexdigest(),'kind':kind,'errorType':type(exc).__name__} for kind,_,_ in refs]
    return verified,failed

with db.get_connection() as conn:
    conn.execute("DELETE FROM security_media_migrations WHERE name='legacy-private-v1'")
failures=[];copied=0
report=Path(args.report).resolve();report.parent.mkdir(parents=True,exist_ok=True)
def write_report(complete=False):
    temporary=report.with_suffix(report.suffix+'.tmp')
    temporary.write_text(json.dumps({'complete':complete,'references':reference_count,'referenceOccurrences':len(references),
        'uniqueSources':len(groups),'verified':copied,'cachedSourcesReused':cache_hits,'failures':failures},indent=2),encoding='utf-8')
    temporary.replace(report)
write_report()
with ThreadPoolExecutor(max_workers=args.workers) as pool:
    for verified,failed in pool.map(classify,groups.items()):
        copied+=verified;failures.extend(failed)
        write_report()
if not failures:
    with db.get_connection() as conn:
        conn.execute("INSERT INTO security_media_migrations(name) VALUES('legacy-private-v1') ON CONFLICT DO NOTHING")
write_report(complete=True)
print(json.dumps({'references':reference_count,'verified':copied,'failed':len(failures)}))
if failures: raise SystemExit(1)
