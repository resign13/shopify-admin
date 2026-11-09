"""Procurement overdelivery: persistent allowance, never derived from remaining stock.

The ledger survives rebuilding product_size_prices. Only real purchase contracts
grant allowance. Old/manual balances retain normal transfers without inventing a
contract total. Extra arrivals spend allowance permanently, including after returns.
"""
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
    totals = contract_totals(cur, product_ids)
    cur.execute('SELECT * FROM inventory_overdelivery WHERE product_id=ANY(%s)', (product_ids,))
    ledger = {(r['product_id'], r['size_code']): r for r in cur.fetchall()}
    return totals, ledger


def _contract_stage_counts(received, inspection, qualified, excess_inspection, excess_qualified,
                           contract_inspection=None, contract_qualified=None):
    # For old rows without stage provenance, infer at most the already recorded
    # contract receipts. In particular, zero recorded receipts means all of
    # the old ordinary inspection/qualified balance is outside the contract.
    if contract_inspection is None:
        contract_inspection = min(max(0, inspection-excess_inspection), max(0, received-(contract_qualified or 0)))
    if contract_qualified is None:
        contract_qualified = min(max(0, qualified-excess_qualified), max(0, received-contract_inspection))
    return contract_inspection, contract_qualified


def internal(total, ledger=None, row=None, *, include_stage_sources=False):
    ledger = ledger or {}
    used = int(ledger.get('used', 0))
    limit = min(MAX_QUANTITY, int(total) * 15 // 100)
    row = row or {}
    received = ledger.get('normal_received')
    if received is None:
        # Inspection/qualified balances can predate the first purchase contract.
        # They are not evidence that this contract has already received goods.
        # Once established, the persisted counter remains authoritative (including
        # after manual pending adjustments, receipt and defective returns).
        received = max(0, int(total)-int(row.get('contract_pending',total))) if total else 0
    result = {'originalContractQuantity': int(total), 'overdeliveryLimit': limit,
            'overdeliveryUsed': used, 'overdeliveryRemaining': max(0, limit-used),
            'overdeliveryInspection': int(ledger.get('inspection', 0)),
            'overdeliveryQualified': int(ledger.get('qualified', 0))}
    result['contractReceived'] = int(received)
    if include_stage_sources:
        ci, cb = _contract_stage_counts(int(received), row.get('pending_inspection', 0), row.get('pending_inbound', 0),
            result['overdeliveryInspection'], result['overdeliveryQualified'], ledger.get('contract_inspection'),
            ledger.get('contract_qualified'))
        result.update(contractInspection=ci, contractQualified=cb)
    return result


def attach(row, total, ledger=None):
    return {**row, **internal(total, ledger, row, include_stage_sources=True)}


def save(cur, product_id, size_code, state):
    cur.execute('''INSERT INTO inventory_overdelivery(product_id,size_code,used,inspection,qualified,normal_received,
      contract_inspection,contract_qualified) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(product_id,size_code) DO UPDATE
      SET used=EXCLUDED.used,inspection=EXCLUDED.inspection,qualified=EXCLUDED.qualified,normal_received=EXCLUDED.normal_received,
          contract_inspection=EXCLUDED.contract_inspection,contract_qualified=EXCLUDED.contract_qualified''',
      (product_id, size_code, state['overdeliveryUsed'], state['overdeliveryInspection'], state['overdeliveryQualified'],
       state['contractReceived'], state['contractInspection'], state['contractQualified']))


def transition(current, updates):
    p, i, b = (int(current[k]) for k in ['contract_pending', 'pending_inspection', 'pending_inbound'])
    used = int(current.get('overdeliveryUsed', 0))
    ei, eb = int(current.get('overdeliveryInspection', 0)), int(current.get('overdeliveryQualified', 0))
    limit = int(current.get('overdeliveryLimit', 0))
    total = int(current.get('originalContractQuantity', 0))
    received = int(current.get('contractReceived', 0))
    ci, cb = _contract_stage_counts(received, i, b, ei, eb, current.get('contractInspection'), current.get('contractQualified'))
    nb = updates.get('pendingInbound', b)
    ni = updates.get('pendingInspection', i-(nb-b))
    arrival = ni+nb-i-b
    np = p
    intermediate_inspection = i
    if nb < b:
        moved = b-nb
        extra = min(eb, moved)
        contract = min(cb, moved-extra)
        eb -= extra
        ei += extra
        cb -= contract
        ci += contract
        intermediate_inspection += moved
    if arrival > 0:
        # All actual undelivered stock is available for normal receipt. Use
        # the old/manual remainder first; only the contract portion advances
        # contract receipts. No manual change can increase the 15% allowance.
        contract_pending = min(p, max(0, total-received))
        normal = min(arrival, p)
        contract = max(0, normal-(p-contract_pending))
        extra = arrival-normal
        if used+extra > limit:
            raise ValueError(f'超出原合同数量累计15%额度：原合同 {current.get("originalContractQuantity", 0)}，允许超量 {limit}，已用 {used}，本次超量 {extra}')
        np -= normal
        ei += extra
        ci += contract
        used += extra
        received += contract
    elif arrival < 0:
        extra = min(ei, -arrival)
        contract = min(ci, -arrival-extra)
        ei -= extra
        ci -= contract
        np += -arrival-extra
        received -= contract
    intermediate_inspection += arrival
    if intermediate_inspection < 0:
        raise ValueError('本次转移超过待验货可用数量')
    if nb > b:
        moved = nb-b
        # Qualify ordinary units (old/manual, then contract) before extras.
        extra = max(0, moved-(intermediate_inspection-ei))
        contract = min(ci, max(0, moved-(intermediate_inspection-ei-ci)))
        ei -= extra
        eb += extra
        ci -= contract
        cb += contract
    moving = ni != i or nb != b
    pending = updates.get('contractPending', np)
    if moving and pending != np:
        raise ValueError('阶段转移时合同未送须按差额同步（超量部分不扣合同），请勿重复扣减或增加合同数量')
    if min(pending, ni, nb, ei, eb, ci, cb) < 0 or ei+ci > ni or eb+cb > nb or ci+cb > received:
        raise ValueError('本次转移超过上一阶段可用数量：请核对合同未送和待验货')
    if max(pending, ni, nb, used) > MAX_QUANTITY:
        raise ValueError('数量超出允许范围')
    return pending, ni, nb, {'overdeliveryUsed': used, 'overdeliveryInspection': ei, 'overdeliveryQualified': eb,
                             'contractReceived': received if total else None, 'contractInspection': ci, 'contractQualified': cb}


def return_preview(row, quantity):
    pending, inspection, _, sources = transition(row, {'pendingInspection': row['pending_inspection']-quantity})
    return {'contractAfter': pending, 'inspectionAfter': inspection,
            'extraReturned': row.get('overdeliveryInspection', 0)-sources['overdeliveryInspection'], **sources}
