"""Creator-scoped customer presets; administrators can manage all presets."""
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
from flask import g, abort
import db
import workbench
from order_management import positive, order_images

TEXT_FIELDS = ('contactName', 'phone', 'country', 'contactValue', 'address',
               'apartment', 'city', 'state', 'zip', 'note')


def migrate(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS order_customer_templates (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name VARCHAR(120) NOT NULL CHECK(length(btrim(name)) > 0),
        store_user_id BIGINT REFERENCES store_users(id) ON DELETE SET NULL,
        created_by_admin_id BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
        customer_info JSONB NOT NULL DEFAULT '{}'::jsonb,
        revision BIGINT NOT NULL DEFAULT 1 CHECK(revision > 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
        CREATE INDEX IF NOT EXISTS idx_order_customer_templates_customer
          ON order_customer_templates(store_user_id);
        CREATE INDEX IF NOT EXISTS idx_order_customer_templates_creator
          ON order_customer_templates(created_by_admin_id,updated_at DESC,id DESC);
    ''')


def pdf_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('PDF 附件地址无效')
    value = value.strip()
    if not value:
        return ''
    parsed = urlsplit(value)
    if not (((parsed.scheme in {'http', 'https'} and parsed.netloc) or
             (not parsed.scheme and not parsed.netloc and parsed.path.startswith('/uploads/')))
            and parsed.path.lower().endswith('.pdf')):
        raise ValueError('附件请上传 PDF 文件')
    return value


def profile(payload):
    if not isinstance(payload, dict):
        raise ValueError('客户模板资料格式无效')
    result = {}
    for key in TEXT_FIELDS:
        value = payload.get(key, '')
        if not isinstance(value, str) or len(value) > (5000 if key == 'note' else 500):
            raise ValueError(f'{key}格式或长度无效')
        result[key] = value.strip()
    result['labelImageUrls'] = order_images({'labelImageUrls': payload.get('labelImageUrls', [])}, None)
    result['labelPdfUrl'] = pdf_url(payload.get('labelPdfUrl', ''))
    return result


BASE_QUERY = '''SELECT t.*, u.name AS customer_name, u.email AS customer_email,
    u.company_name, u.status AS customer_status, a.name AS creator_name
    FROM order_customer_templates t
    LEFT JOIN store_users u ON u.id=t.store_user_id
    LEFT JOIN admin_users a ON a.id=t.created_by_admin_id'''


def serialize(row, detail=False):
    customer = {'id': row['store_user_id'], 'name': row['customer_name'] or '',
                'email': row['customer_email'] or '', 'companyName': row['company_name'] or ''}
    result = {'id': row['id'], 'name': row['name'], 'version': str(row['revision']),
              'userId': row['store_user_id'], 'customer': customer,
              'customerActive': row['customer_status'] == 'active',
              'contactName': row['customer_info'].get('contactName', ''),
              'country': row['customer_info'].get('country', ''),
              'creatorId': row['created_by_admin_id'], 'creatorName': row['creator_name'] or '',
              'updatedAt': row['updated_at'].isoformat()}
    if detail:
        result['profile'] = {**row['customer_info'], 'userId': row['store_user_id']}
    return result


def scope():
    user = g.current_user
    if user.get('role') == 'admin':
        return 'TRUE', ()
    return 't.created_by_admin_id=%s', (user['id'],)


def detail(template_id):
    clause, params = scope()
    row = db._fetch_one(BASE_QUERY + ' WHERE t.id=%s AND ' + clause, (template_id, *params))
    return serialize(row, True) if row else None


def listing(args):
    page, size = workbench.paging(args)
    keyword = '%' + str(args.get('keyword', '')).strip() + '%'
    where = " WHERE concat_ws(' ',t.name,u.name,u.company_name,u.email,t.customer_info->>'contactName') ILIKE %s"
    clause, scope_params = scope()
    where += ' AND ' + clause
    params = (keyword, *scope_params)
    total = db._fetch_one('SELECT COUNT(*) AS total FROM order_customer_templates t LEFT JOIN store_users u ON u.id=t.store_user_id' + where, params)['total']
    rows = db._fetch_all(BASE_QUERY + where + ' ORDER BY t.updated_at DESC,t.id DESC LIMIT %s OFFSET %s',
                         (*params, size, (page - 1) * size))
    return {'items': [serialize(row) for row in rows], 'total': total, 'page': page, 'pageSize': size}


def locked(template_id, payload):
    if not isinstance(payload, dict):
        raise ValueError('客户模板格式无效')
    clause, params = scope()
    row = db._fetch_one('SELECT t.* FROM order_customer_templates t WHERE t.id=%s AND ' + clause + ' FOR UPDATE', (template_id, *params))
    if not row:
        abort(404, description='客户模板不存在')
    if not payload.get('version'):
        raise ValueError('缺少客户模板版本，请重新打开模板')
    if str(payload['version']) != str(row['revision']):
        raise workbench.Conflict('客户模板已被其他人员更新，当前草稿已保留，请重新加载模板后核对。')
    return row


def save(payload, template_id=None):
    if not isinstance(payload, dict):
        raise ValueError('客户模板格式无效')
    name = payload.get('name', '')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ValueError('模板名称请填写 1–120 个字符')
    if template_id is not None:
        locked(template_id, payload)
    data = profile(payload.get('profile'))
    user_id = positive(payload['profile'].get('userId'), '客户编号')
    user = db._fetch_one('SELECT id,status FROM store_users WHERE id=%s FOR SHARE', (user_id,))
    if not user or user['status'] != 'active':
        raise ValueError('请选择有效商城客户')
    if template_id is None:
        row = db._fetch_one('''INSERT INTO order_customer_templates(name,store_user_id,created_by_admin_id,customer_info)
                              VALUES(%s,%s,%s,%s) RETURNING id''',
                            (name.strip(), user_id, g.current_user['id'], Jsonb(data)))
        template_id = row['id']
    else:
        db._fetch_one('''UPDATE order_customer_templates SET name=%s,store_user_id=%s,customer_info=%s,
                        revision=revision+1,updated_at=clock_timestamp() WHERE id=%s RETURNING id''',
                      (name.strip(), user_id, Jsonb(data), template_id))
    return detail(template_id)


def delete(template_id, payload):
    locked(template_id, payload)
    db._fetch_one('DELETE FROM order_customer_templates WHERE id=%s RETURNING id', (template_id,))
