"""One-way encrypted production export -> validated local database swap.

No production writes. Credentials remain in GitHub deployment secrets.
Private decryption key is protected with the current Windows user's DPAPI.
"""
import argparse
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import socket
import time
import msvcrt

import psycopg
from psycopg.sql import SQL, Identifier
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path.home() / '.codex/private/gingtto-db-sync'
GH = Path('C:/Program Files/GitHub CLI/gh.exe')
REPO = 'resign13/shopify-admin'
BRANCH = 'ops/database-sync'
TARGET = 'lumiere_admin'


def ensure_local_postgres():
    with socket.socket() as probe:
        probe.settimeout(2)
        if probe.connect_ex(('127.0.0.1', 55439)) == 0:
            return
    # Restart this existing dedicated cluster after a computer reboot, never
    # create/reinitialize a cluster or touch the unrelated local port 5432.
    runtime = ROOT.parent / 'output/qa-runtime'
    data = runtime / 'pgdata'
    control = runtime / 'node_modules/@embedded-postgres/windows-x64/native/bin/pg_ctl.exe'
    if not control.is_file() or not (data / 'PG_VERSION').is_file():
        raise RuntimeError('Dedicated local PostgreSQL runtime missing; previous backups preserved')
    subprocess.run([str(control), 'start', '-D', str(data), '-l', str(runtime / 'postgres.log'),
                    '-o', '-h 127.0.0.1 -p 55439', '-w', '-t', '60'],
                   check=True, timeout=75, creationflags=subprocess.CREATE_NO_WINDOW,
                   stdout=subprocess.DEVNULL)

def dpapi(data, protect):
    class Blob(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError()
    result = ctypes.string_at(output.data, output.length)
    ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    ctypes.windll.kernel32.LocalFree(output.data)
    return result

def init_key():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    key_path = PRIVATE / 'private-key.dpapi'
    if key_path.exists():
        key = serialization.load_pem_private_key(dpapi(key_path.read_bytes(), False), password=None)
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        key_path.write_bytes(dpapi(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), True))
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    (ROOT / '.github/db-sync-public.pem').write_bytes(public)
    print('Local DPAPI-protected key initialized; public key only is exported.')

def gh(*args):
    return subprocess.check_output([str(GH), *args], text=True, encoding='utf-8').strip()

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True, encoding='utf-8').strip()

def settings():
    config = {}
    for line in (ROOT / 'admin-backend/.env').read_text('utf-8').splitlines():
        if '=' in line and not line.strip().startswith('#'):
            key, value = line.split('=', 1)
            config[key.strip()] = value.strip().strip('\"').strip("'")
    # Dedicated local mirror; never use an environment-supplied remote hostname.
    return dict(host='127.0.0.1', port=55439, user=config.get('PGUSER', 'postgres'), password=config.get('PGPASSWORD', ''), connect_timeout=10)

def fingerprint(conn):
    conn.execute("SET TIME ZONE 'UTC'")
    conn.execute('SET search_path TO public')
    tables = [row[0] for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    return {table: list(conn.execute(SQL('SELECT count(*),md5(COALESCE(string_agg(to_jsonb(t)::text,E\'\\n\' ORDER BY to_jsonb(t)::text COLLATE "C"),\'\')) FROM {} t').format(Identifier(table))).fetchone()) for table in tables}

def sync():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE / 'sync.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1): lock.write(b'0'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        return run_sync()

def run_sync():
    config = settings()
    ensure_local_postgres()
    # Fail before dispatch if the dedicated local server is unavailable.
    with psycopg.connect(**config, dbname='postgres') as conn:
        conn.execute('SELECT 1')
    started = datetime.now(timezone.utc).isoformat()
    # The existing account can push and read CI, but has no workflow-dispatch scope.
    # Request exports via this dedicated push-only operations branch, not main.
    git('fetch', 'origin', BRANCH)
    parent = git('rev-parse', 'origin/'+BRANCH)
    tree = git('rev-parse', parent+'^{tree}')
    revision = git('commit-tree', tree, '-p', parent, '-m', 'ops: request database snapshot '+started)
    git('push', 'origin', revision+':refs/heads/'+BRANCH)
    run = None
    for attempt in range(30):
        runs = json.loads(gh('run', 'list', '--repo', REPO, '--workflow', 'deploy.yml', '--branch', BRANCH, '--limit', '5', '--json', 'databaseId,createdAt,url,headSha'))
        run = next((item for item in runs if item['headSha'] == revision), None)
        if run: break
        time.sleep(3)
    if not run: raise RuntimeError('Database export run not found')
    folder = PRIVATE / str(run['databaseId'])
    folder.mkdir()
    with (folder / 'export-run.log').open('w', encoding='utf-8') as log:
        subprocess.run([str(GH), 'run', 'watch', str(run['databaseId']), '--repo', REPO, '--interval', '15', '--exit-status'], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
    gh('run', 'download', str(run['databaseId']), '--repo', REPO, '--name', 'encrypted-local-db', '--dir', str(folder))
    envelope = json.loads((folder / 'database.enc').read_bytes())
    private = serialization.load_pem_private_key(dpapi((PRIVATE / 'private-key.dpapi').read_bytes(), False), password=None)
    key = private.decrypt(base64.b64decode(envelope['key']), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    archive = AESGCM(key).decrypt(base64.b64decode(envelope['nonce']), base64.b64decode(envelope['payload']), b'gingtto-db-sync-v1')
    payload = json.loads(gzip.decompress(archive))
    sql = payload['sql']
    assert hashlib.sha256(sql.encode()).hexdigest() == payload['sha256']
    sql = re.sub(r'^\\(?:un)?restrict[^\n]*$', '', sql, flags=re.MULTILINE)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    stage = 'gingtto_sync_stage_' + stamp
    backup = TARGET + '_backup_' + stamp
    switched = False
    with psycopg.connect(**config, dbname='postgres', autocommit=True) as management:
        management.execute(SQL('CREATE DATABASE {}').format(Identifier(stage)))
        try:
            with psycopg.connect(**config, dbname=stage) as staged:
                staged.execute(sql, prepare=False)
                actual = fingerprint(staged)
                if actual != payload['tables']:
                    mismatches = {table:{'expected':payload['tables'].get(table),'actual':actual.get(table)} for table in set(actual)|set(payload['tables']) if actual.get(table)!=payload['tables'].get(table)}
                    (folder / 'fingerprint-mismatch.json').write_text(json.dumps(mismatches,indent=2),encoding='utf-8')
                    raise RuntimeError('Restored snapshot fingerprint mismatch: '+json.dumps(mismatches))
                # Production sessions stay production-only; business records stay intact.
                for table in ('admin_sessions', 'store_sessions'):
                    if table in actual: staged.execute(SQL('DELETE FROM {}').format(Identifier(table)))
            existing = bool(management.execute('SELECT 1 FROM pg_database WHERE datname=%s', (TARGET,)).fetchone())
            # Migrate the validated staging database before switching. A failed
            # local migration must leave the previous usable mirror untouched.
            environment = {**os.environ, 'PGHOST':'127.0.0.1', 'PGPORT':'55439',
                           'PGDATABASE':stage, 'PGUSER':config['user'], 'PGPASSWORD':config['password']}
            for backend in (ROOT / 'admin-backend', ROOT.parent / 'shopify/storefront-backend'):
                subprocess.run([os.sys.executable, '-c', 'import app'], cwd=backend, env=environment,
                               check=True, timeout=120, stdout=subprocess.DEVNULL)
            # Storefront login sessions are local JSON, not a PostgreSQL table.
            # Never carry a session bound to an old fixture user ID into the mirror.
            sessions = ROOT.parent / 'shopify/storefront-backend/data/sessions.json'
            if sessions.exists():
                (folder / 'store-sessions-before-sync.json').write_bytes(sessions.read_bytes())
                sessions.write_text('[]', encoding='utf-8')
            management.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = ANY(%s) AND pid<>pg_backend_pid()', ([TARGET, stage],))
            with management.transaction():
                if existing: management.execute(SQL('ALTER DATABASE {} RENAME TO {}').format(Identifier(TARGET), Identifier(backup)))
                management.execute(SQL('ALTER DATABASE {} RENAME TO {}').format(Identifier(stage), Identifier(TARGET)))
            switched = True
        finally:
            if not switched and stage.startswith('gingtto_sync_stage_'):
                management.execute(SQL('DROP DATABASE {} WITH (FORCE)').format(Identifier(stage)))
    # Both applications point to the same dedicated local mirror.
    for path in (ROOT / 'admin-backend/.env', ROOT.parent / 'shopify/storefront-backend/.env'):
        text = path.read_text('utf-8')
        for key, value in {'PGHOST':'127.0.0.1', 'PGPORT':'55439', 'PGDATABASE':TARGET}.items():
            if re.search(r'^'+key+r'=', text, re.MULTILINE): text = re.sub(r'^'+key+r'=.*$', key+'='+value, text, flags=re.MULTILINE)
            else: text += '\n'+key+'='+value+'\n'
        path.write_text(text, encoding='utf-8')
    result = {'syncedAt':datetime.now(timezone.utc).isoformat(), 'source':'production read-only snapshot', 'localDatabase':TARGET, 'localPort':55439, 'backupDatabase':backup if existing else None, 'verifiedTables':len(actual), 'orders':actual.get('orders',[0])[0], 'products':actual.get('products',[0])[0], 'run':run['url']}
    (PRIVATE / 'last-sync.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (folder / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    # Encrypted CI artifacts expire automatically after one day.
    print(json.dumps(result))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--init-key', action='store_true')
    args = parser.parse_args()
    init_key() if args.init_key else sync()

