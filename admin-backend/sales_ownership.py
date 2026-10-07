"""Persistent salesperson attribution; account links never rewrite assigned history."""
def migrate(cur):
    cur.execute('SELECT pg_advisory_xact_lock(7192038)')
    cur.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'admin'")
    cur.execute('ALTER TABLE store_users ADD COLUMN IF NOT EXISTS linked_admin_user_id BIGINT REFERENCES admin_users(id)')
    cur.execute('ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_by_admin_id BIGINT REFERENCES admin_users(id)')
    cur.execute('ALTER TABLE orders ADD COLUMN IF NOT EXISTS owner_admin_id BIGINT REFERENCES admin_users(id)')
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_source VARCHAR(20) NOT NULL DEFAULT 'store' CHECK(order_source IN ('store','backend'))")
    cur.execute('CREATE INDEX IF NOT EXISTS idx_orders_owner_admin ON orders(owner_admin_id,created_at DESC,id DESC)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_store_users_linked_admin ON store_users(linked_admin_user_id)')
    cur.execute('CREATE TABLE IF NOT EXISTS sales_ownership_migrations(name TEXT PRIMARY KEY,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    cur.execute("INSERT INTO sales_ownership_migrations(name) VALUES('initial-owner-v1') ON CONFLICT DO NOTHING RETURNING name")
    if cur.fetchone():
        cur.execute("UPDATE orders SET order_source='backend' WHERE created_by_admin_id IS NOT NULL")
        cur.execute("SELECT to_regclass('public.admin_order_requests') AS requests")
        if cur.fetchone()['requests']:
            cur.execute('UPDATE orders o SET created_by_admin_id=r.actor_id FROM admin_order_requests r WHERE o.id=r.order_id AND o.created_by_admin_id IS NULL')
            cur.execute("UPDATE orders SET order_source='backend' WHERE EXISTS(SELECT 1 FROM admin_order_requests r WHERE r.order_id=orders.id)")
        cur.execute("UPDATE orders o SET owner_admin_id=a.id FROM admin_users a WHERE o.owner_admin_id IS NULL AND o.created_by_admin_id=a.id AND a.role='sales'")

def clause(owner_id, alias='o'):
    if owner_id is None: return 'TRUE', []
    if owner_id == 0: return f'{alias}.owner_admin_id IS NULL', []
    return f'{alias}.owner_admin_id=%s', [owner_id]

def parse_owner(value):
    if value in (None, ''): return None
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise ValueError('请选择有效业务员')
    return int(value)

def validate_owner(owner_id, *, previous=None):
    import db
    owner_id = parse_owner(owner_id)
    if owner_id is None or owner_id == previous: return owner_id
    # Serialize assignment with role changes/deletion (same lock as admin-users).
    db._fetch_one('SELECT pg_advisory_xact_lock(7192027)')
    row = db._fetch_one("SELECT id FROM admin_users WHERE id=%s AND role='sales' AND status='active' FOR KEY SHARE", (owner_id,))
    if not row: raise ValueError('请选择已启用的外贸部业务员')
    return owner_id

def scope(args, user):
    if user.get('role') == 'sales': return int(user['id'])
    if user.get('role') != 'admin': return None
    value = args.get('salespersonId')
    if value in (None, '', 'all'): return None
    if value == 'unassigned': return 0
    import db
    value = parse_owner(value)
    if not db._fetch_one("SELECT id FROM admin_users WHERE id=%s AND role='sales'", (value,)):
        raise ValueError('业务员不存在')
    return value

def assert_access(order_id, *, lock=False):
    from flask import g, abort
    if g.current_user.get('role') != 'sales': return
    import db
    row = db._fetch_one('SELECT owner_admin_id FROM orders WHERE id=%s'+(' FOR UPDATE' if lock else ''), (order_id,))
    if not row or row['owner_admin_id'] != g.current_user['id']: abort(404, description='订单不存在')

def link_account(user_id, value):
    import db
    db._fetch_one('SELECT pg_advisory_xact_lock(7192027)')
    row = db._fetch_one('SELECT linked_admin_user_id FROM store_users WHERE id=%s FOR UPDATE', (user_id,))
    if not row: raise ValueError('商城账号不存在')
    owner = validate_owner(value, previous=row['linked_admin_user_id'])
    db._fetch_one('UPDATE store_users SET linked_admin_user_id=%s,updated_at=NOW() WHERE id=%s RETURNING id', (owner, user_id))
    if owner is not None:
        db._fetch_all("UPDATE orders SET owner_admin_id=%s,updated_at=NOW() WHERE store_user_id=%s AND order_source='store' AND owner_admin_id IS NULL RETURNING id", (owner, user_id))

INVENTORY_KEYS = {'stock','availableStock','shortageUnits','shortageSizeCount','contractPending','pendingInspection','pendingInbound','emptySizeCount','estimatedDays','risk'}


def public_order(order):
    return {key: value for key, value in order.items()
            if key not in {'ownerAdminId', 'ownerAdminName', 'createdByAdminId', 'orderSource'}}

def personalize(result, owner_id):
    if owner_id is None: return result
    # Company stock / individual velocity is not company inventory turnover.
    result['scope'] = {'personal':True, 'ownerId':owner_id}
    def clean(value):
        if isinstance(value, dict):
            for key in list(value):
                if key in INVENTORY_KEYS: value.pop(key)
                else: clean(value[key])
        elif isinstance(value, list):
            for item in value: clean(item)
    clean(result)
    return result
