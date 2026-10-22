"""Aggregate saved order costs in PostgreSQL; materialize only the requested groups."""
from decimal import Decimal


def page(db, query, params, rate, page_number, page_size):
    # The caller owns one read-only snapshot for totals and the page's details.
    query = query.removesuffix(' ORDER BY o.created_at DESC,o.id DESC,i.id')
    raw = 'WITH raw AS (' + query + ')'
    keys = 'style_code,product_id,sku,size_code'
    summary_query = raw + ''' , amounts AS (
      SELECT *, CASE WHEN currency='USD' THEN unit_price*quantity ELSE 0 END AS usd,
        CASE WHEN currency='CNY' THEN unit_price*quantity ELSE 0 END AS native_cny,
        round(CASE WHEN currency='USD' THEN unit_price*quantity*%s ELSE 0 END,2)
          + CASE WHEN currency='CNY' THEN unit_price*quantity ELSE 0 END AS cny,
        cost_cny*quantity AS cost FROM raw)
      SELECT count(DISTINCT order_id) AS orders, COALESCE(sum(quantity),0) AS quantity,
        COALESCE(sum(quantity) FILTER(WHERE cost IS NULL),0) AS missing,
        COALESCE(sum(usd),0) AS usd, COALESCE(sum(native_cny),0) AS native_cny,
        COALESCE(sum(cny),0) AS cny, COALESCE(sum(cost),0) AS cost,
        COALESCE(sum(cny-cost),0) AS profit,
        (SELECT count(*) FROM (SELECT ''' + keys + ''' FROM raw GROUP BY ''' + keys + ''') k) AS groups
      FROM amounts'''
    s = db._fetch_one(summary_query, (*params, rate))
    money = lambda value: format(Decimal(value), '.2f')
    summary = {'orderCount': s['orders'], 'quantity': s['quantity'], 'missingQuantity': s['missing'],
        'salesUsd': money(s['usd']), 'nativeSalesCny': money(s['native_cny']), 'salesCny': money(s['cny']),
        'knownCostCny': money(s['cost']), 'totalCostCny': None if s['missing'] else money(s['cost']),
        'knownProfitCny': money(s['profit']), 'profitCny': None if s['missing'] else money(s['profit'])}
    rows = db._fetch_all(raw + ', selected AS (SELECT ' + keys + ' FROM raw GROUP BY ' + keys +
        ' ORDER BY style_code COLLATE "C",sku COLLATE "C",size_code COLLATE "C",product_id LIMIT %s OFFSET %s) SELECT r.* FROM raw r JOIN selected s ON ' +
        ' AND '.join('r.' + k + ' IS NOT DISTINCT FROM s.' + k for k in keys.split(',')) +
        ' ORDER BY r.created_at DESC,r.order_id DESC,r.item_id', (*params, page_size, (page_number-1)*page_size))
    return rows, summary, s['groups']
