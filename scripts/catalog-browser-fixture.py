"""Shared catalog browser fixture. Never seeds the manually synchronized database."""
import os
import sys
from pathlib import Path
if os.environ.get('PGHOST')!='127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'admin-backend'))
import test_workbench as fixtures
from PIL import Image, ImageDraw
fixtures.seed()
db=fixtures.db
uploads=fixtures.application.media.uploads['admin'];uploads.mkdir(parents=True,exist_ok=True)
image=Image.new('RGB',(400,400),'#f1f2f3');draw=ImageDraw.Draw(image)
draw.polygon([(140,65),(260,65),(335,130),(290,170),(270,145),(270,330),(130,330),(130,145),(110,170),(65,130)],fill='#334155')
image.save(uploads/'fixture.jpg')
with db.get_connection() as conn:
    conn.execute("UPDATE presale_configs SET style_codes='[]',sort_mode='automatic',version=0")
    conn.execute("UPDATE products SET created_at='2020-01-01 00:00:00+00'")
for i in range(14):
    for color in ('Black','White'):
        code=f'CAT-{i:02}'
        db.create_product({'categoryKey':'denim' if i%2 else 'outerwear','productCode':code+'-'+color,'sku':code+'-'+color,
          'slug':(code+'-'+color).lower(),'colorGroup':code,'colorName':color,'title':'Catalog fixture style',
          'summary':{'zh':'100% Cotton','en':'100% Cotton'},'sizes':['28/S','Tall XL'],
          'sizePrices':[{'sizeCode':'28/S','price':10 if color=='Black' else 12,'stock':8 if color=='White' else 0},
                        {'sizeCode':'Tall XL','price':10 if color=='Black' else 12,'stock':3}],
          'image':'/uploads/fixture.jpg','gallery':['/uploads/fixture.jpg']})
    with db.get_connection() as conn:
        conn.execute("UPDATE products SET created_at=%s WHERE color_group=%s",(f'2025-01-{i+1:02} 00:00:00+00',code))
if __name__=='__main__':fixtures.application.app.run(host='127.0.0.1',port=5370,threaded=True,use_reloader=False)
