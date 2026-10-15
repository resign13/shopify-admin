"""Persistent first successful warehouse export, independent of order state."""


def migrate(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS order_warehouse_prints (
        order_id BIGINT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
        printed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        printed_by_admin_id BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
        printed_by_name TEXT NOT NULL DEFAULT '',
        export_kind TEXT NOT NULL CHECK (export_kind IN ('export', 'export-by-sheet'))
    )""")


def record(db, orders, actor, export_kind):
    """Record only trusted, already-authorized export results in one transaction.

    A repeated download keeps the first mark/actor. No order version, payment,
    quantity, inventory or notification row is touched.
    """
    if actor.get('role') != 'warehouse' or not orders:
        return
    if export_kind not in {'export', 'export-by-sheet'}:
        raise ValueError('Unsupported warehouse export type')
    ids = sorted({int(order['id']) for order in orders})
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO order_warehouse_prints
                (order_id, printed_by_admin_id, printed_by_name, export_kind)
                VALUES (%s,%s,%s,%s) ON CONFLICT (order_id) DO NOTHING""",
                [(order_id, actor['id'], actor.get('name') or '', export_kind) for order_id in ids])
