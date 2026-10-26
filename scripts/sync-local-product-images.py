"""Read public catalog images into the local manual-service directory. No remote writes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import unquote, urlsplit

import psycopg

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'admin-backend'))
from api_image_probe import ImageProbe
from safe_images import check_image

ORIGINS={'https://img.smawell.shop','https://admin.gingtto.store','https://api-admin.smawell.shop','https://admin.smawell.shop','https://res.cloudinary.com'}

def destination(url,root,cached_key=None):
    parts=urlsplit(url)
    origin='https://'+parts.netloc
    if parts.scheme!='https' or origin not in ORIGINS or parts.username or parts.password or parts.fragment:
        raise ValueError('Unrecognized catalog image origin')
    path=unquote(parts.path)
    if parts.netloc!='res.cloudinary.com' and path.startswith('/uploads/'):
        key=path[len('/uploads/'):]
        if '\\' in key or any(p in {'','.','..'} for p in key.split('/')):raise ValueError('Invalid upload path')
        download='https://admin.gingtto.store/uploads/'+parts.path[len('/uploads/'):]
    else:
        key=cached_key or 'local-product-cache/'+str(uuid.uuid4())+'.source'
        download=url
    target=(root/key).resolve()
    if not target.is_relative_to(root.resolve()):raise ValueError('Invalid destination')
    return key,target,download

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--upload-dir',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--proxy-from-env',action='store_true')
    args=parser.parse_args()
    if os.environ.get('PGHOST')!='127.0.0.1' or os.environ.get('PGPORT')!='55439' or not (os.environ.get('PGDATABASE')=='lumiere_admin' or os.environ.get('PGDATABASE','').endswith('_test')):
        raise SystemExit('Only the explicitly configured local mirror or *_test database is supported')
    with psycopg.connect() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        rows=conn.execute('SELECT main_image_url FROM products UNION SELECT image_url FROM product_images UNION SELECT size_chart_image_url FROM products UNION SELECT description_image_url FROM products').fetchall()
    urls=sorted({r[0] for r in rows if r[0]})
    root=args.upload_dir.resolve();root.mkdir(parents=True,exist_ok=True)
    manifest=root/'local-product-images.json'
    previous=json.loads(manifest.read_text('utf-8')) if manifest.exists() else {}
    def fetch(url):
        try:
            key,path,remote=destination(url,root,previous.get(url))
            if path.is_file():
                check_image(path.read_bytes())
                return {'url':url,'path':key,'status':'existing'}
            probe=ImageProbe(ORIGINS,proxy_url=os.environ.get('HTTPS_PROXY') if args.proxy_from_env else None,
                connect_seconds=8,read_seconds=12,budget_seconds=45,max_bytes=32*1024*1024,max_attempts=2)
            try:result=probe.sample(remote,destination=path)
            finally:probe.close()
            return {'url':url,'path':key,'status':'failed' if result.get('error') else 'downloaded','result':result}
        except Exception as exc:return {'url':url,'status':'failed','error':type(exc).__name__}
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index,result in enumerate(pool.map(fetch,urls),1):
            results.append(result)
            if index%25==0:print(f'Images checked {index}/{len(urls)}',flush=True)
    mapping={**previous,**{r['url']:r['path'] for r in results if r['status']!='failed'}}
    temp=manifest.with_suffix('.tmp');temp.write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(manifest)
    report={'images':len(urls),'downloaded':sum(r['status']=='downloaded' for r in results),'existing':sum(r['status']=='existing' for r in results),'failed':sum(r['status']=='failed' for r in results),'results':results}
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'}),flush=True)
    return 1 if report['failed'] else 0

if __name__=='__main__':raise SystemExit(main())
