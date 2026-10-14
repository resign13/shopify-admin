"""Independent database + registered-file restore rehearsal, fixture DBs only.

Uses a consistent typed snapshot, matching the existing local sync protocol.
Never accepts a production/mirror database, overwrites an existing target, or
restores cloned login sessions for use. The archive contains synthetic data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from zipfile import ZipFile, ZIP_DEFLATED
from flask import Flask
from psycopg import sql

parser=argparse.ArgumentParser()
parser.add_argument('--source',required=True)
parser.add_argument('--target',required=True)
parser.add_argument('--archive',required=True)
args=parser.parse_args()
if os.environ.get('PGHOST')!='127.0.0.1' or os.environ.get('PGDATABASE')!=args.source:
    raise SystemExit('Explicit local source required')
if any(not re.fullmatch(r'[a-z0-9_]+_test',name) for name in [args.source,args.target]) or args.source==args.target:
    raise SystemExit('Two distinct isolated *_test databases required')
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'admin-backend'))
import db
from private_media import Media
media=Media(Flask('restore-fixture'),db,'admin',root/'admin-backend')

def fingerprint(conn):
    names=[r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    return {name:dict(conn.execute(sql.SQL("SELECT COUNT(*) AS rows,md5(COALESCE(string_agg(to_jsonb(t)::text,'|' ORDER BY to_jsonb(t)::text),'')) AS digest FROM public.{} t").format(sql.Identifier(name))).fetchone()) for name in names}

archive=Path(args.archive).resolve();archive.parent.mkdir(parents=True,exist_ok=True)
if archive.exists(): raise SystemExit('Archive already exists; preserve it and use a fresh filename')
snapshot={'tables':{},'sequences':{},'fingerprint':{},'legacyUploads':[]}
with db._connect() as conn,ZipFile(archive,'x',ZIP_DEFLATED) as bundle:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    snapshot['fingerprint']=fingerprint(conn)
    for name in snapshot['fingerprint']:
        columns=[dict(r) for r in conn.execute("SELECT a.attname AS name,format_type(a.atttypid,a.atttypmod) AS type FROM pg_attribute a WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum",('public.'+name,))]
        fields=[sql.SQL('{}::text AS {}').format(sql.Identifier(c['name']),sql.Identifier(c['name'])) if c['type'] in {'json','jsonb'} else sql.Identifier(c['name']) for c in columns]
        rows=[dict(row) for row in conn.execute(sql.SQL('SELECT {} FROM public.{}').format(sql.SQL(',').join(fields),sql.Identifier(name)))]
        snapshot['tables'][name]={'columns':columns,'rows':rows}
    for row in conn.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public'"):
        snapshot['sequences'][row['sequencename']]=dict(conn.execute(sql.SQL('SELECT last_value,is_called FROM public.{}').format(sql.Identifier(row['sequencename']))).fetchone())
    files=conn.execute('SELECT * FROM security_files').fetchall()
    for row in files:
        bundle.writestr('files/'+row['storage_channel']+'/'+row['storage_key'],media.read(row))
    # The current phase preserves legacy uploads, so the backup rehearsal must
    # cover them too. Only fixture-isolated roots are used; no manual/production
    # upload folder is scanned or restored.
    for channel, directory in media.uploads.items():
        if not directory.exists(): continue
        for path in sorted(directory.rglob('*')):
            if path.is_symlink(): raise ValueError('Symlink in fixture uploads')
            if not path.is_file(): continue
            if directory.resolve() not in path.resolve().parents or path.stat().st_size>32*1024*1024:
                raise ValueError('Invalid fixture upload')
            key=path.relative_to(directory).as_posix();raw=path.read_bytes()
            snapshot['legacyUploads'].append({'channel':channel,'key':key,'sha256':hashlib.sha256(raw).hexdigest()})
            bundle.writestr('legacy_uploads/'+channel+'/'+key,raw)
    bundle.writestr('snapshot.json',json.dumps(snapshot,ensure_ascii=False,default=str))
archive.chmod(0o600)
with db._connect('postgres',autocommit=True) as conn:
    if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(args.target,)).fetchone():
        raise SystemExit('Target already exists; no overwrite was performed')
    conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(args.target)))
env=os.environ.copy();env.update(PGDATABASE=args.target,APP_ENV='test',DB_SCHEMA_AUTO_MIGRATE='0',PRIVATE_STORAGE_BUCKET='')
migrated=subprocess.run([sys.executable,str(root/'scripts/migrate-database.py'),'--expected-db',args.target],env=env,capture_output=True)
if migrated.returncode: raise SystemExit('Restore target schema preparation failed; archive retained')
with ZipFile(archive) as bundle,db._connect(args.target) as conn:
    restored=json.loads(bundle.read('snapshot.json'))
    conn.execute("SET LOCAL session_replication_role='replica'")
    conn.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY CASCADE').format(sql.SQL(',').join(sql.Identifier(name) for name in restored['tables'])))
    for name,table in restored['tables'].items():
        columns=table['columns']
        statement=sql.SQL('INSERT INTO public.{} ({}) OVERRIDING SYSTEM VALUE VALUES ({})').format(sql.Identifier(name),sql.SQL(',').join(sql.Identifier(c['name']) for c in columns),sql.SQL(',').join(sql.SQL('%s::'+c['type']) for c in columns))
        with conn.cursor() as cursor:
            cursor.executemany(statement,[[row[c['name']] for c in columns] for row in table['rows']])
    for name,state in restored['sequences'].items():conn.execute('SELECT setval(%s::regclass,%s,%s)',('public.'+name,state['last_value'],state['is_called']))
    assert fingerprint(conn)==restored['fingerprint'],'Restored table fingerprints differ'
    # Verify recovered files independently, without replacing the live roots.
    recovered=archive.parent/('restored-files-'+args.target)
    rows=conn.execute('SELECT * FROM security_files').fetchall()
    for channel in ('admin','store'):
        path=(recovered/channel).resolve();path.mkdir(parents=True,exist_ok=True);media.roots[channel]=path
    for row in rows:
        key=row['storage_key'];target=(media.roots[row['storage_channel']]/key).resolve()
        assert media.roots[row['storage_channel']] in target.parents,'Unsafe recovery key'
        with target.open('xb') as output:output.write(bundle.read('files/'+row['storage_channel']+'/'+key))
        target.chmod(0o600);media.read(row)
    for row in restored['legacyUploads']:
        directory=(archive.parent/('restored-legacy-'+args.target)/row['channel']).resolve()
        target=(directory/row['key']).resolve()
        assert directory in target.parents,'Unsafe legacy recovery key'
        target.parent.mkdir(parents=True,exist_ok=True)
        raw=bundle.read('legacy_uploads/'+row['channel']+'/'+row['key'])
        assert hashlib.sha256(raw).hexdigest()==row['sha256'],'Recovered legacy file hash differs'
        with target.open('xb') as output:output.write(raw)
        target.chmod(0o600)
    conn.execute('DELETE FROM store_sessions');conn.execute('DELETE FROM admin_sessions')
print(json.dumps({'verifiedTables':len(snapshot['tables']),'recoveredFiles':len(files),
    'recoveredLegacyUploads':len(snapshot['legacyUploads']),
    'tableFingerprintsMatch':True,'fileHashesMatch':True,'clonedSessionsCleared':True,'productionTouched':False}))
