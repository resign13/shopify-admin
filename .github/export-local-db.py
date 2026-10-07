"""Read a consistent snapshot over verified SSH; upload encrypted bytes only."""
import base64
import gzip
import json
import os
from pathlib import Path
import subprocess
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REMOTE = r'''
import os, json, subprocess, hashlib
from pathlib import Path
import psycopg
from psycopg.sql import SQL, Identifier
settings={}
for line in Path('/opt/smawell/shopify-admin/admin-backend/.env').read_text().splitlines():
 if '=' in line and not line.strip().startswith('#'):
  k,v=line.split('=',1);settings[k.strip()]=v.strip().strip('"').strip("'")
assert settings['PGDATABASE']=='smawell_admin'
assert settings.get('PGHOST','127.0.0.1') in ('127.0.0.1','localhost')
environment={**os.environ,**{k:v for k,v in settings.items() if k.startswith('PG')}}
with psycopg.connect(host=settings.get('PGHOST','127.0.0.1'),port=settings.get('PGPORT','5432'),dbname='smawell_admin',user=settings['PGUSER'],password=settings.get('PGPASSWORD','')) as conn:
 conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
 conn.execute("SET TIME ZONE 'UTC'")
 snapshot=conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
 tables=[r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
 fingerprints={t:list(conn.execute(SQL("SELECT count(*),md5(COALESCE(string_agg(to_jsonb(t)::text,E'\\n' ORDER BY to_jsonb(t)::text),'')) FROM {} t").format(Identifier(t))).fetchone()) for t in tables}
 sql=subprocess.check_output(['pg_dump','--snapshot='+snapshot,'--no-owner','--no-acl','--inserts','--rows-per-insert=100','smawell_admin'],env=environment,text=True)
 print(json.dumps({'sql':sql,'sha256':hashlib.sha256(sql.encode()).hexdigest(),'tables':fingerprints}))
'''

known = Path(os.environ['RUNNER_TEMP']) / 'db-sync-known-hosts'
known.write_text(os.environ['DEPLOY_KNOWN_HOSTS'])
known.chmod(0o600)
command = ['sshpass','-e','ssh','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),'-o','ConnectTimeout=30',os.environ['DEPLOY_USER']+'@'+os.environ['DEPLOY_HOST'],"flock -s -w 600 /var/lock/smawell-deploy.lock /opt/smawell/shopify-admin/admin-backend/.venv/bin/python -"]
raw = subprocess.check_output(command, input=REMOTE.encode(), timeout=900)
# The dump exists in memory only. The uploaded file contains authenticated ciphertext.
key = AESGCM.generate_key(bit_length=256)
nonce = os.urandom(12)
public = serialization.load_pem_public_key(Path('.github/db-sync-public.pem').read_bytes())
payload = AESGCM(key).encrypt(nonce, gzip.compress(raw), b'gingtto-db-sync-v1')
wrapped = public.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
Path('database.enc').write_text(json.dumps({k:base64.b64encode(v).decode() for k,v in {'key':wrapped,'nonce':nonce,'payload':payload}.items()}))
print('Read-only snapshot encrypted for the local workstation.')
