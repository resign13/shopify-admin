"""Isolated browser QA server. Never start this against the manual mirror."""
import os
import sys
from pathlib import Path

if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Browser fixtures require an explicit local *_test database')
# CI's PostgreSQL service creates only the regression database. Prepare this
# separately named browser database before importing application initialization.
import psycopg
from psycopg.sql import SQL, Identifier
with psycopg.connect(host='127.0.0.1', port=os.environ['PGPORT'], dbname='postgres',
                      user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'], autocommit=True) as management:
    name = os.environ['PGDATABASE']
    if not management.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
        management.execute(SQL('CREATE DATABASE {}').format(Identifier(name)))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'admin-backend'))
os.environ['ORDER_VOICE_ENABLED']='1'
os.environ['ORDER_VOICE_CURSOR_SECRET']='fixture-only-signing-key-not-for-production'
import test_workbench as fixtures

if __name__ == '__main__':
    fixtures.seed()
    fixtures.application.app.run(host='127.0.0.1',port=5358,threaded=True,use_reloader=False)
