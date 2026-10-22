"""Short database snapshots around otherwise detached file generation."""
from flask import g
import db
import order_printing
import sales_ownership
import workbench
from export_resources import stage


def snapshot(load):
    g.export_actor_role = g.current_user['role']
    with stage('snapshot'):
        return workbench.snapshot_admin_call(load, (), {})


def finish(response, orders, export_kind=None):
    """Recheck current identity, ownership and order versions before releasing a file."""
    def commit():
        if g.current_user['role'] != g.export_actor_role:
            raise workbench.Conflict('导出期间账号角色已修改，请重新导出。')
        ids = sorted({int(order['id']) for order in orders})
        rows = db._fetch_all('SELECT id,updated_at FROM orders WHERE id=ANY(%s) ORDER BY id FOR SHARE', (ids,))
        current = {r['id']: db._iso(r['updated_at']) for r in rows}
        for order in orders:
            sales_ownership.assert_access(order['id'])
            if current.get(order['id']) != order.get('updatedAt'):
                raise workbench.Conflict('导出期间订单已修改，请重新导出。')
        if export_kind:
            order_printing.record(db, orders, g.current_user, export_kind)
        return response
    try:
        with stage('finalize'):
            result = workbench.atomic_admin_call(commit, (), {})
        if result is not response:
            response.close()
        return result
    except BaseException:
        response.close()
        raise
