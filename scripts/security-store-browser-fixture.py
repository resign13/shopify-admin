"""Storefront sidecar for an already-seeded, isolated security browser DB."""
import os
from pathlib import Path
import sys
if os.environ.get('PGHOST')!='127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test target required')
os.environ.update(APP_ENV='test',DB_SCHEMA_AUTO_MIGRATE='0',PRIVATE_STORAGE_BUCKET='')
root=Path(__file__).resolve().parents[1].parent/'shopify'
sys.path.insert(0,str(root/'storefront-backend'))
import app as application
import db
if os.environ.get('SECURITY_ATTACHMENT_MODE', 'legacy') == 'legacy':
    # The synthetic catalog uses a relative shared product image. Production
    # keeps its existing image-host routing; only this fixture needs a copy.
    source=application.media.uploads['admin']/'fixture.jpg'
    target=application.media.uploads['store']/'fixture.jpg'
    if source.is_file():
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(source.read_bytes())
from werkzeug.security import generate_password_hash
with db._connect() as conn:
    if not conn.execute("SELECT 1 FROM store_users WHERE email='security-second@fixture.test'").fetchone():
        conn.execute("INSERT INTO store_users(name,email,password_hash,status) VALUES('Second security fixture','security-second@fixture.test',%s,'active')",
            (generate_password_hash('Store-Fixture-Password-2026',method='pbkdf2:sha256:1000'),))
from flask import send_from_directory
dist=root/'frontend/dist'
@application.app.get('/')
@application.app.get('/<path:path>')
def page(path=''):
    if path.startswith('api/'): return {'message':'Not found'},404
    return send_from_directory(dist,path if (dist/path).is_file() else 'index.html')
application.app.run(host='127.0.0.1',port=5364,threaded=True,use_reloader=False)
