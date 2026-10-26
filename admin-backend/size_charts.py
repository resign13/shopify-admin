"""Independent, versioned style measurements. Never writes product/stock data."""
from copy import deepcopy
from datetime import timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
import json
import re
import uuid

from flask import g, jsonify, request
from psycopg.types.json import Jsonb
import db
import module_permissions
import style_catalog
import workbench

TZ = timezone(timedelta(hours=8))
MAX_STYLES, MAX_SIZES, MAX_DIMENSIONS = 100, 128, 64
PRESET = [
    ('waist-relaxed', '腰围松量', 'Waist (Relaxed)', 'cm'),
    ('waist-stretched', '腰围拉量', 'Waist (Stretched)', 'cm'),
    ('hip', '臀围', 'Hip', 'cm'), ('thigh', '腿围', 'Thigh', 'cm'),
    ('knee', '膝围', 'Knee', 'cm'), ('leg-opening', '脚口', 'Leg Opening', 'cm'),
    ('front-rise', '前浪', 'Front Rise', 'cm'), ('back-rise', '后浪', 'Back Rise', 'cm'),
    ('inseam', '内长', 'Inseam', 'cm'),
]


def migrate(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS product_size_charts (
      style_code TEXT PRIMARY KEY, document JSONB NOT NULL,
      revision BIGINT NOT NULL DEFAULT 1, updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE TABLE IF NOT EXISTS product_size_chart_audit (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, style_code TEXT NOT NULL,
      before_data JSONB NOT NULL, after_data JSONB NOT NULL, actor JSONB NOT NULL,
      request_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE INDEX IF NOT EXISTS product_size_chart_audit_style ON product_size_chart_audit(style_code,id DESC);
    CREATE TABLE IF NOT EXISTS product_size_chart_receipts (
      request_id UUID PRIMARY KEY, actor_id BIGINT NOT NULL, payload JSONB NOT NULL,
      result JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());''')


def text(value, label, limit=255, required=False):
    if not isinstance(value, str) or '\x00' in value or len(value) > limit:
        raise ValueError(label + '格式无效')
    value = value.strip()
    if required and not value: raise ValueError('请填写' + label)
    return value


def number(value):
    if value is None or value == '': return None
    try:
        if isinstance(value, bool): raise ValueError()
        n = Decimal(str(value).strip())
        if not n.is_finite() or n < 0 or n > Decimal('9999999999.99') or n != n.quantize(Decimal('.01')):
            raise ValueError()
        return format(n, '.2f')
    except (ValueError, InvalidOperation):
        raise ValueError('测量值须为非负数，最多两位小数；空白表示清空')


def convert_value(value, source, target):
    if source not in {'cm', 'in'} or target not in {'cm', 'in'}: raise ValueError('单位须为 cm 或 in')
    value = number(value)
    if value is None or source == target: return value
    n = Decimal(value) * Decimal('2.54') if source == 'in' else Decimal(value) / Decimal('2.54')
    return number(n.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def unified_document(document, target=None):
    """Old per-row units are converted on read, without writing or changing revision."""
    doc = deepcopy(document)
    target = target or doc.get('unit', 'cm')
    for d in doc['dimensions']:
        doc['values'][d['id']] = {s: convert_value(v, d['unit'], target)
                                  for s, v in doc['values'].get(d['id'], {}).items()}
        d['unit'] = target
    doc['unit'] = target
    return doc


def catalog(codes=None, lock=False):
    where = 'p.is_active=TRUE'
    params = []
    if codes is not None:
        where += f' AND {style_catalog.style_sql()}=ANY(%s)'; params.append(codes)
    # SHARE locks conflict with the catalog's existing UPDATE/DELETE transactions.
    rows = db._fetch_all(f'''SELECT p.id,p.sku,p.main_image_url,pc.category_key,
      {style_catalog.style_sql()} AS style_code FROM products p
      JOIN product_categories pc ON pc.id=p.category_id WHERE {where}
      ORDER BY p.id''' + (' FOR SHARE OF p' if lock else ''), tuple(params))
    ids = [r['id'] for r in rows]
    names = db._fetch_all('SELECT product_id,lang_code,name FROM product_translations WHERE product_id=ANY(%s) ORDER BY product_id,lang_code', (ids,)) if ids else []
    sizes = db._fetch_all('SELECT product_id,size_code FROM product_sizes WHERE product_id=ANY(%s) ORDER BY product_id,sort_order,id' + (' FOR SHARE' if lock else ''), (ids,)) if ids else []
    images = db._fetch_all('SELECT product_id,image_url FROM product_images WHERE product_id=ANY(%s) ORDER BY product_id,sort_order,id', (ids,)) if ids else []
    by_id, result = {}, {}
    for r in rows:
        c = result.setdefault(r['style_code'], {'styleCode': r['style_code'], 'title': '', 'titleEn': '', 'sizes': [], 'images': [], 'categories': [], 'members': []})
        by_id[r['id']] = c
        c['members'].append({'id': r['id'], 'sizes': []})
        if r['main_image_url'] and r['main_image_url'] not in c['images']: c['images'].append(r['main_image_url'])
        if r['category_key'] not in c['categories']: c['categories'].append(r['category_key'])
    for r in names:
        c = by_id[r['product_id']]
        key = 'titleEn' if r['lang_code'] == 'en' else 'title' if r['lang_code'] == 'zh' else None
        if key and not c[key]: c[key] = r['name'] or ''
    for r in sizes:
        c = by_id[r['product_id']]
        next(m for m in c['members'] if m['id'] == r['product_id'])['sizes'].append(r['size_code'])
        if r['size_code'] not in c['sizes']: c['sizes'].append(r['size_code'])
    for r in images:
        c = by_id[r['product_id']]
        if r['image_url'] and r['image_url'] not in c['images']: c['images'].append(r['image_url'])
    return result


def defaults(c):
    title = c['title'] or c['titleEn'] or c['styleCode']
    return {'title': title, 'titleEn': c['titleEn'] or (title if not re.search(r'[\u3400-\u9fff]', title) else ''),
            'material': '', 'materialEn': '', 'image': next(iter(c['images']), ''), 'unit': 'cm',
            'dimensions': [{'id': i, 'name': cn, 'nameEn': en, 'unit': u, 'showEn': True} for i, cn, en, u in PRESET],
            'values': {i: {s: None for s in c['sizes']} for i, _, _, _ in PRESET}}


def detail(code, catalogs=None):
    c = (catalogs if catalogs is not None else catalog([code])).get(code)
    if not c: raise workbench.Conflict('款号已停用或移除，请刷新列表')
    row = db._fetch_one('SELECT * FROM product_size_charts WHERE style_code=%s', (code,))
    doc = unified_document(row['document']) if row else defaults(c)
    values = {d['id']: {s: doc['values'].get(d['id'], {}).get(s) for s in c['sizes']} for d in doc['dimensions']}
    count = sum(v is not None for vals in values.values() for v in vals.values())
    total = len(c['sizes']) * len(doc['dimensions'])
    return {**doc, 'image': next(iter(c['images']), ''), 'values': values, 'styleCode': code, 'sizes': c['sizes'], 'catalogVersion': c['members'],
            'images': c['images'], 'categories': c['categories'], 'version': str(row['revision'] if row else 0),
            'updatedDate': row['updated_at'].astimezone(TZ).strftime('%Y-%m-%d') if row else '',
            'status': 'complete' if total and count == total else 'partial' if count else 'empty'}


def listing(args):
    page, size = workbench.paging(args)
    cats = catalog()
    # Catalog query is batched; saved chart records are fetched once for list metadata.
    records = {r['style_code']: r for r in db._fetch_all('SELECT * FROM product_size_charts')}
    keyword = str(args.get('keyword', '')).strip().casefold(); category = args.get('category', ''); status = args.get('status', '')
    result = []
    for code, c in cats.items():
        row = records.get(code); doc = row['document'] if row else defaults(c)
        count = sum(doc['values'].get(d['id'], {}).get(s) is not None for d in doc['dimensions'] for s in c['sizes'])
        total = len(c['sizes']) * len(doc['dimensions'])
        state = 'complete' if total and count == total else 'partial' if count else 'empty'
        if keyword and keyword not in (code + ' ' + doc['title'] + ' ' + doc['titleEn']).casefold(): continue
        if category and category not in c['categories']: continue
        if status and state != status: continue
        result.append({'styleCode': code, 'title': doc['title'], 'image': next(iter(c['images']), ''), 'status': state,
                       'updatedDate': row['updated_at'].astimezone(TZ).strftime('%Y-%m-%d') if row else ''})
    result.sort(key=lambda r: r['styleCode'])
    labels = {r['key']: r['label'] for r in db.list_category_labels('zh')}
    return {'items': result[(page-1)*size:page*size], 'total': len(result),
            'categories': [{'key': v, 'label': labels.get(v, v)} for v in sorted({v for c in cats.values() for v in c['categories']})]}


def normalize(data, current):
    if not isinstance(data, dict): raise ValueError('尺码表格式无效')
    if data.get('catalogVersion') != current['catalogVersion'] or data.get('sizes') != current['sizes']:
        raise workbench.Conflict('商品真实尺码已变化，请刷新后核对；未保存内容保留')
    if str(data.get('version')) != current['version']: raise workbench.Conflict('尺码表已被修改，请刷新后核对')
    if not 1 <= len(current['sizes']) <= MAX_SIZES: raise ValueError('商品需配置真实尺码，每款最多 128 个尺码')
    doc = {k: text(data.get(k, ''), label, required=k == 'title') for k, label in [('title', '商品标题'), ('titleEn', '英文标题'), ('material', '材质'), ('materialEn', '英文材质')]}
    # Representative image follows the catalog's first image, never client selection.
    doc['image'] = current['image']
    doc['unit'] = data.get('unit')
    if doc['unit'] not in {'cm', 'in'}: raise ValueError('请为整款选择 cm 或 in')
    dims = data.get('dimensions')
    if not isinstance(dims, list) or not 1 <= len(dims) <= MAX_DIMENSIONS: raise ValueError('每款需 1–64 个测量维度')
    doc['dimensions'] = []; seen = set()
    for d in dims:
        if not isinstance(d, dict): raise ValueError('测量维度格式无效')
        key = text(d.get('id'), '维度标识', 80, True)
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', key) or key in seen: raise ValueError('维度标识重复或无效')
        seen.add(key)
        if d.get('unit') not in {'cm', 'in'} or not isinstance(d.get('showEn'), bool): raise ValueError('维度单位或英文显示配置无效')
        if d['unit'] != doc['unit']: raise ValueError('同一款的所有测量维度必须使用统一单位')
        doc['dimensions'].append({'id': key, 'name': text(d.get('name'), '中文维度', 80, True),
                                  'nameEn': text(d.get('nameEn'), '英文维度', 80), 'unit': d['unit'], 'showEn': d['showEn']})
    if not any(d['showEn'] for d in doc['dimensions']): raise ValueError('至少选择一个英文展示维度')
    values = data.get('values')
    if not isinstance(values, dict) or set(values) != seen: raise ValueError('测量值与维度不一致')
    doc['values'] = {}
    for key in seen:
        if not isinstance(values[key], dict) or set(values[key]) != set(current['sizes']): raise ValueError('测量值与商品真实尺码不一致')
        doc['values'][key] = {s: number(values[key][s]) for s in current['sizes']}
    return doc


def english(doc):
    for key, label in [('titleEn', '英文标题'), ('materialEn', '英文材质')]:
        if (key == 'titleEn' or doc['material'] or doc[key]) and (not doc[key] or re.search(r'[\u3400-\u9fff]', doc[key])):
            raise ValueError('请填写' + label + '，不要包含中文')
    visible = [d for d in doc['dimensions'] if d['showEn']]
    if not visible: raise ValueError('至少选择一个英文展示维度')
    if any(not d['nameEn'] or re.search(r'[\u3400-\u9fff]', d['nameEn']) for d in visible): raise ValueError('请补全展示维度的英文名称，不要包含中文')
    return visible


def save_batch(payload):
    if not isinstance(payload, dict): raise ValueError('请求格式无效')
    try: rid = str(uuid.UUID(str(payload.get('requestId', ''))))
    except ValueError: raise ValueError('缺少有效提交编号')
    changes = payload.get('changes')
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_STYLES: raise ValueError('每次处理 1–100 款')
    codes = [text(c.get('styleCode'), '款号', 200, True) for c in changes if isinstance(c, dict)]
    if len(codes) != len(changes) or len(set(codes)) != len(codes): raise ValueError('款号重复或无效')
    db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('size-chart-request:' + rid,))
    old_receipt = db._fetch_one('SELECT * FROM product_size_chart_receipts WHERE request_id=%s', (rid,))
    if old_receipt:
        if old_receipt['actor_id'] != g.current_user['id'] or old_receipt['payload'] != payload: raise workbench.Conflict('提交编号已用于其他修改')
        return {**old_receipt['result'], 'replayed': True}
    for code in sorted(codes): db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('size-chart:' + code,))
    cats = catalog(codes, lock=True)
    prepared = []
    for item in changes:
        c = detail(item['styleCode'], cats)
        prepared.append((item['styleCode'], normalize(item, c)))
    updated = []
    actor = {k: g.current_user.get(k) for k in ('id', 'name', 'role')}
    for code, doc in prepared:
        previous = db._fetch_one('SELECT document FROM product_size_charts WHERE style_code=%s', (code,))
        before = previous['document'] if previous else defaults(cats[code])
        # Keep removed size/measurement values in storage, not in customer output.
        # Retained sizes of active dimensions must follow unit changes too.
        merged = unified_document(before, doc['unit']).get('values', {})
        for key, values in doc['values'].items(): merged.setdefault(key, {}).update(values)
        doc['values'] = merged
        if doc == before: continue
        db._fetch_one('''INSERT INTO product_size_charts(style_code,document) VALUES(%s,%s)
          ON CONFLICT(style_code) DO UPDATE SET document=EXCLUDED.document,revision=product_size_charts.revision+1,
          updated_at=clock_timestamp() RETURNING revision''', (code, Jsonb(doc)))
        db._fetch_one('''INSERT INTO product_size_chart_audit(style_code,before_data,after_data,actor,request_id)
          VALUES(%s,%s,%s,%s,%s) RETURNING id''', (code, Jsonb(before), Jsonb(doc), Jsonb(actor), rid))
        updated.append(code)
    result = {'updated': updated, 'items': [detail(code, cats) for code in codes]}
    db._fetch_one('INSERT INTO product_size_chart_receipts(request_id,actor_id,payload,result) VALUES(%s,%s,%s,%s) RETURNING request_id', (rid, g.current_user['id'], Jsonb(payload), Jsonb(result)))
    return result


def register(app, require_auth):
    import size_chart_excel
    def guard(write=False):
        def decorate(fn):
            @wraps(fn)
            @require_auth
            def wrapped():
                if g.current_user.get('role') not in module_permissions.STAFF_ROLES or 'size-charts' not in module_permissions.effective(g.current_user):
                    return jsonify({'message': 'Forbidden'}), 403
                try:
                    response = (workbench.atomic_admin_call if write else workbench.snapshot_admin_call)(fn, (), {})
                    return response
                except workbench.Conflict as e: return jsonify({'message': str(e), 'code': 'size_chart_conflict'}), 409
                except ValueError as e: return jsonify({'message': str(e)}), 400
            return wrapped
        return decorate
    for path, method, handler, write in [
        ('', 'GET', lambda: jsonify(listing(request.args)), False),
        ('/detail', 'GET', lambda: jsonify(detail(text(request.args.get('styleCode'), '款号', 200, True))), False),
        ('/save', 'POST', lambda: jsonify(save_batch(request.get_json(silent=True))), True),
        ('/export', 'POST', lambda: size_chart_excel.export(request.get_json(silent=True)), False),
        ('/import/preview', 'POST', lambda: jsonify(size_chart_excel.preview_upload()), False),
        ('/import/confirm', 'POST', lambda: jsonify(size_chart_excel.confirm(request.get_json(silent=True))), True),
    ]:
        app.add_url_rule('/api/admin/size-charts' + path, 'size_charts_' + (path or 'list').replace('/', '_'), guard(write)(handler), methods=[method])
