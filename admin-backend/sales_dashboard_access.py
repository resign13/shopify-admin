"""Explicit, audited one-time permission upgrade; never run implicitly on startup."""
import json
import uuid

MARKER = 'sales-dashboard-access-v1'


def candidates(conn):
    return conn.execute("""SELECT id FROM admin_users WHERE role='sales' AND status='active'
        AND permissions IS NOT NULL AND NOT permissions ? 'dashboard' ORDER BY id""").fetchall()


def apply_once(conn):
    conn.execute('SELECT pg_advisory_xact_lock(7192027)')
    inserted = conn.execute('INSERT INTO sales_ownership_migrations(name) VALUES(%s) ON CONFLICT DO NOTHING RETURNING name', (MARKER,)).fetchone()
    if not inserted:
        return {'alreadyApplied': True, 'changedIds': []}
    actor = {'id': None, 'name': '经营工作台权限升级', 'role': 'system'}
    for key, value in {'actor': json.dumps(actor, ensure_ascii=False), 'module': 'admin-users', 'batch': str(uuid.uuid4())}.items():
        conn.execute('SELECT set_config(%s,%s,true)', ('gingtto.' + key, value))
    rows = conn.execute("""UPDATE admin_users SET permissions=permissions || '["dashboard"]'::jsonb,
        updated_at=clock_timestamp() WHERE role='sales' AND status='active'
        AND permissions IS NOT NULL AND NOT permissions ? 'dashboard' RETURNING id""").fetchall()
    return {'alreadyApplied': False, 'changedIds': sorted(row['id'] for row in rows)}
