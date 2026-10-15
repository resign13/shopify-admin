"""Synthetic browser acceptance services. Explicit local *_test database only."""
import os
from pathlib import Path
import sys

if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')
os.environ.update(APP_ENV='test', ORDER_VOICE_ENABLED='0', SECURITY_ADMIN_CAPTCHA_ENABLED='0')
root=Path(__file__).resolve().parents[1]
store='--store' in sys.argv
backend=root.parent/'shopify/storefront-backend' if store else root/'admin-backend'
sys.path.insert(0,str(backend))
os.environ['DB_SCHEMA_AUTO_MIGRATE']='0' if store else '1'
import db
import app as application
if not store:
    from test_workbench import seed
    tokens,_=seed()
    db._fetch_one('DELETE FROM finance_settings RETURNING id')
    db._fetch_one('INSERT INTO finance_settings(id,exchange_rate) VALUES(1,7.2) RETURNING id')
    import uuid
    with application.app.test_client() as client:
        response=client.post('/api/admin/orders',json={'requestId':str(uuid.uuid4()),'userId':1,
            'contactName':'Browser Quote','phone':'123456','country':'CN','address':'Fixture Street',
            'currency':'CNY','exchangeRate':7.2,'shippingFee':10,'items':[
                {'productId':1,'sizeCode':'M','quantity':2,'unitPrice':80,'priceSource':'manual'},
                {'productId':1,'sizeCode':'L','quantity':1,'unitPrice':90,'priceSource':'manual'}]},
            headers={'Authorization':'Bearer '+tokens['admin']})
        assert response.status_code==200,response.status_code
else:
    from flask import send_from_directory
    dist=root.parent/'shopify/frontend/dist'
    @application.app.get('/')
    @application.app.get('/<path:path>')
    def page(path=''):
        if path.startswith('api/'):return {'message':'Not found'},404
        return send_from_directory(dist,path if (dist/path).is_file() else 'index.html')
application.app.run(host='127.0.0.1',port=5409 if store else 5408,threaded=True,use_reloader=False)
