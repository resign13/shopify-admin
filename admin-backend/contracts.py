"""Purchase contracts: immutable snapshots and atomic pending inventory increments."""
import hashlib
import json
import uuid
from datetime import date
from io import BytesIO
from urllib.parse import urlsplit
from flask import g
from psycopg.types.json import Jsonb
import db


def migrate(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS purchase_contracts (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        request_id UUID UNIQUE NOT NULL, actor_id BIGINT NOT NULL,
        payload_hash TEXT NOT NULL, factory_name TEXT NOT NULL,
        delivery_date DATE NOT NULL, quantity BIGINT NOT NULL CHECK(quantity > 0),
        snapshot JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
        CREATE INDEX IF NOT EXISTS purchase_contracts_created ON purchase_contracts(created_at DESC,id DESC);
    """)


def text(value, label, limit, required=True):
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise ValueError(f'{label}请填写1至{limit}个字符' if required else f'{label}长度超出限制')
    return value.strip()


def image_url(value):
    value = text(value, '图片地址', 2048, False)
    if value:
        parsed = urlsplit(value)
        if not ((parsed.scheme in {'http', 'https'} and parsed.netloc) or (not parsed.scheme and not parsed.netloc and parsed.path.startswith('/uploads/'))):
            raise ValueError('图片地址格式错误')
    return value


def serialize(row, detail=False):
    result = {'id': row['id'], 'contractNo': f"HT-{row['id']:06d}", 'creatorId': row['actor_id'],
              'factoryName': row['factory_name'], 'deliveryDate': row['delivery_date'].isoformat(),
              'quantity': row['quantity'], 'createdAt': row['created_at'].isoformat()}
    result.update({k: row['snapshot'].get(k, default) for k,default in [('contractNo',result['contractNo']),('creatorName',''),('cancelled',False),('revision',1)]})
    if detail:
        result.update(row['snapshot'])
    return result


def detail(contract_id):
    row = db._fetch_one('SELECT * FROM purchase_contracts WHERE id=%s', (contract_id,))
    return serialize(row, True) if row else None


def listing(args):
    import workbench
    page, size = workbench.paging(args)
    keyword = '%' + str(args.get('keyword', '')).strip() + '%'
    where = "(factory_name ILIKE %s OR ('HT-' || lpad(id::text,6,'0')) ILIKE %s OR snapshot->>'items' ILIKE %s)"
    params = (keyword, keyword, keyword)
    total = db._fetch_one('SELECT count(*) AS total FROM purchase_contracts WHERE ' + where, params)['total']
    rows = db._fetch_all('SELECT * FROM purchase_contracts WHERE ' + where + ' ORDER BY id DESC LIMIT %s OFFSET %s', (*params, size, (page-1)*size))
    return {'items': [serialize(row) for row in rows], 'total': total, 'page': page, 'pageSize': size}


def create(payload, existing=None):
    from order_management import positive
    if not isinstance(payload, dict):
        raise ValueError('合同内容格式错误')
    try:
        request_id = str(uuid.UUID(str(payload.get('requestId', ''))))
    except ValueError:
        raise ValueError('缺少有效提交编号，请重新打开新建合同')
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('contract:' + request_id,))
    previous = db._fetch_one('SELECT * FROM purchase_contracts WHERE request_id=%s', (request_id,))
    if previous and existing is None:
        if previous['actor_id'] != g.current_user['id'] or previous['payload_hash'] != digest:
            raise ValueError('提交编号已使用，请重新检查合同列表')
        return {'item': serialize(previous, True), 'replayed': True}
    party_a = text(payload.get('partyA'), '甲方', 200)
    party_b = text(payload.get('partyB') or payload.get('factoryName'), '乙方', 200)
    contract_no = text(payload.get('contractNo'), '合同号', 100)
    attachments = payload.get('attachments') or []
    if not isinstance(attachments, list) or len(attachments) > 9: raise ValueError('备注附件最多上传9张图片')
    attachments = [image_url(v) for v in attachments]
    global_style = image_url(payload.get('styleImage', ''))
    global_chart = image_url(payload.get('sizeChartImage', ''))
    factory = party_b
    note = text(payload.get('note', ''), '合同备注', 5000, False)
    try:
        delivery = date.fromisoformat(payload.get('deliveryDate', ''))
    except (ValueError, TypeError):
        raise ValueError('请填写有效交货日期')
    items = payload.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('请选择1至100个商品')
    if not global_style: global_style = image_url(items[0].get('image', '') if isinstance(items[0], dict) else '')
    if not global_chart: global_chart = image_url(items[0].get('sizeChartImage', '') if isinstance(items[0], dict) else '')
    if not global_style or not global_chart: raise ValueError('请上传一张款式图和一张尺码表')
    ids = [positive(item.get('productId'), '商品编号') for item in items if isinstance(item, dict)]
    if len(ids) != len(items) or len(set(ids)) != len(ids):
        raise ValueError('商品数据无效或重复')
    lock_ids = sorted(set(ids + ([i['productId'] for i in existing['snapshot']['items']] if existing else [])))
    locked = db._fetch_all('SELECT id FROM products WHERE id=ANY(%s) AND is_active=TRUE ORDER BY id FOR UPDATE', (lock_ids,))
    if len(locked) != len(lock_ids):
        raise ValueError('商品不存在或已删除，请重新选择')
    snapshots, total = [], 0
    for item in sorted(items, key=lambda item: int(item['productId'])):
        product_id = int(item['productId'])
        product = db.get_product_by_id(product_id)
        style_image = global_style
        size_chart = global_chart
        if not style_image or not size_chart:
            raise ValueError('请补全每个商品的款式图和尺寸表')
        sizes = db._fetch_all('SELECT size_code,contract_pending FROM product_size_prices WHERE product_id=%s ORDER BY sort_order,id FOR UPDATE', (product_id,))
        amounts = item.get('quantities')
        mapping = item.get('sizeMapping')
        display = None
        if mapping is not None:
            if not isinstance(mapping, dict) or not isinstance(amounts, dict) or set(amounts) - set(STANDARD): raise ValueError('合同尺码须为S–XXL')
            display = {k: db._parse_non_negative_int(amounts.get(k, 0), '合同数量') for k in STANDARD}
            selected = [mapping.get(k) for k in STANDARD if mapping.get(k)]
            if len(selected) != len(set(selected)): raise ValueError('不同合同尺码不得对应同一库存尺码')
            amounts = {}
            for k, qty in display.items():
                if qty and not mapping.get(k): raise ValueError(f'{k} 请先选择对应的库存尺码')
                if mapping.get(k): amounts[mapping[k]] = qty
        if not isinstance(amounts, dict) or set(amounts) - {r['size_code'] for r in sizes}:
            raise ValueError('尺码已变化或不属于该商品，请重新选择商品')
        quantities = {size: db._parse_non_negative_int(qty, '合同数量') for size, qty in amounts.items()}
        if not quantities or sum(quantities.values()) <= 0:
            raise ValueError('每个商品至少填写一个尺码数量')
        snapshots.append({'productId': product_id, 'productCode': product.get('productCode') or product['sku'],
                          'sku': product['sku'], 'title': product['name'].get('zh') or product['name'].get('en'),
                          'colorName': text(item.get('colorName') or product.get('colorName', ''), '色号', 100),
                          'colorCode': text(item.get('colorCode') or product.get('colorName', ''), '色号', 100),
                          'image': style_image,
                          'sizeChartImage': size_chart,
                          'sizes': [s['size_code'] for s in sizes], 'quantities': quantities,
                          'quantity': sum(quantities.values()), 'sizeMapping': mapping, 'displayQuantities': display})
        total += sum(quantities.values())
    snapshot = {'creatorName': (existing['snapshot'].get('creatorName','') if existing else g.current_user.get('name') or g.current_user.get('email') or ''),
                'contractNo': contract_no, 'partyA': party_a, 'partyB': party_b, 'note': note,
                'attachments': attachments, 'styleImage': global_style, 'sizeChartImage': global_chart, 'items': snapshots,
                'revision': (existing['snapshot'].get('revision', 1) + 1 if existing else 1)}
    apply_delta(existing['snapshot']['items'] if existing else [], snapshots)
    if existing:
        row = db._fetch_one('UPDATE purchase_contracts SET factory_name=%s,delivery_date=%s,quantity=%s,snapshot=%s WHERE id=%s RETURNING *',
                           (factory,delivery,total,Jsonb(snapshot),existing['id']))
    else:
        row = db._fetch_one("""INSERT INTO purchase_contracts(request_id,actor_id,payload_hash,factory_name,delivery_date,quantity,snapshot)
            VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (request_id,g.current_user['id'],digest,factory,delivery,total,Jsonb(snapshot)))
    return {'item': serialize(row, True), 'replayed': False}


STANDARD = ['S','M','L','XL','XXL']

def apply_delta(before, after):
    delta = {}
    for items, sign in [(before,-1),(after,1)]:
        for item in items:
            for size, qty in item['quantities'].items():
                key = (int(item['productId']),size)
                delta[key] = delta.get(key,0) + sign * int(qty)
    ids = sorted({key[0] for key in delta})
    db._fetch_all('SELECT id FROM products WHERE id=ANY(%s) ORDER BY id FOR UPDATE',(ids,))
    for (pid,size), change in sorted(delta.items()):
        if not change: continue
        row = db._fetch_one('SELECT contract_pending,pending_inbound FROM product_size_prices WHERE product_id=%s AND size_code=%s FOR UPDATE',(pid,size))
        if not row: raise ValueError(f'商品 {pid} 的库存尺码 {size} 不存在')
        value = row['contract_pending'] + change
        if value < row['pending_inbound'] or value < 0:
            raise ValueError(f'商品 {pid} 尺码 {size} 的合同未送已减少或包含待入库，当前数量不足以回退；请先核对入库记录')
        if value > 2147483647: raise ValueError('合同未送数量超出允许范围')
        db._fetch_one('UPDATE product_size_prices SET contract_pending=%s WHERE product_id=%s AND size_code=%s RETURNING id',(value,pid,size))
        db._fetch_one('UPDATE products SET updated_at=clock_timestamp() WHERE id=%s RETURNING id',(pid,))


def update(contract_id, payload):
    from workbench import Conflict
    row = db._fetch_one('SELECT * FROM purchase_contracts WHERE id=%s FOR UPDATE',(contract_id,))
    if not row: raise ValueError('合同不存在')
    if row['snapshot'].get('cancelled'): raise ValueError('已取消合同不可修改')
    if payload.get('revision') != row['snapshot'].get('revision',1): raise Conflict('合同已更新，请重新打开详情核对')
    return create(payload, existing=row)['item']


def cancel(contract_id, payload=None):
    from workbench import Conflict
    row = db._fetch_one('SELECT * FROM purchase_contracts WHERE id=%s FOR UPDATE',(contract_id,))
    if not row: raise ValueError('合同不存在')
    snap=row['snapshot']
    if snap.get('cancelled'): return serialize(row,True)
    if (payload or {}).get('revision') != snap.get('revision',1): raise Conflict('合同已更新，请重新打开详情核对')
    apply_delta(snap['items'],[])
    snap['cancelled']=True
    snap['revision']=snap.get('revision',1)+1
    updated=db._fetch_one('UPDATE purchase_contracts SET snapshot=%s WHERE id=%s RETURNING *',(Jsonb(snap),contract_id))
    return serialize(updated,True)


def export(contract, fetch_image, make_image):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    book = Workbook(); ws = book.active; ws.title = '购买合同'
    sizes = STANDARD + list(dict.fromkeys(size for item in contract['items'] if not item.get('displayQuantities') for size in item['sizes'] if size not in STANDARD))
    # Keep wide/unusual size sets readable in successive blocks, without merging real sizes.
    row = 1
    def line(value, height=30):
        nonlocal row
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        cell = ws.cell(row, 1, str(value)); cell.data_type = 's'
        cell.alignment = Alignment(wrap_text=True, vertical='center'); ws.row_dimensions[row].height = height
        row += 1
    line('购买合同 · ' + contract['contractNo']); ws['A1'].font = Font(size=18, bold=True)
    line('乙方：' + contract.get('partyB', contract['factoryName']) + '    甲方：' + contract.get('partyA', ''))
    line('交期：' + contract['deliveryDate'] + '    合同号：' + contract.get('contractNo', '') + '    合同总数：' + str(contract['quantity']))
    ws.column_dimensions['A'].width = 24; ws.column_dimensions['B'].width = 20
    for col in range(3, 10): ws.column_dimensions[get_column_letter(col)].width = 12
    thin = Side(style='thin', color='D1D5DB')
    for offset in range(0, len(sizes), 6):
        block = sizes[offset:offset+6]
        for col, value in enumerate(['款号 / 颜色SKU', '色号', *block, '本组小计'], 1):
            cell = ws.cell(row, col, value); cell.data_type = 's'; cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='EAF0F8')
        row += 1
        for item in contract['items']:
            values = [item['productCode'], item.get('colorCode', item['colorName']), *[(item.get('displayQuantities') or item['quantities']).get(s, 0) for s in block], sum((item.get('displayQuantities') or item['quantities']).get(s, 0) for s in block)]
            for col, value in enumerate(values, 1):
                cell = ws.cell(row, col, value)
                if isinstance(value, str): cell.data_type = 's'
                cell.alignment = Alignment(wrap_text=True, vertical='center', horizontal='left' if col < 3 else 'center')
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            ws.row_dimensions[row].height = 40; row += 1
        row += 1
    line('合同合计：' + str(contract['quantity']) + ' 件')
    cache = {}
    for key, label, url in [('styleImage', '款式图', contract.get('styleImage', '')), ('sizeChartImage', '尺寸表', contract.get('sizeChartImage', ''))]:
            if not url:
                line(label + '：未填写'); continue
            if url not in cache:
                if len(cache) >= 4: cache.pop(next(iter(cache)))
                cache[url] = fetch_image(url)
            picture = make_image(cache[url], width=600, height=480, pixels=1600) if cache[url] else None
            if not picture:
                raise ValueError('合同图片暂时读取失败，请稍后重试导出')
            line(label)
            ws.add_image(picture, f'A{row}')
            ws.row_dimensions[row].height = picture.height * .75 + 12; row += 2
    if contract['note']:
        line('备注：' + contract['note'], min(409, max(48, len(contract['note']) / 60 * 18)))
    if contract.get('attachments'):
        line('备注附件')
        from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
        from openpyxl.drawing.xdr import XDRPositiveSize2D
        from openpyxl.utils.units import pixels_to_EMU
        left, tallest = 0, 0
        for url in contract['attachments']:
            if url not in cache: cache[url] = fetch_image(url)
            picture = make_image(cache[url], width=260, height=180, pixels=1200) if cache[url] else None
            if not picture: raise ValueError('备注附件图片读取失败，请稍后重试')
            picture.anchor = OneCellAnchor(
                _from=AnchorMarker(col=0, row=row-1, colOff=pixels_to_EMU(left)),
                ext=XDRPositiveSize2D(pixels_to_EMU(picture.width), pixels_to_EMU(picture.height)))
            ws.add_image(picture)
            left += picture.width + 16
            tallest = max(tallest, picture.height)
        ws.row_dimensions[row].height = tallest * .75 + 12
        row += 2
    ws.sheet_view.showGridLines = False; ws.freeze_panes = None
    ws.page_setup.orientation = 'landscape'; ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    stream = BytesIO(); book.save(stream); stream.seek(0); return stream
