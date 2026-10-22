"""Browser-only synthetic database. Not a manual-preview launcher."""
import json
import os
from pathlib import Path
import sys

if os.environ.get('PGHOST')!='127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Explicit local *_test database required')
os.environ.update(APP_ENV='test',DB_SCHEMA_AUTO_MIGRATE='1',SECURITY_ADMIN_CAPTCHA_ENABLED='0',
    SECURITY_ATTACHMENT_MODE='legacy',SECURITY_LOGIN_PROTECTION_ENABLED='0',ORDER_VOICE_ENABLED='0')
root=Path(__file__).resolve().parents[1]
channel=sys.argv[1]
if channel=='admin':
    import psycopg
    from psycopg.sql import SQL, Identifier
    with psycopg.connect(host='127.0.0.1',port=os.environ['PGPORT'],dbname='postgres',user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],autocommit=True) as conn:
        name=os.environ['PGDATABASE']
        if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
            conn.execute(SQL('CREATE DATABASE {}').format(Identifier(name)))
    sys.path.insert(0,str(root/'admin-backend'))
    import test_workbench as fixture
    fixture.seed()
    from werkzeug.security import generate_password_hash
    with fixture.db.get_connection() as conn:
        conn.execute("UPDATE products SET is_active=FALSE,style_code='GT-INACTIVE' WHERE id=3")
        conn.execute("UPDATE store_users SET password_hash=%s WHERE id=1",(generate_password_hash('Workbench-Test-2026',method='pbkdf2:sha256:1000'),))
        conn.execute("""INSERT INTO orders(order_no,store_user_id,status,contact_name,phone,shipping_address,total_amount)
          SELECT 'BROWSER-'||n,1,'paid','Fixture','123','Fixture address',10 FROM generate_series(1,30) n""")
        conn.execute("UPDATE orders SET label_image_urls=%s WHERE order_no='BROWSER-30'",(json.dumps(['/uploads/fixture.jpg?attachment='+str(n) for n in range(12)]),))
    app=fixture.application.app
    port=5382
else:
    assert channel=='store'
    root=root.parent/'shopify'
    sys.path.insert(0,str(root/'storefront-backend'))
    import app as application
    app=application.app
    from flask import send_from_directory
    dist=root/'frontend/dist'
    @app.get('/')
    @app.get('/<path:path>')
    def page(path=''):
        if path.startswith('api/'):return {'message':'Not found'},404
        return send_from_directory(dist,path if (dist/path).is_file() else 'index.html')
    source=application.media.uploads['admin']/'fixture.jpg'
    target=application.media.uploads['store']/'fixture.jpg'
    if source.is_file():
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
    port=5384
app.run(host='127.0.0.1',port=port,threaded=True,use_reloader=False)
