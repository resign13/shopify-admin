"""Private cost timelines and read-only order-line accounting. All money is Decimal."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from functools import wraps
from io import BytesIO
import hashlib
import json
import uuid
import unicodedata

from flask import g, jsonify, request, send_file
from psycopg.types.json import Jsonb
import db
import module_permissions
import style_catalog
import workbench

TZ = timezone(timedelta(hours=8))
STATES = ['pending_payment', 'allocated', 'paid', 'shipped', 'completed']
CENT = Decimal('.01')


def migrate(cur):
    # Logical product identity survives hard deletion and size-row reconstruction.
    cur.execute('''CREATE TABLE IF NOT EXISTS finance_cost_versions (
      product_id BIGINT NOT NULL, size_code TEXT NOT NULL, revision BIGINT NOT NULL DEFAULT 0,
      PRIMARY KEY(product_id,size_code));
    CREATE TABLE IF NOT EXISTS finance_cost_history (
      product_id BIGINT NOT NULL, size_code TEXT NOT NULL, effective_date DATE NOT NULL,
      cost_cny NUMERIC(12,2) CHECK(cost_cny>=0), sku TEXT NOT NULL, style_code TEXT NOT NULL,
      actor JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(product_id,size_code,effective_date));
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='finance_cost_history'::regclass
                AND attname='cost_cny' AND attnotnull AND NOT attisdropped) THEN
        ALTER TABLE finance_cost_history ALTER COLUMN cost_cny DROP NOT NULL;
      END IF;
    END $$;
    CREATE TABLE IF NOT EXISTS finance_cost_audit (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, product_id BIGINT NOT NULL,
      size_code TEXT NOT NULL, effective_date DATE NOT NULL, before_data JSONB NOT NULL,
      after_data JSONB NOT NULL, actor JSONB NOT NULL, request_id UUID NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE TABLE IF NOT EXISTS finance_cost_receipts (
      request_id UUID PRIMARY KEY, actor_id BIGINT NOT NULL, fingerprint TEXT NOT NULL,
      result JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE INDEX IF NOT EXISTS finance_cost_audit_variant ON finance_cost_audit(product_id,size_code,id DESC);
    CREATE TABLE IF NOT EXISTS finance_settings (
      id SMALLINT PRIMARY KEY CHECK(id=1),
      exchange_rate NUMERIC(16,6) NOT NULL CHECK(exchange_rate>0),
      revision BIGINT NOT NULL DEFAULT 1,
      updated_by BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    ''')


def number(value, *, rate=False):
    if isinstance(value, bool) or value is None or str(value).strip() == '':
        raise ValueError('请输入汇率' if rate else '请输入成本；未设置不能当作零成本保存')
    try:
        d = Decimal(str(value))
        quantum = Decimal('.000001') if rate else CENT
        if not d.is_finite() or d < 0 or d > Decimal('9999999999.99') or d != d.quantize(quantum) or (rate and d == 0):
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise ValueError('汇率必须为正数，最多六位小数' if rate else '成本须为非负金额，最多两位小数')
    return d


def day(value=None):
    try:
        result = date.fromisoformat(str(value)) if value else datetime.now(TZ).date()
        if not 1900 <= result.year <= 9998: raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValueError('日期格式无效')


def integer(value, minimum=1):
    if isinstance(value, bool) or not str(value).isdigit() or not minimum <= int(value) <= 2147483647:
        raise ValueError('编号或分页参数无效')
    return int(value)


def terms(value):
    if isinstance(value, str): value = value.replace('，', ',').split(',')
    if not isinstance(value, list) or len(value) > 200 or any(not isinstance(s, str) or len(s) > 200 for s in value):
        raise ValueError('款号筛选无效，最多 200 项')
    return list(dict.fromkeys(s.strip() for s in value if s.strip()))


def money(value):
    return None if value is None else format(value.quantize(CENT, rounding=ROUND_HALF_UP), '.2f')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def preferences():
    row=db._fetch_one('SELECT exchange_rate,revision FROM finance_settings WHERE id=1')
    return {'exchangeRate':format(row['exchange_rate'],'.6f') if row else None,'version':str(row['revision']) if row else '0'}


def save_preferences(payload):
    if not isinstance(payload,dict):raise ValueError('汇率保存格式无效')
    rate=number(payload.get('exchangeRate'),rate=True)
    expected=str(integer(payload.get('version'),0))
    uid=g.current_user['id']
    db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('finance-shared-settings',))
    old=db._fetch_one('SELECT exchange_rate,revision FROM finance_settings WHERE id=1 FOR UPDATE')
    if old and old['exchange_rate']==rate:return preferences()
    if expected!=str(old['revision'] if old else 0):raise workbench.Conflict('公共汇率已更新，请核对最新保存值后重试')
    db._fetch_one('''INSERT INTO finance_settings(id,exchange_rate,updated_by) VALUES(1,%s,%s)
      ON CONFLICT(id) DO UPDATE SET exchange_rate=EXCLUDED.exchange_rate,
        revision=finance_settings.revision+1,updated_by=EXCLUDED.updated_by,updated_at=clock_timestamp() RETURNING revision''',(rate,uid))
    return preferences()


def options():
    return {
        'customers': db._fetch_all('SELECT id,name,company_name AS company FROM store_users ORDER BY name,id'),
        'salespeople': db._fetch_all("SELECT id,name,status FROM admin_users WHERE role='sales' ORDER BY name,id"),
        'styles': [r['code'] for r in db._fetch_all(f'SELECT DISTINCT {style_catalog.style_sql()} AS code FROM products p ORDER BY code')],
        'categories': db._fetch_all('SELECT category_key AS key FROM product_categories ORDER BY sort_order,id'),
    }


def costs(args):
    effective = day(args.get('effectiveDate'))
    page = integer(args.get('page', 1)); size = integer(args.get('pageSize', 12))
    if size not in (12, 24, 48): raise ValueError('每页请选择 12、24 或 48 款')
    rows = db._fetch_all(f'''SELECT p.id,p.sku,p.color_name,p.is_active,p.main_image_url,
        {style_catalog.style_sql()} AS style_code,c.category_key,
        COALESCE(t.name,p.sku) AS name,s.size_code,s.sort_order,h.cost_cny,h.effective_date,
        COALESCE(v.revision,0) AS revision
      FROM products p JOIN product_categories c ON c.id=p.category_id
      LEFT JOIN product_translations t ON t.product_id=p.id AND t.lang_code='zh'
      JOIN product_size_prices s ON s.product_id=p.id
      LEFT JOIN finance_cost_versions v ON v.product_id=p.id AND v.size_code=s.size_code
      LEFT JOIN LATERAL (SELECT cost_cny,effective_date FROM finance_cost_history h
        WHERE h.product_id=p.id AND h.size_code=s.size_code AND h.effective_date<=%s
        ORDER BY effective_date DESC LIMIT 1) h ON true ORDER BY p.id,s.sort_order,s.size_code''', (effective,))
    groups = {}
    for r in rows:
        group = groups.setdefault(r['style_code'], {'styleCode':r['style_code'],'name':r['name'],'variants':{},'sizes':[]})
        variant = group['variants'].setdefault(r['id'], {'id':r['id'],'sku':r['sku'],'color':r['color_name'],
            'image':r['main_image_url'],'active':r['is_active'],'category':r['category_key'],'sizes':[]})
        variant['sizes'].append({'sizeCode':r['size_code'],'costCny':money(r['cost_cny']),
            'effectiveDate':str(r['effective_date']) if r['effective_date'] else None,'version':str(r['revision'])})
        if r['size_code'] not in group['sizes']: group['sizes'].append(r['size_code'])
    codes = {s.casefold() for s in terms(args.get('styleCodes', ''))}
    keyword = str(args.get('keyword', '')).strip().casefold()
    result = []
    for group in groups.values():
        variants = list(group['variants'].values()); group['variants'] = variants
        if codes and group['styleCode'].casefold() not in codes: continue
        if args.get('category') and not any(v['category']==args['category'] for v in variants): continue
        if keyword and keyword not in ' '.join([group['styleCode'], *[v['sku']+' '+v['color'] for v in variants]]).casefold(): continue
        if str(args.get('missingOnly','')).lower() in ('1','true') and not any(s['costCny'] is None for v in variants for s in v['sizes']): continue
        result.append(group)
    result.sort(key=lambda r:r['styleCode'])
    return {'items':result[(page-1)*size:page*size], 'total':len(result),'page':page,'pageSize':size,'effectiveDate':str(effective)}


def normalized(payload):
    if not isinstance(payload, dict): raise ValueError('请求格式无效')
    effective = day(payload.get('effectiveDate'))
    changes = payload.get('changes')
    if not isinstance(changes, list) or not 1 <= len(changes) <= 2000: raise ValueError('每次保存 1–2000 个尺码成本')
    result = []; seen = set()
    for row in changes:
        if not isinstance(row, dict): raise ValueError('成本格式无效')
        pid = integer(row.get('productId')); size = row.get('sizeCode')
        if not isinstance(size, str) or not size.strip() or len(size)>200: raise ValueError('尺码无效')
        if (pid,size) in seen: raise ValueError('同一商品尺码重复')
        seen.add((pid,size))
        if 'costCny' not in row:raise ValueError('缺少成本字段；填写金额或显式传入 null 清空')
        cost=None if row['costCny'] is None else money(number(row['costCny']))
        result.append({'productId':pid,'sizeCode':size,'costCny':cost,
            'version':str(integer(row.get('version'),0))})
    return effective, sorted(result,key=lambda r:(r['productId'],r['sizeCode']))


def preview(payload, lock=False):
    effective, changes = normalized(payload)
    ids = sorted({r['productId'] for r in changes})
    products = {r['id']:r for r in db._fetch_all(f'SELECT p.id,p.sku,{style_catalog.style_sql()} AS style_code FROM products p WHERE p.id=ANY(%s) ORDER BY p.id'+(' FOR SHARE' if lock else ''),(ids,))}
    sizes = {(r['product_id'],r['size_code']) for r in db._fetch_all('SELECT product_id,size_code FROM product_size_prices WHERE product_id=ANY(%s) ORDER BY product_id,size_code'+(' FOR SHARE' if lock else ''),(ids,))}
    if lock:
        for r in changes:
            key=(r['productId'],r['sizeCode'])
            db._fetch_one('INSERT INTO finance_cost_versions(product_id,size_code) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING revision',key)
        db._fetch_all('SELECT * FROM finance_cost_versions WHERE product_id=ANY(%s) ORDER BY product_id,size_code FOR UPDATE',(ids,))
    versions={(r['product_id'],r['size_code']):str(r['revision']) for r in db._fetch_all('SELECT * FROM finance_cost_versions WHERE product_id=ANY(%s)',(ids,))}
    history=defaultdict(list)
    for r in db._fetch_all('SELECT * FROM finance_cost_history WHERE product_id=ANY(%s) ORDER BY effective_date',(ids,)):
        history[(r['product_id'],r['size_code'])].append(r)
    # One batch lookup for impact, no per-order or per-line queries.
    orders=db._fetch_all('''SELECT DISTINCT o.id,i.product_id,i.size_code,(o.created_at AT TIME ZONE 'Asia/Shanghai')::date AS day
      FROM orders o JOIN order_items i ON i.order_id=o.id WHERE i.product_id=ANY(%s) AND o.status=ANY(%s)''',(ids,STATES))
    output=[]; affected=set()
    for r in changes:
        key=(r['productId'],r['sizeCode'])
        if key not in sizes: raise workbench.Conflict('商品或尺码已移除，请刷新并核对成本草稿')
        if r['version'] != versions.get(key,'0'): raise workbench.Conflict('成本已被其他人更新，请刷新后核对；当前输入已保留')
        records=history[key]; earlier=[v for v in records if v['effective_date']<=effective]
        later=[v['effective_date'] for v in records if v['effective_date']>effective]
        end=min(later) if later else None
        matching={v['id'] for v in orders if (v['product_id'],v['size_code'])==key and v['day']>=effective and (end is None or v['day']<end)}
        affected.update(matching)
        output.append({**r,'sku':products[key[0]]['sku'],'styleCode':products[key[0]]['style_code'],
            'oldCostCny':money(earlier[-1]['cost_cny']) if earlier else None,
            'effectiveDate':str(effective),'untilExclusive':str(end) if end else None,'affectedOrders':len(matching)})
    result={'changes':output,'affectedOrders':len(affected),'effectiveDate':str(effective)}
    return {**result,'previewHash':digest(result)}


def save_costs(payload):
    try: rid=str(uuid.UUID(str(payload.get('requestId',''))))
    except (ValueError, AttributeError): raise ValueError('缺少有效提交编号')
    effective, changes=normalized(payload)
    fingerprint=digest({'effectiveDate':effective,'changes':changes,'previewHash':payload.get('previewHash')})
    db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('finance:'+rid,))
    previous=db._fetch_one('SELECT * FROM finance_cost_receipts WHERE request_id=%s',(rid,))
    if previous:
        if previous['actor_id']!=g.current_user['id'] or previous['fingerprint']!=fingerprint: raise workbench.Conflict('提交编号已用于其他修改')
        return {**previous['result'],'replayed':True}
    result=preview(payload,lock=True)
    if result['previewHash']!=payload.get('previewHash'): raise workbench.Conflict('预览已变化，请重新预览确认后保存')
    actor={key:g.current_user.get(key) for key in ('id','name','role')}
    for r in result['changes']:
        key=(r['productId'],r['sizeCode'],effective)
        old=db._fetch_one('SELECT cost_cny FROM finance_cost_history WHERE product_id=%s AND size_code=%s AND effective_date=%s',key)
        db._fetch_one('''INSERT INTO finance_cost_history(product_id,size_code,effective_date,cost_cny,sku,style_code,actor)
          VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(product_id,size_code,effective_date)
          DO UPDATE SET cost_cny=EXCLUDED.cost_cny,sku=EXCLUDED.sku,style_code=EXCLUDED.style_code,actor=EXCLUDED.actor,updated_at=clock_timestamp() RETURNING product_id''',
          (*key,None if r['costCny'] is None else Decimal(r['costCny']),r['sku'],r['styleCode'],Jsonb(actor)))
        db._fetch_one('UPDATE finance_cost_versions SET revision=revision+1 WHERE product_id=%s AND size_code=%s RETURNING revision',key[:2])
        db._fetch_one('''INSERT INTO finance_cost_audit(product_id,size_code,effective_date,before_data,after_data,actor,request_id)
          VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id''',(*key,Jsonb({'costCny':money(old['cost_cny']) if old else None}),Jsonb(r),Jsonb(actor),rid))
    response={'saved':len(changes),'replayed':False}
    db._fetch_one('INSERT INTO finance_cost_receipts(request_id,actor_id,fingerprint,result) VALUES(%s,%s,%s,%s) RETURNING request_id',(rid,g.current_user['id'],fingerprint,Jsonb(response)))
    return response


def history(args):
    if 'styleCode' in args:
        return style_history(args)
    pid=integer(args.get('productId')); size=str(args.get('sizeCode',''))
    page=integer(args.get('page',1))
    timeline=db._fetch_all('SELECT effective_date,cost_cny,actor,updated_at FROM finance_cost_history WHERE product_id=%s AND size_code=%s ORDER BY effective_date DESC',(pid,size))
    audits=db._fetch_all('SELECT * FROM finance_cost_audit WHERE product_id=%s AND size_code=%s ORDER BY id DESC LIMIT 10 OFFSET %s',(pid,size,(page-1)*10))
    return {'timeline':[{'effectiveDate':str(r['effective_date']),'costCny':money(r['cost_cny']),'actor':r['actor'],'updatedAt':db._iso(r['updated_at'])} for r in timeline],
        'items':[{'id':r['id'],'effectiveDate':str(r['effective_date']),'before':r['before_data'],'after':r['after_data'],'actor':r['actor'],'createdAt':db._iso(r['created_at'])} for r in audits],
        'total':db._fetch_one('SELECT count(*) AS n FROM finance_cost_audit WHERE product_id=%s AND size_code=%s',(pid,size))['n'],'page':page}


def style_history(args):
    code=str(args.get('styleCode','')).strip()
    if not code or len(code)>200:raise ValueError('请选择有效款号')
    page=integer(args.get('page',1))
    if integer(args.get('pageSize',20))!=20:raise ValueError('成本历史每页显示 20 条')
    # Live products follow the same canonical identity as the cost matrix. Deleted
    # products follow their saved audit identity, never a guessed title/SKU prefix.
    scope=f'''((p.id IS NOT NULL AND {style_catalog.style_sql()}=%s)
      OR (p.id IS NULL AND a.after_data->>'styleCode'=%s))'''
    current=db._fetch_all(f'''SELECT p.id,p.sku,p.color_name FROM products p
      WHERE {style_catalog.style_sql()}=%s ORDER BY p.id''',(code,))
    variants={r['id']:{'productId':r['id'],'sku':r['sku'],'color':r['color_name'],'deleted':False} for r in current}
    identities=db._fetch_all(f'''SELECT a.product_id,a.size_code,MAX(a.id) AS last_id,
        (array_agg(a.after_data->>'sku' ORDER BY a.id DESC))[1] AS sku
      FROM finance_cost_audit a LEFT JOIN products p ON p.id=a.product_id WHERE {scope}
      GROUP BY a.product_id,a.size_code ORDER BY last_id DESC''',(code,code))
    for row in identities:
        variants.setdefault(row['product_id'],{'productId':row['product_id'],'sku':row['sku'] or str(row['product_id']),
                                             'color':'','deleted':True})
    current_sizes=db._fetch_all('''SELECT size_code FROM product_size_prices
      WHERE product_id=ANY(%s) ORDER BY product_id,sort_order,size_code''',([r['id'] for r in current],))
    sizes=list(dict.fromkeys([r['size_code'] for r in current_sizes]+[r['size_code'] for r in identities]))
    conditions=[scope];params=[code,code]
    if args.get('productId'):
        pid=integer(args['productId'])
        if pid not in variants:raise ValueError('所选颜色不属于该款号')
        conditions.append('a.product_id=%s');params.append(pid)
    if args.get('sizeCode'):
        size=str(args['sizeCode'])
        if len(size)>200:raise ValueError('尺码无效')
        conditions.append('a.size_code=%s');params.append(size)
    source='FROM finance_cost_audit a LEFT JOIN products p ON p.id=a.product_id WHERE '+' AND '.join(conditions)
    rows=db._fetch_all('SELECT a.* '+source+' ORDER BY a.id DESC LIMIT 20 OFFSET %s',(*params,(page-1)*20))
    items=[]
    for row in rows:
        after=row['after_data'];before=row['before_data']
        # New effective dates have no previous row at that date. Their saved
        # preview still records the prior effective cost in after.oldCostCny.
        old=after['oldCostCny'] if 'oldCostCny' in after else before.get('costCny')
        items.append({'id':row['id'],'productId':row['product_id'],'sku':after.get('sku') or variants[row['product_id']]['sku'],
            'sizeCode':row['size_code'],'oldCostCny':old,'costCny':after.get('costCny'),
            'effectiveDate':str(row['effective_date']),'actor':row['actor'],'createdAt':db._iso(row['created_at'])})
    return {'styleCode':code,'items':items,'page':page,'pageSize':20,
        'total':db._fetch_one('SELECT count(*) AS n '+source,tuple(params))['n'],
        'options':{'variants':list(variants.values()),'sizes':sizes}}


def report(payload, paginate=True):
    with localcontext() as context:
        context.prec=60  # Quantity, stored amount, FX and cross-order sums stay exact.
        return _report(payload,paginate)


def _report(payload, paginate=True):
    if not isinstance(payload,dict): raise ValueError('筛选条件无效')
    end=day(payload.get('dateTo')); start=day(payload.get('dateFrom') or end-timedelta(days=29))
    if start>end: raise ValueError('开始日期不能晚于结束日期')
    rate=number(payload.get('exchangeRate'),rate=True)
    states=payload.get('statuses') or STATES
    if not isinstance(states,list) or any(s not in STATES for s in states): raise ValueError('仅支持有效订单状态')
    codes=terms(payload.get('styleCodes',[]))
    people=payload.get('salespersonIds',[])
    if not isinstance(people,list) or len(people)>200: raise ValueError('业务员筛选无效')
    owners=[integer(i) for i in people if i!='unassigned']
    params=[start,end+timedelta(days=1),states]
    where=["o.created_at >= (%s::date::timestamp AT TIME ZONE 'Asia/Shanghai')", "o.created_at < (%s::date::timestamp AT TIME ZONE 'Asia/Shanghai')",'o.status=ANY(%s)']
    customer=str(payload.get('customerName','')).strip()
    if customer: where.append('o.contact_name ILIKE %s');params.append('%'+customer+'%')
    if payload.get('customerId'): where.append('o.store_user_id=%s');params.append(integer(payload['customerId']))
    if people:
        where.append('(o.owner_admin_id=ANY(%s)'+(' OR o.owner_admin_id IS NULL' if 'unassigned' in people else '')+')');params.append(owners)
    style=f"CASE WHEN p.id IS NOT NULL THEN {style_catalog.style_sql()} ELSE COALESCE(ch.style_code,'未归类') END"
    if codes: where.append(f'LOWER({style})=ANY(%s)');params.append([v.lower() for v in codes])
    rows=db._fetch_all(f'''SELECT o.id AS order_id,o.order_no,o.created_at,o.status,o.contact_name,
        o.store_user_id,su.name AS account_name,su.company_name,COALESCE(a.name,'未分配') AS salesperson,
        o.owner_admin_id,i.id AS item_id,i.product_id,i.sku,i.size_code,i.quantity,i.unit_price,
        {style} AS style_code,h.cost_cny,h.effective_date
      FROM orders o JOIN order_items i ON i.order_id=o.id
      LEFT JOIN store_users su ON su.id=o.store_user_id LEFT JOIN admin_users a ON a.id=o.owner_admin_id
      LEFT JOIN products p ON p.id=i.product_id
      LEFT JOIN LATERAL (SELECT style_code FROM finance_cost_history c WHERE c.product_id=i.product_id AND c.size_code=i.size_code ORDER BY effective_date DESC LIMIT 1) ch ON true
      LEFT JOIN LATERAL (SELECT cost_cny,effective_date FROM finance_cost_history c
        WHERE c.product_id=i.product_id AND c.size_code=i.size_code AND COALESCE(i.size_code,'')<>''
          AND c.effective_date <= (o.created_at AT TIME ZONE 'Asia/Shanghai')::date ORDER BY effective_date DESC LIMIT 1) h ON true
      WHERE {' AND '.join(where)} ORDER BY o.created_at DESC,o.id DESC,i.id''',params)
    groups={}; lines=[]
    for r in rows:
        usd=r['unit_price']*r['quantity']; cny=(usd*rate).quantize(CENT,rounding=ROUND_HALF_UP)
        cost=r['cost_cny']*r['quantity'] if r['cost_cny'] is not None else None
        line={'orderId':r['order_id'],'orderNo':r['order_no'],'createdAt':db._iso(r['created_at']),
            'customerName':r['contact_name'],'accountName':r['company_name'] or r['account_name'] or '',
            'salesperson':r['salesperson'],'styleCode':r['style_code'],'sku':r['sku'],'sizeCode':r['size_code'] or '',
            'productId':r['product_id'],'quantity':r['quantity'],'salesUsd':money(usd),'salesCny':money(cny),
            'unitCostCny':money(r['cost_cny']),'costCny':money(cost),'profitCny':money(cny-cost) if cost is not None else None,
            'costEffectiveDate':str(r['effective_date']) if r['effective_date'] else None}
        lines.append(line)
        key=(r['style_code'],r['product_id'],r['sku'],r['size_code'])
        groups.setdefault(key,[]).append(line)
    def aggregate(items):
        missing=sum(v['quantity'] for v in items if v['costCny'] is None)
        total=lambda name:sum((Decimal(v[name]) for v in items if v[name] is not None),Decimal(0))
        return {'orderCount':len({v['orderId'] for v in items}),'quantity':sum(v['quantity'] for v in items),
            'salesUsd':money(total('salesUsd')),'salesCny':money(total('salesCny')),'knownCostCny':money(total('costCny')),
            'totalCostCny':None if missing else money(total('costCny')),
            'profitCny':None if missing else money(total('profitCny')),'knownProfitCny':money(total('profitCny')),'missingQuantity':missing}
    items=[]
    for key, values in groups.items():
        costs=[Decimal(v['unitCostCny']) for v in values if v['unitCostCny'] is not None]
        items.append({'styleCode':key[0],'productId':key[1],'sku':key[2],'sizeCode':key[3] or '',**aggregate(values),
            'minCostCny':money(min(costs)) if costs else None,'maxCostCny':money(max(costs)) if costs else None,'lines':values})
    items.sort(key=lambda r:(r['styleCode'],r['sku'],r['sizeCode']))
    page=integer(payload.get('page',1)); page_size=integer(payload.get('pageSize',25))
    if page_size not in (25,50,100): raise ValueError('分页无效')
    filters={'dateFrom':str(start),'dateTo':str(end),'customerName':customer,'customerId':payload.get('customerId'),
        'salespersonIds':people,'styleCodes':codes,'statuses':states,'exchangeRate':str(rate)}
    return {'items':items[(page-1)*page_size:page*page_size] if paginate else items,
        'total':len(items),'page':page,'pageSize':page_size,'summary':aggregate(lines),
        'filters':filters,'generatedAt':datetime.now(TZ).isoformat(),**({'lines':lines} if not paginate else {})}


def export(payload):
    # Existing Flask XLSX stack, not a spreadsheet authoring dependency for clients.
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    data=report(payload,paginate=False); book=Workbook(); summary=book.active;summary.title='核算汇总'
    def append(sheet, values):
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value,str): cell.data_type='s'  # Untrusted text never becomes a formula.
            if isinstance(cell.value,Decimal): cell.number_format='#,##0.00;[Red]-#,##0.00'
            cell.alignment=Alignment(vertical='center',wrap_text=True)
    amount=lambda v:Decimal(v) if v is not None else '待补全'
    append(summary,['GINGTTO 商品成本核算']); append(summary,['生成时间',data['generatedAt']])
    append(summary,['口径','人民币成本；美元销售额按本次汇率换算；不含运费、税费及其他费用；未付款订单不代表实际回款。'])
    labels={'dateFrom':'下单日期起（北京时间）','dateTo':'下单日期止（北京时间）','customerName':'客户名称关键词',
        'customerId':'商城账号','salespersonIds':'业务员','styleCodes':'款号','statuses':'订单状态','exchangeRate':'本次汇率（1 USD = CNY）',
        'orderCount':'涉及订单数','quantity':'商品件数','salesUsd':'商品销售额 USD','salesCny':'折合销售额 CNY',
        'knownCostCny':'已知成本 CNY','totalCostCny':'完整成本 CNY','profitCny':'商品毛利 CNY',
        'knownProfitCny':'已设置成本部分商品毛利 CNY','missingQuantity':'缺失成本件数'}
    lookup=options(); customers={c['id']:c['name'] for c in lookup['customers']}; people={c['id']:c['name'] for c in lookup['salespeople']}
    states={'pending_payment':'待付款','allocated':'已配货','paid':'已付款','shipped':'已发货','completed':'已完成'}
    for k,v in data['filters'].items():
        if k=='customerId': v=customers.get(v,str(v)) if v else '全部'
        if k=='salespersonIds': v=[('未分配' if i=='unassigned' else people.get(i,people.get(int(i),str(i)))) for i in v]
        if k=='statuses': v=[states[s] for s in v]
        if isinstance(v,list): v='、'.join(map(str,v)) or '全部'
        append(summary,[labels[k],str(v or '全部')])
    for k,v in data['summary'].items(): append(summary,[labels[k],amount(v) if k.endswith(('Cny','Usd')) else v])
    headers=['款号','颜色 SKU','真实尺码','订单数','件数','销售额 USD','折合销售额 CNY','成本下限 CNY','成本上限 CNY','已知成本 CNY','完整成本 CNY','商品毛利 CNY','缺失成本件数']
    append(summary,headers); header_row=summary.max_row
    for r in data['items']:
        append(summary,[r['styleCode'],r['sku'],r['sizeCode'],r['orderCount'],r['quantity'],*[amount(r[k]) for k in ('salesUsd','salesCny','minCostCny','maxCostCny','knownCostCny','totalCostCny','profitCny')],r['missingQuantity']])
    detail=book.create_sheet('订单明细');missing=book.create_sheet('成本缺失')
    columns=[('orderNo','订单号'),('createdAt','下单时间（北京时间）'),('customerName','客户'),('accountName','商城账号'),('salesperson','业务员'),('styleCode','款号'),('sku','SKU'),('sizeCode','尺码'),('quantity','数量'),('salesUsd','销售额 USD'),('salesCny','折合销售额 CNY'),('unitCostCny','单件成本 CNY'),('costEffectiveDate','成本生效日期'),('costCny','成本 CNY'),('profitCny','商品毛利 CNY')]
    for sheet in (detail,missing): append(sheet,[label for _,label in columns])
    for row in data['lines']:
        vals=[amount(row[k]) if k.endswith(('Cny','Usd')) else datetime.fromisoformat(row[k]).astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S') if k=='createdAt' else row[k] for k,_ in columns]
        append(detail,vals)
        if row['costCny'] is None: append(missing,vals)
    if missing.max_row==1: append(missing,['无缺失成本'])
    for sheet,head in ((summary,header_row),(detail,1),(missing,1)):
        sheet.freeze_panes=f'A{head+1}';sheet.auto_filter.ref=f'A{head}:{get_column_letter(sheet.max_column)}{sheet.max_row}'
        sheet.sheet_view.showGridLines=False; sheet.sheet_properties.pageSetUpPr.fitToPage=True
        sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=sheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0;sheet.print_title_rows=f'{head}:{head}'
        for cell in sheet[head]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='243850')
        for i in range(1,sheet.max_column+1): sheet.column_dimensions[get_column_letter(i)].width=36 if i==1 else 22 if i<=5 else 18
        for cells in sheet:
            # Excel does not automatically grow wrapped rows generated by openpyxl.
            def wrapped_lines(cell):
                width=sheet.column_dimensions[cell.column_letter].width-3
                return sum(1+sum(2 if unicodedata.east_asian_width(ch) in ('W','F') else 1 for ch in line)//width for line in str(cell.value or '').split('\n'))
            sheet.row_dimensions[cells[0].row].height=max(30,min(409,16*max(wrapped_lines(c) for c in cells)))
    out=BytesIO();book.save(out);out.seek(0)
    return send_file(out,as_attachment=True,download_name='finance-cost-report.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def register(app, require_auth):
    def guard(write=False):
        def decorate(fn):
            @wraps(fn)
            @require_auth
            def wrapped(*args,**kwargs):
                if g.current_user.get('role') not in {'admin','finance'} or 'finance' not in module_permissions.effective(g.current_user):
                    return jsonify({'message':'Forbidden'}),403
                try:
                    response=(workbench.atomic_admin_call if write else workbench.snapshot_admin_call)(fn,args,kwargs)
                    if hasattr(response,'headers'):response.headers['Cache-Control']='no-store'
                    return response
                except workbench.Conflict as exc:return jsonify({'message':str(exc),'code':'finance_conflict'}),409
                except ValueError as exc:return jsonify({'message':str(exc)}),400
            return wrapped
        return decorate
    routes=[('preferences','GET',lambda:jsonify(preferences()),False),
        ('preferences','PUT',lambda:jsonify(save_preferences(request.get_json(silent=True))),True),
        ('options','GET',lambda:jsonify(options()),False),('costs','GET',lambda:jsonify(costs(request.args)),False),
        ('costs/history','GET',lambda:jsonify(history(request.args)),False),
        ('costs/preview','POST',lambda:jsonify(preview(request.get_json(silent=True))),False),
        ('costs/save','POST',lambda:jsonify(save_costs(request.get_json(silent=True))),True),
        ('reports/query','POST',lambda:jsonify(report(request.get_json(silent=True))),False),
        ('reports/export','POST',lambda:export(request.get_json(silent=True)),False)]
    for path,method,handler,write in routes:
        app.add_url_rule('/api/admin/finance/'+path,'finance_'+path.replace('/','_')+'_'+method,guard(write)(handler),methods=[method])
