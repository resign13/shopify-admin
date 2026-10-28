"""Private, ticket-bound completed exports; download never reruns a builder."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import os
from pathlib import Path
import shutil
import time
from urllib.parse import quote
from flask import abort, g, jsonify, send_file
import db
import export_queue
import module_permissions
import order_export_service
import sales_ownership
import workbench

TTL_SECONDS = 30 * 60
MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def folder():
    # Deliberately outside uploads/static and never exposed by a directory route.
    root = Path(os.environ.get('ORDER_EXPORT_RESULT_DIR') or
                (Path(__file__).resolve().parent / 'data' / 'order-export-results'))
    if os.environ.get('APP_ENV') == 'test':
        database = os.environ.get('PGDATABASE', '')
        if not database.endswith('_test'):
            raise ValueError('Export test results require a *_test database namespace')
        root = root / ('db-' + quote(database, safe=''))
    return root.resolve()


@lru_cache(maxsize=8)
def _private_folder(directory):
    from export_image_cache import _private_directory
    _private_directory(Path(directory))


def file_path(ticket):
    return folder() / (export_queue.parse_ticket(ticket) + '.xlsx')


def cleanup():
    directory = folder()
    if not directory.exists():
        return
    cutoff = time.time() - TTL_SECONDS
    for path in directory.glob('*.xlsx'):
        try:
            if path.stat().st_mtime <= cutoff:
                path.unlink(missing_ok=True)
        except (FileNotFoundError, PermissionError):
            # Windows may still have a previous download open; logical expiry
            # remains enforced and the next request retries physical removal.
            pass


def ready(ticket, filename, expires):
    base = '/api/admin/orders/export-results/' + ticket
    return {'ticketId': ticket, 'status': 'ready', 'statusUrl': base,
            'downloadUrl': base + '/download', 'filename': filename,
            'expiresAt': expires.isoformat()}


def deliver(stream, orders, filename, export_kind=None):
    ticket = getattr(g, 'security_export_ticket', None)
    if not ticket:
        response = send_file(stream, as_attachment=True, download_name=filename, mimetype=MIMETYPE)
        return order_export_service.finish(response, orders, export_kind)
    directory = folder()
    _private_folder(str(directory))
    cleanup()
    path = file_path(ticket)
    expires = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
    try:
        # Complete and close the file before finalizing ownership and print records.
        try:
            with path.open('xb') as output:
                os.chmod(path, 0o600)
                stream.seek(0)
                shutil.copyfileobj(stream, output)
        finally:
            stream.close()
        response = jsonify(ready(ticket, filename, expires))
        def publish():
            row = db._fetch_one('''UPDATE security_export_queue SET state='finished',result_name=%s,
                result_expires=%s,result_orders=%s,actor_role=%s,updated_at=clock_timestamp()
                WHERE ticket=%s AND state='started' RETURNING ticket''',
                (filename, expires, sorted({int(order['id']) for order in orders}),
                 g.export_actor_role, ticket))
            if not row:
                raise workbench.Conflict('导出请求状态已改变，请重新发起。')
        result = order_export_service.finish(response, orders, export_kind, on_success=publish)
        if result is not response:
            path.unlink(missing_ok=True)
        return result
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def authorized(ticket):
    """One short snapshot checks current session, original permission and ownership."""
    try:
        ticket = export_queue.parse_ticket(ticket)
    except ValueError:
        abort(404)
    def load():
        identity = getattr(g, 'current_session', None)
        current = db._fetch_one('''SELECT u.id,u.role,u.status,u.permissions FROM admin_users u
            JOIN admin_sessions s ON s.admin_user_id=u.id WHERE u.id=%s AND s.id=%s
            AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp()''',
            (g.current_user['id'], identity['session_id'] if identity else None))
        if not current or current['status'] != 'active':
            abort(401)
        row = db._fetch_one('''SELECT *,clock_timestamp() AS now FROM security_export_queue
            WHERE ticket=%s AND channel='admin' AND account_id=%s AND session_id=%s''',
            (ticket, current['id'], identity['public_id']))
        if not row:
            abort(404)
        roles = {'admin', 'sales'} if export_queue.is_invoice(row['path']) else {'admin', 'sales', 'warehouse'}
        if (not module_permissions.allows_operation(current, row['path'], row['method'], roles)
                or row['actor_role'] and current['role'] != row['actor_role']):
            abort(403)
        g.current_user = {**g.current_user, **current}
        ids = row['result_orders'] or []
        if ids:
            existing = db._fetch_all('SELECT id FROM orders WHERE id=ANY(%s)', (ids,))
            if len(existing) != len(ids):
                abort(404)
            for order_id in ids:
                sales_ownership.assert_access(order_id)
        return row
    return workbench.snapshot_admin_call(load, (), {})


def status(ticket, *, download=False):
    cleanup()
    row = authorized(ticket)
    ticket = str(row['ticket'])
    if row['state'] == 'waiting' and (row['now'] - row['created_at']).total_seconds() >= export_queue.WAIT_SECONDS:
        row['state'] = 'expired'
    if row['state'] == 'waiting' and (row['now'] - row['last_seen']).total_seconds() >= export_queue.HEARTBEAT_SECONDS:
        row['state'] = 'expired'
    if row['state'] == 'started':
        # An interrupted HTTP client leaves its running generator alone. Only a
        # vanished server owner (released advisory lock) makes the job terminal.
        with db._connect(autocommit=True, coordination=True) as conn:
            key = f'export:admin:{row["account_id"]}'
            unlocked = conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked', (key,)).fetchone()['locked']
            if unlocked:
                try:
                    conn.execute("UPDATE security_export_queue SET state='finished',updated_at=clock_timestamp() WHERE ticket=%s AND state='started'", (ticket,))
                finally:
                    conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))
                row = authorized(ticket)
    if row['result_name'] and row['result_expires'] > row['now'] and file_path(ticket).is_file():
        if download:
            try:
                return send_file(file_path(ticket), as_attachment=True,
                                 download_name=row['result_name'], mimetype=MIMETYPE, conditional=False)
            except FileNotFoundError:
                return jsonify({'code': 'export_result_expired', 'message': '导出文件已过期，请重新生成。'}), 410
        return jsonify(ready(ticket, row['result_name'], row['result_expires']))
    if row['result_name'] or row['state'] == 'expired':
        state, code, message = 'expired', 'export_result_expired', '导出文件或排队已过期，请重新生成。'
    elif row['state'] == 'finished':
        state, code, message = 'failed', row['result_code'] or 'export_failed', row['result_message'] or '导出失败，请重新生成。'
    else:
        state, code, message = row['state'], 'export_not_ready', '导出尚未完成，请稍后检查状态。'
    data = {'ticketId': ticket, 'status': state, 'statusUrl': '/api/admin/orders/export-results/' + ticket,
            'code': code, 'message': message}
    if download:
        return jsonify(data), 410 if state == 'expired' else 409
    return jsonify(data)
