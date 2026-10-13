"""Private, versioned order work-in-progress. Never writes orders or inventory."""
import copy
import hashlib
import json
import uuid

from flask import abort, g
from psycopg.types.json import Jsonb

import db
import order_reorder
import workbench


def migrate(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS admin_order_drafts (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        creator_id BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
        draft_key UUID NOT NULL, submit_request_id UUID NOT NULL UNIQUE,
        document JSONB NOT NULL DEFAULT '{}'::jsonb,
        revision BIGINT NOT NULL DEFAULT 1,
        state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','converted','deleted')),
        order_id BIGINT REFERENCES orders(id) ON DELETE SET NULL,
        last_save_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(creator_id,draft_key));
        CREATE INDEX IF NOT EXISTS idx_admin_order_drafts_owner
          ON admin_order_drafts(creator_id,state,updated_at DESC,id DESC);
    ''')


def get_row(draft_id, *, write=False):
    # Administrators may inspect all drafts, but only the creator can mutate.
    restriction = '' if not write and g.current_user['role'] == 'admin' else ' AND creator_id=%s'
    params = (draft_id,) if not restriction else (draft_id, g.current_user['id'])
    row = db._fetch_one('SELECT * FROM admin_order_drafts WHERE id=%s' + restriction + (' FOR UPDATE' if write else ''), params)
    if not row:
        abort(404, description='草稿不存在或无权访问')
    return row


def active(row):
    if row['state'] != 'active':
        raise workbench.Conflict('该草稿已转为正式订单或已删除，请刷新草稿列表。')


def version(row, payload):
    if str(payload.get('version') or '') != str(row['revision']):
        raise workbench.Conflict('草稿已在其他窗口更新，当前输入已保留，请重新打开草稿后核对。')


def clean_document(payload):
    from order_management import amount, positive, order_images
    from customer_templates import TEXT_FIELDS, pdf_url
    if not isinstance(payload, dict):
        raise ValueError('草稿格式无效')
    result = {}
    for key in TEXT_FIELDS:
        value = payload.get(key, '')
        if not isinstance(value, str) or len(value) > (5000 if key == 'note' else 500):
            raise ValueError('草稿文字格式或长度无效')
        result[key] = value
    for key in ['userId','ownerAdminId','sourceOrderId']:
        result[key] = positive(payload[key], key) if payload.get(key) not in (None, '') else None
    if g.current_user['role'] == 'sales':
        result['ownerAdminId'] = g.current_user['id']
    origin = order_reorder.source(result['sourceOrderId']) if result['sourceOrderId'] else {}
    result['sourceOrderNo'] = origin.get('order_no', '')
    result['inheritedAttachmentUrls'] = order_reorder.inherited_attachments(payload, origin)
    result['labelImageUrls'] = order_images({'labelImageUrls': payload.get('labelImageUrls', [])}, None)
    result['labelPdfUrl'] = pdf_url(payload.get('labelPdfUrl', ''))
    order_reorder.validate_attachment_uploads(result['inheritedAttachmentUrls'], result['labelImageUrls'], result['labelPdfUrl'])
    result['shippingFee'] = db._num(amount(payload.get('shippingFee') or 0, '运费'))
    result['ownerConfirmed'] = payload.get('ownerConfirmed', True) is True
    for field in ['items','pendingItems']:
        rows = payload.get(field, [])
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError('草稿最多保存 500 个商品尺码行')
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('草稿商品格式无效')
            item = {'productId': positive(row['productId'], '商品编号') if row.get('productId') else None}
            for key in ['sizeCode','sku','productName','reason']:
                value = row.get(key, '')
                if not isinstance(value, str) or len(value) > 500:
                    raise ValueError('草稿商品描述格式无效')
                item[key] = value
            item['quantity'] = db._parse_non_negative_int(row.get('quantity') or 0, '商品数量')
            item['unitPrice'] = db._num(amount(row.get('unitPrice') or 0, '商品单价'))
            previous = row.get('oldUnitPrices', [item['unitPrice']])
            if not isinstance(previous, list) or len(previous) > 500:
                raise ValueError('历史价格格式无效')
            item['oldUnitPrices'] = [db._num(amount(v, '历史单价')) for v in previous]
            cleaned.append(item)
        result[field] = cleaned
    if len(result['items']) + len(result['pendingItems']) > 500:
        raise ValueError('草稿最多保存 500 个商品尺码行')
    if len(json.dumps(result, ensure_ascii=False).encode()) > 512 * 1024:
        raise ValueError('草稿内容超过大小限制')
    return result


def metadata(row):
    data = row['document']
    return {'id': row['id'], 'version': str(row['revision']), 'state': row['state'], 'orderId': row['order_id'],
            'submitRequestId': str(row['submit_request_id']),
            'sourceOrderId': data.get('sourceOrderId'), 'sourceOrderNo': data.get('sourceOrderNo', ''),
            'contactName': data.get('contactName') or '未填写客户', 'country': data.get('country', ''),
            'itemCount': sum(r.get('quantity', 0) for r in data.get('items', [])),
            'creatorId': row['creator_id'], 'canEdit': row['creator_id'] == g.current_user['id'],
            'updatedAt': db._iso(row['updated_at'])}


def detail(draft_id):
    row = get_row(draft_id)
    active(row)
    result = metadata(row)
    data = copy.deepcopy(row['document'])
    data['items'], data['pendingItems'], products = order_reorder.refresh_items(data['items'] + data['pendingItems'])
    had_customer = bool(data['userId'])
    customer = db._fetch_one('SELECT id,name,email,company_name,status FROM store_users WHERE id=%s', (data['userId'],)) if had_customer else None
    if not customer or customer['status'] != 'active':
        data['userId'] = None
    if data['ownerAdminId']:
        owner = db._fetch_one("SELECT id FROM admin_users WHERE id=%s AND status='active' AND role='sales'", (data['ownerAdminId'],))
        if not owner:
            data['ownerAdminId'] = None
            data['ownerConfirmed'] = False
    result.update(draft=data, products=products, submitRequestId=str(row['submit_request_id']),
                  customerUnavailable=had_customer and (not customer or customer['status'] != 'active'),
                  customer={'id':customer['id'],'name':customer['name'],'companyName':customer['company_name'],'email':customer['email']} if customer else None)
    return result


def listing(args):
    page, size = int(args.get('page', 1)), 10
    if not 1 <= page <= 2147483647:
        raise ValueError('分页参数无效')
    all_users = g.current_user['role'] == 'admin' and args.get('scope') == 'all'
    where = "d.state='active'"
    params = []
    if not all_users:
        where += ' AND d.creator_id=%s'; params.append(g.current_user['id'])
    where += " AND concat_ws(' ',d.document->>'contactName',d.document->>'sourceOrderNo',u.name,u.company_name) ILIKE %s"
    params.append('%' + str(args.get('keyword', '')).strip() + '%')
    joins = " FROM admin_order_drafts d LEFT JOIN store_users u ON u.id=(d.document->>'userId')::bigint"
    total = db._fetch_one('SELECT COUNT(*) AS n' + joins + ' WHERE ' + where, params)['n']
    rows = db._fetch_all('SELECT d.*,a.name AS creator_name,u.name AS customer_name,u.company_name' + joins +
                        ' LEFT JOIN admin_users a ON a.id=d.creator_id WHERE ' + where +
                        ' ORDER BY d.updated_at DESC,d.id DESC LIMIT %s OFFSET %s', (*params,size,(page-1)*size))
    return {'items': [{**metadata(r),'creatorName':r['creator_name'] or '账号已删除',
                       'customerName':r['company_name'] or r['customer_name'] or ''} for r in rows],
            'total': total, 'page': page, 'pageSize': size}


def audit(row, action):
    actor = {key: g.current_user.get(key) for key in ('id','name','role')}
    db._fetch_one('''INSERT INTO admin_audit_logs(actor,module,action,entity_table,object_id,batch_id,after_data)
        VALUES(%s,'orders',%s,'admin_order_drafts',%s,current_setting('gingtto.batch'),%s) RETURNING id''',
        (Jsonb(actor), action, str(row['id']), Jsonb({'revision':row['revision'],'state':row['state']})))


def save(payload, draft_id=None):
    if not isinstance(payload, dict):
        raise ValueError('草稿格式无效')
    row = get_row(draft_id, write=True) if draft_id else None
    if row: active(row)
    document = clean_document(payload.get('draft'))
    digest = hashlib.sha256(json.dumps(document,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if row:
        # An identical retry after a successful save is harmless, not another revision.
        if str(payload.get('version')) == str(row['revision'] - 1) and digest == row['last_save_hash']:
            return metadata(row)
        version(row, payload)
        if document['sourceOrderId'] != row['document'].get('sourceOrderId'):
            raise ValueError('草稿的来源订单不可更改')
        row = db._fetch_one('''UPDATE admin_order_drafts SET document=%s,last_save_hash=%s,
            revision=revision+1,updated_at=clock_timestamp() WHERE id=%s RETURNING *''', (Jsonb(document),digest,draft_id))
    else:
        try: key = str(uuid.UUID(str(payload.get('draftKey', ''))))
        except ValueError: raise ValueError('缺少有效草稿编号，请重新打开表单')
        try: submit_id = str(uuid.UUID(str(payload.get('submitRequestId') or uuid.uuid4())))
        except ValueError: raise ValueError('草稿提交编号无效')
        # Keep the form's original submission identity when its first save follows
        # a network timeout. A committed order must not become a second draft.
        db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (submit_id,))
        if db._fetch_one('SELECT request_id FROM admin_order_requests WHERE request_id=%s', (submit_id,)):
            raise workbench.Conflict('该表单已创建正式订单，请先检查订单列表，不再另存为草稿。')
        db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'draft:{g.current_user["id"]}:{key}',))
        previous = db._fetch_one('SELECT * FROM admin_order_drafts WHERE creator_id=%s AND draft_key=%s FOR UPDATE', (g.current_user['id'],key))
        if previous:
            active(previous)
            if previous['last_save_hash'] != digest:
                raise workbench.Conflict('该草稿已保存，请从“我的草稿”重新打开，避免覆盖其他窗口。')
            return metadata(previous)
        if db._fetch_one('SELECT id FROM admin_order_drafts WHERE submit_request_id=%s', (submit_id,)):
            raise workbench.Conflict('该提交编号已用于其他草稿，请从“我的草稿”继续编辑。')
        row = db._fetch_one('''INSERT INTO admin_order_drafts(creator_id,draft_key,submit_request_id,document,last_save_hash)
            VALUES(%s,%s,%s,%s,%s) RETURNING *''', (g.current_user['id'],key,submit_id,Jsonb(document),digest))
    audit(row, 'DRAFT_SAVE')
    return {**metadata(row), 'submitRequestId':str(row['submit_request_id'])}


def delete(draft_id, payload):
    row = get_row(draft_id, write=True)
    active(row); version(row, payload)
    row = db._fetch_one("UPDATE admin_order_drafts SET state='deleted',document='{}',revision=revision+1,updated_at=clock_timestamp() WHERE id=%s RETURNING *",(draft_id,))
    audit(row, 'DRAFT_DELETE')
    return {'deleted': True}


def for_submit(payload):
    from order_management import positive
    row = get_row(positive(payload['draftId'], '草稿编号'), write=True)
    active(row)
    version(row, {'version':payload.get('draftVersion')})
    if str(payload.get('requestId')) != str(row['submit_request_id']):
        raise ValueError('草稿提交编号不一致，请重新打开草稿')
    supplied = positive(payload['sourceOrderId'], '来源订单编号') if payload.get('sourceOrderId') is not None else None
    if supplied != row['document'].get('sourceOrderId'):
        raise ValueError('草稿来源订单不一致')
    return row


def converted(row, order_id):
    db._fetch_one("UPDATE admin_order_drafts SET state='converted',order_id=%s,document='{}',revision=revision+1,updated_at=clock_timestamp() WHERE id=%s RETURNING id",(order_id,row['id']))
