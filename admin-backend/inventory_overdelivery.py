"""One undelivered balance per size; keep only ordinary vs extra stage counts."""
MAX_QUANTITY = 2147483647


def migrate_stage_sources(cur):
    # NULL means the stage predates source tracking; do not redistribute old stock.
    cur.execute('''ALTER TABLE inventory_overdelivery
      ADD COLUMN IF NOT EXISTS contract_inspection INTEGER CHECK(contract_inspection >= 0),
      ADD COLUMN IF NOT EXISTS contract_qualified INTEGER CHECK(contract_qualified >= 0)''')


def stage_sources_ready(cur):
    cur.execute('''SELECT count(*) = 2 AS ready FROM information_schema.columns
      WHERE table_schema='public' AND table_name='inventory_overdelivery'
        AND column_name IN ('contract_inspection','contract_qualified') AND data_type='integer' ''')
    return cur.fetchone()['ready']


def migrate(cur):
    cur.execute('SELECT pg_advisory_xact_lock(7192031)')
    cur.execute('''CREATE TABLE IF NOT EXISTS inventory_overdelivery (
      product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      size_code VARCHAR(32) NOT NULL,
      used INTEGER NOT NULL DEFAULT 0 CHECK(used >= 0),
      inspection INTEGER NOT NULL DEFAULT 0 CHECK(inspection >= 0),
      qualified INTEGER NOT NULL DEFAULT 0 CHECK(qualified >= 0),
      PRIMARY KEY(product_id,size_code),
      CHECK(inspection::bigint + qualified <= used));''')
    cur.execute('ALTER TABLE inventory_overdelivery ADD COLUMN IF NOT EXISTS normal_received BIGINT CHECK(normal_received >= 0)')
    migrate_stage_sources(cur)


def contract_totals(cur, product_ids):
    cur.execute("SELECT to_regclass('public.purchase_contracts') AS relation")
    if not cur.fetchone()['relation']:
        return {}
    # quantities are the immutable real-size snapshots used by contract deltas.
    cur.execute('''SELECT (item->>'productId')::bigint AS product_id, q.key AS size_code,
                   SUM(q.value::bigint) AS quantity
      FROM purchase_contracts c
      CROSS JOIN LATERAL jsonb_array_elements(c.snapshot->'items') item
      CROSS JOIN LATERAL jsonb_each_text(item->'quantities') q
      WHERE COALESCE((c.snapshot->>'cancelled')::boolean,FALSE)=FALSE
        AND (item->>'productId')::bigint=ANY(%s)
      GROUP BY (item->>'productId')::bigint,q.key''', (product_ids,))
    return {(r['product_id'], r['size_code']): int(r['quantity']) for r in cur.fetchall()}


def states(cur, product_ids):
    cur.execute('SELECT * FROM inventory_overdelivery WHERE product_id=ANY(%s)', (product_ids,))
    return {(r['product_id'], r['size_code']): r for r in cur.fetchall()}


def allowance(pending):
    return pending * 15 // 100


def internal(row, ledger=None):
    ledger = ledger or {}
    return {'overdeliveryLimit': allowance(row['contract_pending']),
            'overdeliveryUsed': int(ledger.get('used', 0)),
            'overdeliveryInspection': int(ledger.get('inspection', 0)),
            'overdeliveryQualified': int(ledger.get('qualified', 0))}


def attach(row, ledger=None):
    return {**row, **internal(row, ledger)}


def save(cur, product_id, size_code, state):
    # Old contract-specific columns remain historical; no backfill or reset.
    cur.execute('''INSERT INTO inventory_overdelivery(product_id,size_code,used,inspection,qualified)
      VALUES(%s,%s,%s,%s,%s) ON CONFLICT(product_id,size_code) DO UPDATE
      SET used=EXCLUDED.used,inspection=EXCLUDED.inspection,qualified=EXCLUDED.qualified
      WHERE (inventory_overdelivery.used,inventory_overdelivery.inspection,inventory_overdelivery.qualified)
         IS DISTINCT FROM (EXCLUDED.used,EXCLUDED.inspection,EXCLUDED.qualified)''',
      (product_id, size_code, state['overdeliveryUsed'], state['overdeliveryInspection'], state['overdeliveryQualified']))


def transition(current, updates):
    p, i, b = (int(current[k]) for k in ['contract_pending', 'pending_inspection', 'pending_inbound'])
    used = int(current.get('overdeliveryUsed', 0))
    ei, eb = int(current.get('overdeliveryInspection', 0)), int(current.get('overdeliveryQualified', 0))
    explicit_extra = updates.get('receiptExtra')
    nb = updates.get('pendingInbound', b)
    ni = updates.get('pendingInspection', i-(nb-b))
    arrival = ni+nb-i-b
    np = p
    intermediate_inspection = i
    if nb < b:
        moved = b-nb
        extra = min(eb, moved)
        eb -= extra
        ei += extra
        intermediate_inspection += moved
    if arrival > 0:
        extra = max(0, arrival-p) if explicit_extra is None else explicit_extra
        normal, limit = arrival-extra, allowance(p)
        if extra < 0 or extra > arrival:
            raise ValueError('本次超收须在 0 与本次实际到货之间')
        if extra > limit or normal > p:
            raise ValueError(f'按当前未送 {p} 件，超收最多 {limit} 件，本次最多登记 {p+limit} 件；正常到货不超过当前未送')
        np -= normal
        ei += extra
        used += extra
    elif explicit_extra:
        raise ValueError('只有新增到货时可登记本次超收')
    elif arrival < 0:
        extra = min(ei, -arrival)
        ei -= extra
        np += -arrival-extra
    intermediate_inspection += arrival
    if intermediate_inspection < 0:
        raise ValueError('本次转移超过待验货可用数量')
    if nb > b:
        moved = nb-b
        # Move ordinary units first; only marked extras fail to restore pending.
        extra = max(0, moved-(intermediate_inspection-ei))
        ei -= extra
        eb += extra
    moving = ni != i or nb != b
    pending = updates.get('contractPending', np)
    if moving and pending != np:
        raise ValueError('阶段转移时合同未送须按差额同步（超量部分不扣合同），请勿重复扣减或增加合同数量')
    if min(pending, ni, nb, ei, eb) < 0 or ei > ni or eb > nb:
        raise ValueError('本次转移超过上一阶段可用数量：请核对合同未送和待验货')
    if max(pending, ni, nb, used) > MAX_QUANTITY:
        raise ValueError('数量超出允许范围')
    return pending, ni, nb, {'overdeliveryUsed': used, 'overdeliveryInspection': ei, 'overdeliveryQualified': eb}


def return_preview(row, quantity):
    pending, inspection, _, sources = transition(row, {'pendingInspection': row['pending_inspection']-quantity})
    return {'contractAfter': pending, 'inspectionAfter': inspection,
            'extraReturned': row.get('overdeliveryInspection', 0)-sources['overdeliveryInspection'], **sources}
