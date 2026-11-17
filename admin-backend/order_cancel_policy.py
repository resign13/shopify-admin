"""Shared cancellation workflow. Callers own short transactions and identity checks."""
import json
import uuid
from flask import g, has_request_context

DIRECT = {'pending_payment', 'partially_allocated'}
PROTECTED = {'allocated', 'paid', 'shipped', 'completed'}
STAGES = ['pending_payment', 'paid', 'partially_allocated', 'allocated', 'shipped', 'completed']
APPROVE_PERMISSION = 'orders.cancel.approve'


class Conflict(Exception):
    pass


def migrate(cur):
    cur.execute("""ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_from_status TEXT;
      CREATE TABLE IF NOT EXISTS order_cancellation_requests (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        order_id BIGINT REFERENCES orders(id) ON DELETE SET NULL,
        order_no TEXT NOT NULL,
        requester_kind TEXT NOT NULL CHECK(requester_kind IN ('admin','store')),
        requester_id BIGINT NOT NULL, requester_name TEXT NOT NULL,
        reason TEXT NOT NULL CHECK(char_length(reason) BETWEEN 1 AND 500),
        order_status TEXT NOT NULL, order_version TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','approved','rejected','withdrawn')),
        revision BIGINT NOT NULL DEFAULT 1,
        reviewer_id BIGINT, reviewer_name TEXT, review_note TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), closed_at TIMESTAMPTZ
      );
      CREATE UNIQUE INDEX IF NOT EXISTS order_cancellation_one_pending
        ON order_cancellation_requests(order_id) WHERE state='pending';
      CREATE INDEX IF NOT EXISTS order_cancellation_order_history ON order_cancellation_requests(order_id,id DESC);
      CREATE INDEX IF NOT EXISTS order_cancellation_review_list ON order_cancellation_requests(state,id DESC);
      CREATE TABLE IF NOT EXISTS order_cancellation_migrations(name TEXT PRIMARY KEY);
    """)
    cur.execute("SELECT to_regclass('public.admin_audit_logs') AS audit")
    if cur.fetchone()['audit']:
        cur.execute("INSERT INTO order_cancellation_migrations(name) VALUES('restore-history-v1') ON CONFLICT DO NOTHING RETURNING name")
        if cur.fetchone():
            cur.execute("""UPDATE orders o SET cancelled_from_status=h.previous_status FROM (
              SELECT DISTINCT ON (object_id) object_id,before_data->>'status' AS previous_status
              FROM admin_audit_logs WHERE entity_table='orders' AND action='UPDATE'
                AND after_data->>'status'='cancelled' AND before_data->>'status'=ANY(%s)
              ORDER BY object_id,occurred_at DESC,id DESC
            ) h WHERE o.id::text=h.object_id AND o.status='cancelled' AND o.cancelled_from_status IS NULL""", (STAGES,))
    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='admin_users' AND column_name='permissions') AS present")
    if cur.fetchone()['present']:
        cur.execute("INSERT INTO order_cancellation_migrations(name) VALUES('admin-approval-grant-v1') ON CONFLICT DO NOTHING RETURNING name")
        if cur.fetchone():
            cur.execute("""UPDATE admin_users SET permissions=permissions || %s::jsonb
                WHERE role='admin' AND permissions IS NOT NULL AND permissions ? 'orders'
                AND NOT permissions ? 'orders.cancel.approve'""", (json.dumps([APPROVE_PERMISSION]),))
    cur.execute("INSERT INTO order_cancellation_migrations(name) VALUES('workflow-v1') ON CONFLICT DO NOTHING")


def require_ready(conn):
    row=conn.execute("SELECT to_regclass('public.order_cancellation_migrations') AS name").fetchone()
    if not row['name'] or not conn.execute("SELECT 1 FROM order_cancellation_migrations WHERE name='workflow-v1'").fetchone():
        raise RuntimeError('Database cancellation approval migration is required')


def reason(value, *, required=True):
    if not isinstance(value, str) or len(value.strip()) > 500 or '\x00' in value:
        raise ValueError('申请原因或审核意见须为 500 字以内的文字')
    value = value.strip()
    if required and not value:
        raise ValueError('请填写申请原因或驳回原因')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError('申请原因或审核意见须为有效文字') from error
    return value


def assert_mutable(cur, order_id, *, approval_id=None):
    cur.execute("SELECT id FROM order_cancellation_requests WHERE order_id=%s AND state='pending'", (order_id,))
    pending = cur.fetchone()
    if pending and pending['id'] != approval_id:
        raise Conflict('取消申请正在审核，请先撤回申请或完成审核后再操作。')
    if approval_id is not None and (not pending or pending['id'] != approval_id):
        raise Conflict('取消申请已处理，请刷新订单。')


def validate_transition(previous, next_status, cancelled_from=None, *, approved=False):
    if previous == next_status:
        return
    if previous == 'cancelled':
        if cancelled_from not in STAGES or next_status != cancelled_from:
            raise ValueError('已取消订单仅可恢复到取消前状态；旧订单缺少可靠记录时请使用“再来一单”。')
        return
    if next_status == 'cancelled':
        if previous in PROTECTED and not approved:
            raise Conflict('该状态取消订单需要提交申请并审核通过。')
        return
    if previous in PROTECTED and next_status in STAGES and STAGES.index(next_status) < STAGES.index(previous):
        raise ValueError('当前订单状态不支持回退到更早状态。')


def serialize(row, *, public=False, actor=None, source='admin'):
    if not row:
        return None
    if actor is None:
        actor = getattr(g, 'current_user', {}) if has_request_context() else {}
    result = {'id': row['id'], 'orderId': row['order_id'], 'orderNo': row['order_no'],
              'state': row['state'], 'version': str(row['revision']), 'reason': row['reason'] if not public or row['requester_kind']=='store' else '',
              'reviewNote': row['review_note'] if not public or row['requester_kind']=='store' else '', 'createdAt': str(row['created_at']) if isinstance(row['created_at'],str) else row['created_at'].isoformat(),
              'closedAt': (str(row['closed_at']) if isinstance(row['closed_at'],str) else row['closed_at'].isoformat()) if row['closed_at'] else None,
              'canWithdraw': row['state']=='pending' and row['requester_kind']==source and row['requester_id']==actor.get('id')}
    if not public:
        result.update(requesterKind=row['requester_kind'],requesterName=row['requester_name'],
                      reviewerName=row['reviewer_name'] or '',orderStatus=row['order_status'])
    return result


def presentation(status, cancelled_from, request_row, *, public=False):
    pending = request_row and request_row['state']=='pending'
    return {'cancelApprovalRequired': status in PROTECTED,
            'canCancel': status in DIRECT and not pending,
            'canRequestCancellation': status in PROTECTED and not pending,
            **({} if public else {'cancelledFromStatus': cancelled_from,
                                  'canRestore':status=='cancelled' and cancelled_from in STAGES}),
            'cancelRequest':serialize(request_row,public=public,source='store' if public else 'admin')}


def audit(db, row, actor, source, action):
    if source!='admin':
        return  # Store runtime cannot write the internal admin audit table.
    if not db._fetch_one("SELECT to_regclass('public.admin_audit_logs') AS name")['name']:
        return  # The request itself retains the complete actor/decision history.
    db._fetch_one("""INSERT INTO admin_audit_logs(actor,module,action,entity_table,object_id,batch_id,before_data,after_data)
      VALUES(%s::jsonb,'orders',%s,'order_cancellation_requests',%s,%s,NULL,%s::jsonb) RETURNING id""",
      (json.dumps({'id':actor['id'],'name':actor.get('name',''),'role':actor.get('role','customer'),'channel':source}),
       action,str(row['order_id'] or row['order_no']),str(uuid.uuid4()),
       json.dumps({'requestId':row['id'],'state':row['state'],'reason':row['reason'],'reviewNote':row['review_note']})))


def locked_order(db, order_id):
    order = db._fetch_one('SELECT *,updated_at::text AS version FROM orders WHERE id=%s FOR UPDATE', (order_id,))
    if not order:
        raise Conflict('订单不存在，请刷新列表。')
    return order


def submit(db, order_id, actor, source, payload):
    order = locked_order(db, order_id)
    if source=='store' and order['store_user_id'] != actor['id']:
        from flask import abort
        abort(404)
    if order['status'] not in PROTECTED:
        raise Conflict('该订单当前状态不适用取消审批，请刷新订单。')
    with db.get_connection() as conn, conn.cursor() as cur:
        assert_mutable(cur,order_id)
    if source=='admin' and str(payload.get('version','')) != order['version']:
        raise Conflict('订单已更新，请刷新后重新提交申请。')
    row = db._fetch_one("""INSERT INTO order_cancellation_requests
      (order_id,order_no,requester_kind,requester_id,requester_name,reason,order_status,order_version)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
      (order_id,order['order_no'],source,actor['id'],actor.get('name',''),reason(payload.get('reason')),
       order['status'],order['version']))
    audit(db,row,actor,source,'cancel_request_submit')
    return serialize(row,public=source=='store',actor=actor,source=source)


def decide(db, request_id, actor, source, payload, decision, *, apply_cancel=None):
    before = db._fetch_one('SELECT * FROM order_cancellation_requests WHERE id=%s', (request_id,))
    if not before or not before['order_id']:
        from flask import abort
        abort(404)
    order = locked_order(db,before['order_id'])
    row = db._fetch_one('SELECT * FROM order_cancellation_requests WHERE id=%s FOR UPDATE',(request_id,))
    if source=='store' and order['store_user_id'] != actor['id']:
        from flask import abort
        abort(404)
    if decision=='withdrawn' and (row['requester_kind']!=source or row['requester_id']!=actor['id']):
        from flask import abort
        abort(403)
    if row['state']!='pending' or str(payload.get('version','')) != str(row['revision']):
        raise Conflict('取消申请已更新或已处理，请刷新。')
    note = reason(payload.get('reviewNote',''),required=decision=='rejected') if decision!='withdrawn' else ''
    if decision=='approved':
        if source!='admin' or apply_cancel is None:
            from flask import abort
            abort(403)
        if order['status']!=row['order_status'] or order['version']!=row['order_version']:
            raise Conflict('订单已发生变化，请撤回或驳回后重新申请。')
        apply_cancel(order,row)
    if decision=='withdrawn':
        row=db._fetch_one("UPDATE order_cancellation_requests SET state='withdrawn',closed_at=clock_timestamp(),revision=revision+1 WHERE id=%s RETURNING *",(request_id,))
    else:
        row = db._fetch_one("""UPDATE order_cancellation_requests SET state=%s,review_note=%s,
          reviewer_id=%s,reviewer_name=%s,closed_at=clock_timestamp(),revision=revision+1 WHERE id=%s RETURNING *""",
          (decision,note,actor['id'],actor.get('name',''),request_id))
    audit(db,row,actor,source,'cancel_request_'+decision)
    return serialize(row,public=source=='store',actor=actor,source=source)


def history(db, order_id, *, public=False):
    rows = db._fetch_all('SELECT * FROM order_cancellation_requests WHERE order_id=%s ORDER BY id DESC', (order_id,))
    return [serialize(r,public=public,source='store' if public else 'admin') for r in rows]


def listing(db, args):
    state = args.get('state','pending')
    page = int(args.get('page',1))
    if state not in {'pending','processed'} or not 1<=page<=2147483647:
        raise ValueError('审批分页或筛选无效')
    condition = "state='pending'" if state=='pending' else "state<>'pending'"
    total = db._fetch_one('SELECT count(*) AS n FROM order_cancellation_requests WHERE '+condition)['n']
    pending = db._fetch_one("SELECT count(*) AS n FROM order_cancellation_requests WHERE state='pending'")['n']
    rows = db._fetch_all('SELECT * FROM order_cancellation_requests WHERE '+condition+' ORDER BY id DESC LIMIT 20 OFFSET %s',((page-1)*20,))
    return {'items':[serialize(r) for r in rows],'total':total,'pendingCount':pending,'page':page,'pageSize':20}
