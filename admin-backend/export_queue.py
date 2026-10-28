"""Persistent admission tickets for the admin order-export FIFO."""
import json
import re
import uuid

VERSION = 'order-export-queue-v2'
RETRY_SECONDS = 5
WAIT_SECONDS = 120
HEARTBEAT_SECONDS = 20
QUEUE_LIMIT = 10
# Fixed PostgreSQL advisory-lock namespace for short admission transactions.
MUTEX = 549728836142681785
ORDER_ROUTES = {'/api/admin/orders/export', '/api/admin/orders/export-by-sheet'}


def is_invoice(path):
    return re.fullmatch(r'/api/admin/orders/[0-9]+/invoice', path) is not None


def is_order_route(path):
    return path in ORDER_ROUTES or is_invoice(path)


def migrate(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS security_export_queue (
      seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      ticket UUID NOT NULL UNIQUE,
      channel TEXT NOT NULL,
      account_id BIGINT NOT NULL,
      session_id UUID NOT NULL,
      method TEXT NOT NULL,
      path TEXT NOT NULL,
      query TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('waiting','started','finished','expired')),
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      last_seen TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE INDEX IF NOT EXISTS security_export_queue_waiting ON security_export_queue(seq) WHERE state='waiting';
    CREATE OR REPLACE VIEW security_export_waiting AS
      SELECT EXISTS (SELECT 1 FROM security_export_queue WHERE state='waiting'
        AND created_at > clock_timestamp() - interval '120 seconds'
        AND last_seen > clock_timestamp() - interval '20 seconds') AS has_waiting;
    ALTER TABLE security_export_queue ADD COLUMN IF NOT EXISTS result_name TEXT;
    ALTER TABLE security_export_queue ADD COLUMN IF NOT EXISTS result_expires TIMESTAMPTZ;
    ALTER TABLE security_export_queue ADD COLUMN IF NOT EXISTS result_orders BIGINT[];
    ALTER TABLE security_export_queue ADD COLUMN IF NOT EXISTS actor_role TEXT;
    ALTER TABLE security_export_queue ADD COLUMN IF NOT EXISTS result_code TEXT;
    ALTER TABLE security_export_queue ADD COLUMN IF NOT EXISTS result_message TEXT;
    INSERT INTO security_schema_versions(version) VALUES('order-export-queue-v2') ON CONFLICT DO NOTHING''')


def identity(request):
    # Keep repeated parameter order, as it can affect request.args.get().
    query = [[key, request.args.getlist(key)] for key in sorted(request.args)]
    return request.method, request.path, json.dumps(query, ensure_ascii=False, separators=(',', ':'))


def parse_ticket(value):
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ValueError('Invalid export ticket') from None


def lock(conn):
    conn.execute('SELECT pg_advisory_xact_lock(%s)', (MUTEX,))


def expire(conn):
    from order_export_results import cleanup
    cleanup()
    conn.execute('''UPDATE security_export_queue SET state='expired',updated_at=clock_timestamp()
        WHERE state='waiting' AND (created_at <= clock_timestamp() - interval '120 seconds'
          OR last_seen <= clock_timestamp() - interval '20 seconds')''')
    # Keep terminal and orphaned started tickets for one day to reject replays.
    conn.execute("DELETE FROM security_export_queue WHERE state <> 'waiting' AND updated_at < clock_timestamp() - interval '1 day'")


def waiting(conn):
    return conn.execute('''SELECT seq,ticket,channel,account_id FROM security_export_queue WHERE state='waiting'
        AND created_at > clock_timestamp() - interval '120 seconds'
        AND last_seen > clock_timestamp() - interval '20 seconds' ORDER BY seq''').fetchall()


def has_waiting(conn):
    return conn.execute('SELECT has_waiting FROM security_export_waiting').fetchone()['has_waiting']


def first_runnable(conn):
    """Preserve order among accounts not already exporting."""
    for row in waiting(conn):
        key = f'export:{row["channel"]}:{row["account_id"]}'
        if conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked', (key,)).fetchone()['locked']:
            conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))
            return str(row['ticket'])
    return None


def enter(conn, ticket, channel, account, session, operation):
    """Return (error, position), keeping ticket identity bound to the request."""
    row = conn.execute('''SELECT seq,channel,account_id,session_id,method,path,query,state
        FROM security_export_queue WHERE ticket=%s''', (ticket,)).fetchone()
    if row:
        binding = (row['channel'], row['account_id'], str(row['session_id']), row['method'], row['path'], row['query'])
        if binding != (channel, account, str(session), *operation):
            return 'export_ticket_mismatch', None
        if row['state'] != 'waiting':
            return 'export_ticket_' + row['state'], None
        conn.execute("UPDATE security_export_queue SET last_seen=clock_timestamp(),updated_at=clock_timestamp() WHERE ticket=%s", (ticket,))
    else:
        if len(waiting(conn)) >= QUEUE_LIMIT:
            return 'export_queue_full', None
        conn.execute('''INSERT INTO security_export_queue(ticket,channel,account_id,session_id,method,path,query,state)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'waiting')''', (ticket, channel, account, session, *operation))
    rows = waiting(conn)
    return None, next(index for index, item in enumerate(rows, 1) if str(item['ticket']) == ticket)


def mark(conn, ticket, state):
    conn.execute('UPDATE security_export_queue SET state=%s,updated_at=clock_timestamp() WHERE ticket=%s', (state, ticket))
