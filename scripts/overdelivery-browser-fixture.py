"""Deterministic UI fixture, explicit local *_test database only."""
import os
import sys
from pathlib import Path
if os.environ.get('PGHOST')!='127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Explicit isolated test database required')
import psycopg
from psycopg.sql import SQL, Identifier
with psycopg.connect(host='127.0.0.1',port=os.environ['PGPORT'],dbname='postgres',
                     user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],autocommit=True) as management:
    name=os.environ['PGDATABASE']
    if not management.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
        management.execute(SQL('CREATE DATABASE {}').format(Identifier(name)))
from PIL import Image
uploads=Path(__file__).resolve().parents[1]/'admin-backend/uploads'
uploads.mkdir(exist_ok=True)
Image.new('RGB',(160,160),'#334155').save(uploads/'fixture.jpg')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'admin-backend'))
os.environ['ORDER_VOICE_ENABLED']='0'
from test_inventory_overdelivery import OverdeliveryTest
import test_workbench as fixtures
if __name__=='__main__':
    case=OverdeliveryTest();case.setUp();case.prepare({'M':100,'L':7})
    fixtures.application.app.run(host='127.0.0.1',port=5359,threaded=True,use_reloader=False)
