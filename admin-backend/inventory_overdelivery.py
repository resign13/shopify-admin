"""Procurement overdelivery: persistent allowance, never derived from remaining stock.

The ledger survives rebuilding product_size_prices. Only real purchase contracts
grant allowance. Old/manual balances retain normal transfers without inventing a
contract total. Extra arrivals spend allowance permanently, including after returns.
"""
MAX_QUANTITY = 2147483647


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
    totals = contract_totals(cur, product_ids)
    cur.execute('SELECT * FROM inventory_overdelivery WHERE product_id=ANY(%s)', (product_ids,))
    ledger = {(r['product_id'], r['size_code']): r for r in cur.fetchall()}
    return totals, ledger


def internal(total, ledger=None, row=None):
    ledger = ledger or {}
    used = int(ledger.get('used', 0))
    limit = min(MAX_QUANTITY, int(total) * 15 // 100)
    row = row or {}
    received = ledger.get('normal_received')
    if received is None:
        received = max(0, int(total)-int(row.get('contract_pending',total)), int(row.get('pending_inspection',0))+int(row.get('pending_inbound',0))) if total else 0
    result = {'originalContractQuantity': int(total), 'overdeliveryLimit': limit,
            'overdeliveryUsed': used, 'overdeliveryRemaining': max(0, limit-used),
            'overdeliveryInspection': int(ledger.get('inspection', 0)),
            'overdeliveryQualified': int(ledger.get('qualified', 0))}
    # A cumulative normal counter also prevents manually increasing the remaining
    # balance from manufacturing another original-contract allowance.
    return {**result, 'contractReceived': int(received)}


def attach(row, total, ledger=None):
    return {**row, **internal(total, ledger, row)}


def save(cur, product_id, size_code, state):
    cur.execute('''INSERT INTO inventory_overdelivery(product_id,size_code,used,inspection,qualified,normal_received)
      VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(product_id,size_code) DO UPDATE
      SET used=EXCLUDED.used,inspection=EXCLUDED.inspection,qualified=EXCLUDED.qualified,normal_received=EXCLUDED.normal_received''',
      (product_id, size_code, state['overdeliveryUsed'], state['overdeliveryInspection'], state['overdeliveryQualified'], state.get('contractReceived')))


def transition(current, updates):
    p, i, b = (int(current[k]) for k in ['contract_pending', 'pending_inspection', 'pending_inbound'])
    used = int(current.get('overdeliveryUsed', 0))
    ei, eb = int(current.get('overdeliveryInspection', 0)), int(current.get('overdeliveryQualified', 0))
    limit = int(current.get('overdeliveryLimit', 0))
    total = int(current.get('originalContractQuantity', 0))
    received = int(current.get('contractReceived', 0))
    nb = updates.get('pendingInbound', b)
    ni = updates.get('pendingInspection', i-(nb-b))
    arrival = ni+nb-i-b
    np = p
    intermediate_inspection = i
    if nb < b:
        extra = min(eb, b-nb)
        eb -= extra
        ei += extra
        intermediate_inspection += b-nb
    if arrival > 0:
        normal = min(arrival, p, max(0,total-received)) if total else min(arrival,p)
        extra = arrival-normal
        if used+extra > limit:
            raise ValueError(f'超出原合同数量累计15%额度：原合同 {current.get("originalContractQuantity", 0)}，允许超量 {limit}，已用 {used}，本次超量 {extra}')
        np -= arrival-extra
        ei += extra
        used += extra
        received += normal
    elif arrival < 0:
        extra = min(ei, -arrival)
        ei -= extra
        np += -arrival-extra
        received -= -arrival-extra
    intermediate_inspection += arrival
    if intermediate_inspection < 0:
        raise ValueError('本次转移超过待验货可用数量')
    if nb > b:
        extra = max(0, nb-b-(intermediate_inspection-ei))
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
    return pending, ni, nb, {'overdeliveryUsed': used, 'overdeliveryInspection': ei, 'overdeliveryQualified': eb, 'contractReceived': max(0,received) if total else None}


def return_preview(row, quantity):
    extra = min(quantity, int(row.get('overdeliveryInspection', 0)))
    return {'contractAfter': row['contract_pending']+quantity-extra,
            'inspectionAfter': row['pending_inspection']-quantity,
            'extraReturned': extra,
            'overdeliveryUsed': int(row.get('overdeliveryUsed', 0)),
            'overdeliveryInspection': int(row.get('overdeliveryInspection', 0))-extra,
            'overdeliveryQualified': int(row.get('overdeliveryQualified', 0)),
            'contractReceived': max(0, int(row.get('contractReceived',0))-quantity+extra) if row.get('originalContractQuantity') else None}
