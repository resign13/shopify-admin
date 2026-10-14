"""Isolated staff permission UI fixture; never writes to the local mirror."""
import os
import sys
from pathlib import Path
import psycopg
from psycopg.sql import SQL, Identifier
from werkzeug.security import generate_password_hash

name = os.environ.get('PGDATABASE', '')
if os.environ.get('PGHOST') != '127.0.0.1' or not name.endswith('_test'):
    raise RuntimeError('Explicit loopback *_test fixture required')
with psycopg.connect(host='127.0.0.1', port=os.environ['PGPORT'], dbname='postgres',
                     user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'], autocommit=True) as conn:
    if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
        conn.execute(SQL('CREATE DATABASE {} TEMPLATE template0').format(Identifier(name)))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
os.environ.update(APP_ENV='test', DB_SCHEMA_AUTO_MIGRATE='1', ORDER_VOICE_ENABLED='0')
import test_workbench as fixtures

if __name__ == '__main__':
    # Browser fixture only: a predictable drawing lets the UI test type what
    # the image contains. Release packaging explicitly excludes fixture files.
    from unittest.mock import patch
    fixture_code=patch('login_captcha.random_code',return_value='AB7CD')
    fixture_code.start()
    fixtures.seed()
    fixtures.db.create_admin_user({'name':'财务测试员','email':'finance@gingtto.test',
        'passwordHash':generate_password_hash('Workbench-Test-2026',method='pbkdf2:sha256:1000'),
        'status':'active','role':'finance'})
    fixtures.application.app.run(host='127.0.0.1',port=5364,threaded=True,use_reloader=False)
