"""Internal workbench queries, transaction boundary and audit integration."""
import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal

from flask import g, jsonify, request, make_response
from psycopg.types.json import Jsonb
import db
import inventory_policy

SHANGHAI = timezone(timedelta(hours=8))


def _style_code_sql(alias: str = "p") -> str:
    """SQL expression shared by dashboard aggregations and product filters."""
    return f"""
      COALESCE(
        NULLIF(BTRIM({alias}.style_code), ''),
        CASE
          WHEN NULLIF(BTRIM({alias}.color_group), '') IS NOT NULL
               AND LOWER(BTRIM({alias}.color_group)) <> LOWER(BTRIM({alias}.product_code))
            THEN BTRIM({alias}.color_group)
          ELSE COALESCE(
            NULLIF(regexp_replace(BTRIM(COALESCE(NULLIF({alias}.product_code, ''), NULLIF({alias}.sku, ''))), '[-_－][^-_－]+$', ''), ''),
            NULLIF(BTRIM({alias}.product_code), ''),
            NULLIF(BTRIM({alias}.sku), ''),
            '未归类'
          )
        END
      )
    """


def _dashboard_window(args, default_days: int = 30):
    end = date.fromisoformat(args.get('dateTo') or datetime.now(SHANGHAI).date().isoformat())
    start = date.fromisoformat(args.get('dateFrom') or (end - timedelta(days=default_days - 1)).isoformat())
    if start > end:
        raise ValueError('开始日期不能晚于结束日期')
    if (end - start).days > 1095:
        raise ValueError('查询时间不能超过三年')
    return start, end, (end - start).days + 1


def _style_catalog_parts(args, style_code: str | None = None):
    style_sql = _style_code_sql('p')
    where, params = ['(p.is_active = TRUE OR EXISTS(SELECT 1 FROM product_size_prices debt WHERE debt.product_id=p.id AND debt.stock<0))'], []
    if args.get('style') not in {None, '', 'all'}:
        where.append(f"({style_sql}=%s OR COALESCE(NULLIF(p.product_code,''),p.sku)=%s)")
        params.extend([args['style']] * 2)
    if args.get('category') and args.get('category') != 'all':
        where.append('pc.category_key=%s')
        params.append(args['category'])
    if args.get('keyword'):
        where.append(
            f"({style_sql} ILIKE %s OR concat_ws(' ',p.sku,p.product_code,p.color_name,p.color_group) ILIKE %s "
            "OR COALESCE(NULLIF(pt.name,''),NULLIF(pte.name,''),p.product_code,p.sku,'') ILIKE %s)"
        )
        params.extend([f"%{args['keyword']}%"] * 3)
    if style_code:
        where.append(f"{style_sql}=%s")
        params.append(style_code)
    cte = f"""
      product_catalog AS (
        SELECT
          p.id,
          {style_sql} AS style_code,
          p.product_code,
          p.sku,
          p.color_name,
          p.color_hex,
          p.main_image_url,
          p.stock AS product_stock,
          pc.category_key,
          COALESCE(NULLIF(pt.name,''),NULLIF(pte.name,''),p.product_code,p.sku,'') AS name
        FROM products p
        JOIN product_categories pc ON pc.id=p.category_id
        LEFT JOIN product_translations pt ON pt.product_id=p.id AND pt.lang_code='zh'
        LEFT JOIN product_translations pte ON pte.product_id=p.id AND pte.lang_code='en'
        WHERE {' AND '.join(where)}
      )
    """
    return cte, params


def _style_sales_join(args, start: date, end: date, *, days: int | None = None):
    actual_start = end - timedelta(days=(days - 1 if days else 0)) if days else start
    clauses = [
        "o.status <> 'cancelled'",
        "o.created_at >= %s",
        "o.created_at < %s",
    ]
    params = [datetime.combine(actual_start, datetime.min.time(), SHANGHAI),
              datetime.combine(end + timedelta(days=1), datetime.min.time(), SHANGHAI)]
    if args.get('country') and args.get('country') != 'all':
        clauses.append('o.country=%s')
        params.append(args['country'])
    return ' AND '.join(clauses), params


def _style_row(row):
    result = dict(row)
    for key in ('units', 'velocityUnits', 'orders', 'customers', 'stock', 'contractPending',
                'pendingInspection', 'pendingInbound', 'colorSkuCount', 'sizeCount', 'emptySizeCount', 'availableStock', 'shortageUnits', 'shortageSizeCount'):
        if key in result:
            result[key] = int(result[key] or 0)
    for key in ('amount', 'averageDailyUnits'):
        if key in result:
            result[key] = round(float(result[key] or 0), 2)
    if 'estimatedDays' in result:
        result['estimatedDays'] = round(float(result['estimatedDays']), 1) if result['estimatedDays'] is not None else None
    if isinstance(result.get('lastSoldAt'), datetime):
        result['lastSoldAt'] = db._iso(result['lastSoldAt'])
    if 'velocityUnits' in result:
        result['risk'] = ('backordered' if result.get('shortageUnits', 0) > 0 else
                          'out_of_stock' if result.get('availableStock', result['stock']) <= 0 else
                          'no_sales' if result['velocityUnits'] == 0 else
                          'critical' if result['estimatedDays'] <= 7 else
                          'warning' if result['estimatedDays'] <= 30 else 'healthy')
    return result


def style_performance(args):
    start, end, span = _dashboard_window(args)
    velocity_days = int(args.get('velocityWindow', 7) or 7)
    if velocity_days not in {7, 30}:
        raise ValueError('周转计算窗口只支持近 7 天或近 30 天')
    page = int(args.get('page', 1) or 1)
    page_size = int(args.get('pageSize', 10) or 10)
    if page < 1 or page_size not in {10, 25, 50}:
        raise ValueError('款号分页参数无效')
    catalog_cte, catalog_params = _style_catalog_parts(args)
    window_join, window_params = _style_sales_join(args, start, end)
    velocity_join, velocity_params = _style_sales_join(args, start, end, days=velocity_days)
    metrics_sql = f"""
      WITH {catalog_cte},
      style_catalog AS (
        SELECT pc.style_code, MAX(pc.name) AS name,
               COUNT(DISTINCT pc.id) AS color_sku_count,
               COUNT(psp.id) AS size_count,
               COUNT(*) FILTER (WHERE psp.stock=0) AS empty_size_count,
               COALESCE(SUM(psp.stock),0) AS stock,
               COALESCE(SUM(GREATEST(psp.stock,0)),0) AS available_stock,
               COALESCE(SUM(GREATEST(-psp.stock::bigint,0)),0) AS shortage_units,
               COUNT(*) FILTER (WHERE psp.stock<0) AS shortage_size_count,
               COALESCE(SUM(psp.contract_pending),0) AS contract_pending,
               COALESCE(SUM(psp.pending_inspection),0) AS pending_inspection,
               COALESCE(SUM(psp.pending_inbound),0) AS pending_inbound
        FROM product_catalog pc
        LEFT JOIN product_size_prices psp ON psp.product_id=pc.id
        GROUP BY pc.style_code
      ),
      window_sales AS (
        SELECT pc.style_code, SUM(i.quantity) AS units, SUM(i.total_price) AS amount,
               COUNT(DISTINCT o.id) AS orders, COUNT(DISTINCT o.store_user_id) AS customers,
               MAX(o.created_at) AS last_sold_at
        FROM product_catalog pc
        JOIN order_items i ON i.product_id=pc.id
        JOIN orders o ON o.id=i.order_id
        WHERE {window_join}
        GROUP BY pc.style_code
      ),
      velocity_sales AS (
        SELECT pc.style_code, SUM(i.quantity) AS units
        FROM product_catalog pc
        JOIN order_items i ON i.product_id=pc.id
        JOIN orders o ON o.id=i.order_id
        WHERE {velocity_join}
        GROUP BY pc.style_code
      ),
      metrics AS (
        SELECT c.style_code, c.name, c.color_sku_count, c.size_count, c.empty_size_count,
               c.stock, c.available_stock, c.shortage_units, c.shortage_size_count, c.contract_pending, c.pending_inspection, c.pending_inbound,
               COALESCE(w.units,0) AS units, COALESCE(w.amount,0) AS amount,
               COALESCE(w.orders,0) AS orders, COALESCE(w.customers,0) AS customers,
               COALESCE(v.units,0) AS velocity_units, w.last_sold_at,
               ROUND(COALESCE(v.units,0)::numeric / %s, 2) AS average_daily_units,
               CASE WHEN COALESCE(v.units,0)=0 OR c.available_stock=0 THEN NULL
                    ELSE ROUND(c.available_stock::numeric / (v.units::numeric / %s), 1) END AS estimated_days
        FROM style_catalog c
        LEFT JOIN window_sales w ON w.style_code=c.style_code
        LEFT JOIN velocity_sales v ON v.style_code=c.style_code
      )
      SELECT style_code AS "styleCode", name, units, amount, orders, customers,
             velocity_units AS "velocityUnits", average_daily_units AS "averageDailyUnits",
             estimated_days AS "estimatedDays", stock, available_stock AS "availableStock", shortage_units AS "shortageUnits", shortage_size_count AS "shortageSizeCount", contract_pending AS "contractPending",
             pending_inspection AS "pendingInspection", pending_inbound AS "pendingInbound",
             color_sku_count AS "colorSkuCount", size_count AS "sizeCount",
             empty_size_count AS "emptySizeCount", last_sold_at AS "lastSoldAt",
             CASE WHEN shortage_units>0 THEN 'backordered'
                  WHEN available_stock=0 THEN 'out_of_stock'
                  WHEN velocity_units=0 THEN 'no_sales'
                  WHEN estimated_days <= 7 THEN 'critical'
                  WHEN estimated_days <= 30 THEN 'warning'
                  ELSE 'healthy' END AS risk
      FROM metrics
    """
    base_params = [*catalog_params, *window_params, *velocity_params, velocity_days, velocity_days]
    risk = str(args.get('risk') or '').strip()
    risk_filter = ''
    risk_params = []
    if risk and risk not in {'backordered', 'out_of_stock', 'no_sales', 'critical', 'warning', 'healthy'}:
        raise ValueError('库存状态无效')
    if risk:
        risk_filter = ' WHERE risk=%s'
        risk_params = [risk]
    summary = db._fetch_one(
        f"SELECT COUNT(*) AS total, COALESCE(SUM(units),0) AS units, COALESCE(SUM(amount),0) AS amount, "
        f'COALESCE(SUM("availableStock"),0) AS available_stock, COALESCE(SUM("shortageUnits"),0) AS shortage_units, COALESCE(SUM("shortageSizeCount"),0) AS shortage_size_count, COALESCE(SUM(stock),0) AS stock, COALESCE(SUM("contractPending"),0) AS contract_pending, '
        f'COALESCE(SUM("pendingInspection"),0) AS pending_inspection, '
        f'COALESCE(SUM("pendingInbound"),0) AS pending_inbound FROM ({metrics_sql}) q{risk_filter}',
        tuple([*base_params, *risk_params]),
    )
    sort_map = {
        'units': 'units', 'amount': 'amount', 'stock': 'stock',
        'estimatedDays': '"estimatedDays"', 'lastSoldAt': '"lastSoldAt"',
        'styleCode': '"styleCode"', 'velocityUnits': '"velocityUnits"',
    }
    order = sort_map.get(args.get('sort'), 'units')
    direction = 'ASC' if args.get('direction') == 'asc' else 'DESC'
    total = int(summary['total'] or 0)
    page = min(page, max(1, (total + page_size - 1) // page_size))
    rows = db._fetch_all(
        f'SELECT * FROM ({metrics_sql}) q{risk_filter} ORDER BY {order} {direction} NULLS LAST, "styleCode" ASC LIMIT %s OFFSET %s',
        tuple([*base_params, *risk_params, page_size, (page - 1) * page_size]),
    )
    return {
        'items': [_style_row(row) for row in rows],
        'total': total,
        'page': page,
        'pageSize': page_size,
        'summary': {
            'styleCount': int(summary['total'] or 0),
            'units': int(summary['units'] or 0),
            'amount': float(summary['amount'] or 0),
            'stock': int(summary['stock'] or 0),
            'availableStock': int(summary['available_stock']), 'shortageUnits': int(summary['shortage_units']), 'shortageSizeCount': int(summary['shortage_size_count']),
            'contractPending': int(summary['contract_pending'] or 0),
            'pendingInspection': int(summary['pending_inspection'] or 0),
            'pendingInbound': int(summary['pending_inbound'] or 0),
        },
        'salesWindow': {'dateFrom': start.isoformat(), 'dateTo': end.isoformat(), 'days': span},
        'velocityWindow': {'days': velocity_days, 'dateFrom': (end - timedelta(days=velocity_days - 1)).isoformat(), 'dateTo': end.isoformat()},
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }


def _style_detail_rows(args, style_code: str, product_id: int | None = None):
    start, end, span = _dashboard_window(args)
    velocity_days = int(args.get('velocityWindow', 7) or 7)
    if velocity_days not in {7, 30}:
        raise ValueError('周转计算窗口只支持近 7 天或近 30 天')
    catalog_cte, catalog_params = _style_catalog_parts(args, style_code)
    window_join, window_params = _style_sales_join(args, start, end)
    velocity_join, velocity_params = _style_sales_join(args, start, end, days=velocity_days)
    product_filter = ' WHERE pc.id=%s' if product_id is not None else ''
    product_params = [product_id] if product_id is not None else []
    sql = f"""
      WITH {catalog_cte},
      color_catalog AS (
        SELECT pc.id, pc.style_code, pc.product_code, pc.sku, pc.color_name, pc.color_hex,
               pc.main_image_url, pc.name, COUNT(psp.id) AS size_count,
               COUNT(*) FILTER (WHERE psp.stock=0) AS empty_size_count,
               COALESCE(SUM(psp.stock),0) AS stock,
               COALESCE(SUM(GREATEST(psp.stock,0)),0) AS available_stock,
               COALESCE(SUM(GREATEST(-psp.stock::bigint,0)),0) AS shortage_units,
               COUNT(*) FILTER (WHERE psp.stock<0) AS shortage_size_count,
               COALESCE(SUM(psp.contract_pending),0) AS contract_pending,
               COALESCE(SUM(psp.pending_inspection),0) AS pending_inspection,
               COALESCE(SUM(psp.pending_inbound),0) AS pending_inbound
        FROM product_catalog pc
        LEFT JOIN product_size_prices psp ON psp.product_id=pc.id
        {product_filter}
        GROUP BY pc.id,pc.style_code,pc.product_code,pc.sku,pc.color_name,pc.color_hex,pc.main_image_url,pc.name
      ),
      window_sales AS (
        SELECT pc.id, SUM(i.quantity) AS units, SUM(i.total_price) AS amount,
               COUNT(DISTINCT o.id) AS orders, MAX(o.created_at) AS last_sold_at
        FROM product_catalog pc JOIN order_items i ON i.product_id=pc.id JOIN orders o ON o.id=i.order_id
        WHERE {window_join}
        GROUP BY pc.id
      ),
      velocity_sales AS (
        SELECT pc.id, SUM(i.quantity) AS units
        FROM product_catalog pc JOIN order_items i ON i.product_id=pc.id JOIN orders o ON o.id=i.order_id
        WHERE {velocity_join}
        GROUP BY pc.id
      )
      SELECT c.id AS "productId", c.product_code AS "productCode", c.sku, c.color_name AS "colorName",
             c.color_hex AS "colorHex", c.main_image_url AS image, c.name, c.size_count AS "sizeCount",
             c.empty_size_count AS "emptySizeCount", c.stock, c.available_stock AS "availableStock", c.shortage_units AS "shortageUnits", c.shortage_size_count AS "shortageSizeCount", c.contract_pending AS "contractPending",
             c.pending_inspection AS "pendingInspection", c.pending_inbound AS "pendingInbound",
             COALESCE(w.units,0) AS units, COALESCE(w.amount,0) AS amount, COALESCE(w.orders,0) AS orders,
             COALESCE(v.units,0) AS "velocityUnits", w.last_sold_at AS "lastSoldAt",
             ROUND(COALESCE(v.units,0)::numeric / %s, 2) AS "averageDailyUnits",
             CASE WHEN COALESCE(v.units,0)=0 OR c.available_stock=0 THEN NULL
                  ELSE ROUND(c.available_stock::numeric / (v.units::numeric / %s), 1) END AS "estimatedDays"
      FROM color_catalog c
      LEFT JOIN window_sales w ON w.id=c.id
      LEFT JOIN velocity_sales v ON v.id=c.id
      ORDER BY c.id
    """
    params = [*catalog_params, *product_params, *window_params, *velocity_params, velocity_days, velocity_days]
    rows = db._fetch_all(sql, tuple(params))
    return rows, start, end, span, velocity_days


def style_detail(args):
    style_code = str(args.get('styleCode') or '').strip()
    if not style_code:
        raise ValueError('缺少款号')
    rows, start, end, span, velocity_days = _style_detail_rows(args, style_code)
    if not rows:
        raise LookupError('款号不存在')
    sizes_by_product = {}
    for size in _style_size_rows(args, style_code):
        sizes_by_product.setdefault(size['productId'], []).append(size)
    items = []
    for row in rows:
        item = _style_row(row)
        item['sizes'] = sizes_by_product.get(row['productId'], [])
        items.append(item)
    return {
        'styleCode': style_code,
        'items': items,
        'salesWindow': {'dateFrom': start.isoformat(), 'dateTo': end.isoformat(), 'days': span},
        'velocityWindow': {'days': velocity_days, 'dateFrom': (end - timedelta(days=velocity_days - 1)).isoformat(), 'dateTo': end.isoformat()},
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }


def _style_size_rows(args, style_code: str, product_id: int | None = None):
    start, end, span = _dashboard_window(args)
    velocity_days = int(args.get('velocityWindow', 7) or 7)
    if velocity_days not in {7, 30}:
        raise ValueError('周转计算窗口只支持近 7 天或近 30 天')
    window_join, window_params = _style_sales_join(args, start, end)
    velocity_join, velocity_params = _style_sales_join(args, start, end, days=velocity_days)
    catalog_cte, catalog_params = _style_catalog_parts(args, style_code)
    product_filter = ' WHERE p.id=%s' if product_id is not None else ''
    sql = f"""
      WITH {catalog_cte},
      window_sales AS (
        SELECT i.product_id, i.size_code, SUM(i.quantity) AS units, SUM(i.total_price) AS amount
        FROM product_catalog pc JOIN order_items i ON i.product_id=pc.id JOIN orders o ON o.id=i.order_id
        WHERE {window_join} GROUP BY i.product_id,i.size_code
      ),
      velocity_sales AS (
        SELECT i.product_id, i.size_code, SUM(i.quantity) AS units
        FROM product_catalog pc JOIN order_items i ON i.product_id=pc.id JOIN orders o ON o.id=i.order_id
        WHERE {velocity_join} GROUP BY i.product_id,i.size_code
      )
      SELECT p.id AS "productId", p.product_code AS "productCode", p.color_name AS "colorName",
             s.size_code AS "sizeCode", s.stock, GREATEST(s.stock,0) AS "availableStock", GREATEST(-s.stock::bigint,0) AS "shortageUnits", (s.stock<0)::int AS "shortageSizeCount", s.contract_pending AS "contractPending",
             s.pending_inspection AS "pendingInspection", s.pending_inbound AS "pendingInbound",
             COALESCE(w.units,0) AS units, COALESCE(w.amount,0) AS amount,
             COALESCE(v.units,0) AS "velocityUnits",
             ROUND(COALESCE(v.units,0)::numeric / %s, 2) AS "averageDailyUnits",
             CASE WHEN COALESCE(v.units,0)=0 OR s.stock<=0 THEN NULL
                  ELSE ROUND(s.stock::numeric / (v.units::numeric / %s), 1) END AS "estimatedDays"
      FROM product_catalog p
      JOIN product_size_prices s ON s.product_id=p.id
      LEFT JOIN window_sales w ON w.product_id=p.id AND w.size_code=s.size_code
      LEFT JOIN velocity_sales v ON v.product_id=p.id AND v.size_code=s.size_code
      {product_filter}
      ORDER BY p.id,s.sort_order,s.id
    """
    params = [*catalog_params, *window_params, *velocity_params, velocity_days, velocity_days]
    if product_id is not None:
        params.append(product_id)
    return [_style_row(row) for row in db._fetch_all(sql, tuple(params))]


def style_size_detail(args, style_code: str | None = None, product_id: int | None = None):
    style_code = style_code or str(args.get('styleCode') or '').strip()
    product_id = product_id or int(args.get('productId') or 0)
    if not style_code or product_id <= 0:
        raise ValueError('缺少款号或商品')
    start, end, span = _dashboard_window(args)
    return {
        'styleCode': style_code,
        'productId': product_id,
        'items': _style_size_rows(args, style_code, product_id),
        'salesWindow': {'dateFrom': start.isoformat(), 'dateTo': end.isoformat(), 'days': span},
    }


def migrate(cur):
    import contracts
    contracts.migrate(cur)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_order_requests (
          request_id UUID PRIMARY KEY, actor_id BIGINT NOT NULL, payload_hash TEXT NOT NULL,
          order_id BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS inventory_receipts (
          request_id UUID PRIMARY KEY, actor_id BIGINT NOT NULL, product_id BIGINT NOT NULL,
          request_hash TEXT NOT NULL, result JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS inventory_import_receipts (
          file_hash TEXT PRIMARY KEY, result JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS admin_audit_logs (
          id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          actor JSONB NOT NULL, module TEXT NOT NULL, action TEXT NOT NULL,
          entity_table TEXT NOT NULL, object_id TEXT NOT NULL, batch_id TEXT NOT NULL,
          before_data JSONB, after_data JSONB
        );
        CREATE INDEX IF NOT EXISTS idx_admin_audit_time ON admin_audit_logs (occurred_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_admin_audit_object ON admin_audit_logs (module, object_id);
        CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_products_updated_id ON products (updated_at DESC, id DESC);
        CREATE OR REPLACE FUNCTION capture_admin_audit() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE a text; old_data jsonb; new_data jsonb; obj text;
        BEGIN
          a := current_setting('gingtto.actor', true);
          IF a IS NULL OR a = '' THEN RETURN NULL; END IF;
          IF TG_OP <> 'INSERT' THEN old_data := to_jsonb(OLD); END IF;
          IF TG_OP <> 'DELETE' THEN new_data := to_jsonb(NEW); END IF;
          IF TG_OP = 'UPDATE' AND (old_data - 'updated_at') = (new_data - 'updated_at') THEN RETURN NULL; END IF;
          obj := COALESCE(new_data->>'product_id', old_data->>'product_id', new_data->>'category_id', old_data->>'category_id', new_data->>'id', old_data->>'id');
          IF TG_TABLE_NAME = 'products' THEN obj := COALESCE(new_data->>'id',old_data->>'id'); END IF;
          IF TG_TABLE_NAME = 'order_items' THEN obj := COALESCE(new_data->>'order_id', old_data->>'order_id'); END IF;
          IF COALESCE(old_data->>'password_hash','') IS DISTINCT FROM COALESCE(new_data->>'password_hash','') AND TG_OP <> 'DELETE' THEN
            new_data := new_data || '{"passwordChanged":true}'::jsonb;
          END IF;
          old_data := old_data - ARRAY['password_hash','token','payment_link','contact_email','phone','shipping_address','address_line1','postal_code'];
          new_data := new_data - ARRAY['password_hash','token','payment_link','contact_email','phone','shipping_address','address_line1','postal_code'];
          INSERT INTO admin_audit_logs(actor,module,action,entity_table,object_id,batch_id,before_data,after_data)
          VALUES(a::jsonb,current_setting('gingtto.module',true),TG_OP,TG_TABLE_NAME,obj,
            current_setting('gingtto.batch',true),old_data,new_data);
          RETURN NULL;
        END $$;
    """)
    for table in ['products', 'product_size_prices', 'product_translations', 'product_images',
                  'product_sizes', 'orders', 'order_items', 'homepage_configs', 'product_categories',
                  'product_category_translations', 'admin_users', 'store_users', 'banners', 'purchase_contracts']:
        cur.execute(f'DROP TRIGGER IF EXISTS admin_audit ON {table}')
        cur.execute(f'CREATE TRIGGER admin_audit AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION capture_admin_audit()')


class Conflict(Exception):
    pass


def version(table, object_id):
    row = db._fetch_one(f'SELECT updated_at::text AS version FROM {table} WHERE id=%s', (object_id,))
    return row['version'] if row else 'missing'


def check_versions(payload):
    path = request.path.split('/')
    module = 'home-config' if path[3] == 'activity-config' else path[3]
    if module not in {'products', 'inventory', 'orders', 'home-config'}:
        return
    table = {'products': 'products', 'inventory': 'products', 'orders': 'orders', 'home-config': 'homepage_configs'}[module]
    expected = payload.get('versions', {})
    if 'version' in payload:
        object_id = 1 if module == 'home-config' else int(path[4])
        expected = {str(object_id): payload['version']}
    if not isinstance(expected, dict):
        raise ValueError('无效的版本信息')
    if module == 'home-config':
        db._fetch_one('SELECT pg_advisory_xact_lock(7192026)')
    for object_id, previous in sorted(expected.items(), key=lambda pair: int(pair[0])):
        row = db._fetch_one(f'SELECT updated_at::text AS version FROM {table} WHERE id=%s FOR UPDATE', (int(object_id),))
        current = row['version'] if row else 'missing'
        if previous != current:
            raise Conflict('数据已被其他操作更新。当前草稿已保留，请读取最新数据并核对后保存。')


def atomic_admin_call(func, args, kwargs):
    """All helpers and audit triggers commit together, including legacy multi-step routes."""
    with db._connect() as conn:
        token = db.REQUEST_CONNECTION.set(conn)
        try:
            actor = {key: g.current_user.get(key) for key in ('id', 'name', 'role')}
            for key, value in {'actor': json.dumps(actor), 'module': request.path.split('/')[3], 'batch': str(uuid.uuid4())}.items():
                conn.execute('SELECT set_config(%s,%s,true)', (f'gingtto.{key}', value))
            if request.path.split('/')[3] == 'admin-users':
                conn.execute('SELECT pg_advisory_xact_lock(7192027)')
            if not request.path.endswith('/receive'):
                check_versions(request.get_json(silent=True) or {})
            response = make_response(func(*args, **kwargs))
            if response.status_code >= 400:
                conn.rollback()
            else:
                conn.commit()
            return response
        except Conflict as exc:
            conn.rollback()
            return jsonify({'message': str(exc), 'code': 'version_conflict'}), 409
        except ValueError as exc:
            conn.rollback()
            return jsonify({'message': str(exc)}), 400
        finally:
            db.REQUEST_CONNECTION.reset(token)


def snapshot_admin_call(func, args, kwargs):
    """Keep detail fields and their edit version in one MVCC snapshot."""
    with db._connect() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        token = db.REQUEST_CONNECTION.set(conn)
        try:
            return func(*args, **kwargs)
        finally:
            db.REQUEST_CONNECTION.reset(token)


def paging(args):
    page, size = int(args.get('page', 1)), int(args.get('pageSize', 25))
    if page < 1 or size not in {25, 50, 100}:
        raise ValueError('分页参数无效')
    return page, size


def product_where(args, include_inactive=False):
    conditions, params = ['(p.is_active=TRUE OR EXISTS(SELECT 1 FROM product_size_prices debt WHERE debt.product_id=p.id AND (debt.stock<0 OR debt.contract_pending>0 OR debt.pending_inspection>0 OR debt.pending_inbound>0)))' if include_inactive else 'p.is_active=TRUE'], []
    if args.get('category') and args['category'] != 'all':
        conditions.append('pc.category_key=%s'); params.append(args['category'])
    if args.get('keyword'):
        conditions.append("(concat_ws(' ',p.sku,p.product_code,p.color_name,p.color_group) ILIKE %s OR EXISTS (SELECT 1 FROM product_translations t WHERE t.product_id=p.id AND t.name ILIKE %s))")
        params.extend([f"%{args['keyword']}%"] * 2)
    if args.get('stock') in {'available', 'empty'}:
        conditions.append(inventory_policy.available_sql('p') + (' > 0' if args['stock'] == 'available' else ' = 0'))
    if args.get('stock') == 'backordered':
        if getattr(g, 'current_user', {}).get('role') == 'customer':
            raise ValueError('不支持此库存筛选')
        conditions.append('EXISTS(SELECT 1 FROM product_size_prices debt WHERE debt.product_id=p.id AND debt.stock<0)')
    if args.get('featured') in {'true', 'false'}:
        conditions.append('p.featured=%s'); params.append(args['featured'] == 'true')
    if args.get('ids'):
        ids = [int(value) for value in args['ids'].split(',') if value]
        conditions.append('p.id=ANY(%s)'); params.append(ids)
    if args.get('colorGroup'):
        conditions.append('p.color_group=%s'); params.append(args['colorGroup'])
    return ' AND '.join(conditions), params


def products_page(args, pending=False):
    page, size = paging(args)
    where, params = product_where(args, include_inactive=pending)
    base = ' FROM products p JOIN product_categories pc ON pc.id=p.category_id WHERE ' + where
    summary = db._fetch_one('SELECT COUNT(*) AS total,COALESCE(SUM(p.stock),0) AS stock,COALESCE(SUM(' + inventory_policy.available_sql('p') + '),0) AS available_stock' + base, tuple(params))
    sizes = db._fetch_one('SELECT COALESCE(SUM(GREATEST(-s.stock::bigint,0)),0) AS shortage_units,COUNT(*) FILTER(WHERE s.stock<0) AS shortage_sizes,COALESCE(SUM(s.contract_pending),0) AS pending,COALESCE(SUM(s.pending_inbound),0) AS inbound,COALESCE(SUM(s.pending_inspection),0) AS inspection,COUNT(*) FILTER(WHERE s.stock=0) AS empty FROM product_size_prices s JOIN products p ON p.id=s.product_id JOIN product_categories pc ON pc.id=p.category_id WHERE '+where, tuple(params))
    sorts = {'id': 'p.id', 'stock': 'p.stock', 'price': 'p.price', 'updatedAt': 'p.updated_at', 'sku': 'p.sku'}
    order = sorts.get(args.get('sort'), 'p.updated_at')
    direction = 'ASC' if args.get('direction') == 'asc' else 'DESC'
    if args.get('sort') == 'configured' and args.get('ids'):
        order = 'array_position(ARRAY[' + ','.join(str(int(v)) for v in args['ids'].split(',') if v) + ']::bigint[], p.id)'
        direction = 'ASC'
    rows = db._fetch_all(db._product_base_query().replace('p.id,', 'p.id,p.updated_at::text AS version,') +
                        f' WHERE {where} ORDER BY {order} {direction},p.id DESC LIMIT %s OFFSET %s',
                        tuple(['zh', *params, size, (page-1)*size]))
    items = db._build_product_result(rows, include_contract_pending=pending)
    for item, row in zip(items, rows):
        item.update(version=row['version'], updatedAt=row['version'])
    totals = {'stock': int(summary['stock']), 'availableStock': int(summary['available_stock']), 'shortageUnits': int(sizes['shortage_units']), 'shortageSizeCount': int(sizes['shortage_sizes']), 'zeroSizes': sizes['empty']}
    if pending:
        totals['contractPending'] = int(sizes['pending'])
        totals['pendingInbound'] = int(sizes['inbound'])
        totals['pendingInspection'] = int(sizes['inspection'])
    return {'items': items, 'total': summary['total'], 'page': page, 'pageSize': size, 'summary': totals}


def product_detail(product_id, pending=False):
    item = db.get_product_by_id(product_id, include_contract_pending=pending, include_inactive=pending)
    if item:
        item['version'] = version('products', product_id)
        item['updatedAt'] = item['version']
    return item


def products_for_export(args):
    where, params = product_where(args, include_inactive=True)
    rows = db._fetch_all(db._product_base_query()+' WHERE '+where+' ORDER BY p.id',tuple(['zh',*params]))
    return db._build_product_result(rows,include_contract_pending=True)


def receive_inventory(product_id, payload):
    request_id = str(uuid.UUID(str(payload.get('requestId',''))))
    if not payload.get('version'):
        raise ValueError('请重新读取商品后再入库')
    actor_id = g.current_user['id']
    request_hash = hashlib.sha256(json.dumps({'productId':product_id,'version':payload['version']},sort_keys=True).encode()).hexdigest()
    db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (request_id,))
    existing = db._fetch_one('SELECT * FROM inventory_receipts WHERE request_id=%s', (request_id,))
    if existing:
        if existing['actor_id'] != actor_id or existing['request_hash'] != request_hash:
            raise ValueError('此入库请求编号已用于其他操作')
        return {**existing['result'], 'replayed':True}
    check_versions(payload)
    item = db._fetch_one('SELECT id FROM products WHERE id=%s FOR UPDATE',(product_id,))
    if not item:
        raise ValueError('商品不存在')
    rows = db._fetch_all('SELECT size_code,stock,contract_pending,pending_inbound FROM product_size_prices WHERE product_id=%s ORDER BY size_code FOR UPDATE',(product_id,))
    for row in rows:
        inventory_policy.parse_stock(row['stock'] + row['pending_inbound'])
    if not -2147483648 <= sum(row['stock'] + row['pending_inbound'] for row in rows) <= 2147483647:
        raise ValueError('入库后的库存总数超出允许范围')
    changes=[]
    for row in rows:
        amount=row['pending_inbound']
        if not amount:
            continue
        db._fetch_one('UPDATE product_size_prices SET stock=stock+pending_inbound,pending_inbound=0 WHERE product_id=%s AND size_code=%s RETURNING id',(product_id,row['size_code']))
        changes.append({'sizeCode':row['size_code'],'quantity':amount,'stockBefore':row['stock'],'stockAfter':row['stock']+amount,'contractBefore':row['contract_pending'],'contractAfter':row['contract_pending']})
    if changes:
        db._fetch_one('UPDATE products SET stock=(SELECT COALESCE(SUM(stock),0) FROM product_size_prices WHERE product_id=%s),updated_at=NOW() WHERE id=%s RETURNING id',(product_id,product_id))
    result={'receivedUnits':sum(row['quantity'] for row in changes),'receivedSizes':len(changes),'changes':changes,'productId':product_id}
    db._fetch_one('INSERT INTO inventory_receipts(request_id,actor_id,product_id,request_hash,result) VALUES(%s,%s,%s,%s,%s) RETURNING request_id',(request_id,actor_id,product_id,request_hash,Jsonb(result)))
    return result


def order_where(args, status=True, owner_id=None):
    where, params = ['TRUE'], []
    if owner_id is not None:
        where.append('o.created_by_admin_id=%s'); params.append(owner_id)
    if status and args.get('status') not in {None, '', 'all'}:
        where.append('o.status=%s'); params.append(args['status'])
    if args.get('keyword'):
        where.append("concat_ws(' ',o.order_no,su.name,su.email,su.company_name,o.tracking_no) ILIKE %s")
        params.append(f"%{args['keyword']}%")
    if args.get('country') not in {None, '', 'all'}:
        where.append('o.country=%s'); params.append(args['country'])
    product_conditions = []
    if args.get('category') not in {None, '', 'all'}:
        product_conditions.append('c.category_key=%s')
        params.append(args['category'])
    if args.get('style') not in {None, '', 'all'}:
        product_conditions.append(f"({_style_code_sql('p')}=%s OR COALESCE(NULLIF(p.product_code,''),i.sku)=%s)")
        params.extend([args['style']] * 2)
    if product_conditions:
        where.append('EXISTS(SELECT 1 FROM order_items i JOIN products p ON p.id=i.product_id '
                     'JOIN product_categories c ON c.id=p.category_id WHERE i.order_id=o.id AND '
                     + ' AND '.join(product_conditions) + ')')
    for field, op, extra in [('dateFrom', '>=', 0), ('dateTo', '<', 1)]:
        if args.get(field):
            day = date.fromisoformat(args[field]) + timedelta(days=extra)
            where.append(f'o.created_at {op} %s'); params.append(datetime.combine(day, datetime.min.time(), SHANGHAI))
    if args.get('orderIds'):
        where.append('o.id=ANY(%s)'); params.append([int(x) for x in args['orderIds'].split(',') if x])
    return ' AND '.join(where), params


def order_ids(args, limit=None, offset=0, status=True, owner_id=None):
    where, params = order_where(args, status, owner_id)
    sort = {'createdAt': 'o.created_at', 'totalAmount': 'o.total_amount', 'id': 'o.id'}.get(args.get('sort'), 'o.created_at')
    direction = 'ASC' if args.get('direction') == 'asc' else 'DESC'
    query = f'SELECT o.id FROM orders o JOIN store_users su ON su.id=o.store_user_id WHERE {where} ORDER BY {sort} {direction},o.id DESC'
    if limit is not None:
        query += ' LIMIT %s OFFSET %s'; params.extend([limit, offset])
    return [row['id'] for row in db._fetch_all(query, tuple(params))]


def orders_page(args, owner_id=None):
    page, size = paging(args)
    where, params = order_where(args, status=False, owner_id=owner_id)
    counts = db._fetch_all('SELECT o.status,COUNT(*) AS count FROM orders o JOIN store_users su ON su.id=o.store_user_id WHERE '+where+' GROUP BY o.status', tuple(params))
    status_counts = {row['status']: row['count'] for row in counts}
    total = status_counts.get(args['status'], 0) if args.get('status') not in {None,'','all'} else sum(status_counts.values())
    ids = order_ids(args, size, (page-1)*size, owner_id=owner_id)
    items = db.list_orders(order_ids=ids)
    positions = {v:i for i,v in enumerate(ids)}
    items.sort(key=lambda item: positions[item['id']])
    for item in items:
        item['version'] = version('orders', item['id'])
        item['goodsAmount'] = round(sum(float(row['totalPrice']) for row in item['items']), 2)
    return {'items': items, 'total': total, 'page': page, 'pageSize': size, 'statusCounts': status_counts}


def users_page(args, admin=False):
    page, size = paging(args)
    table = 'admin_users' if admin else 'store_users'
    where, params = ['TRUE'], []
    if args.get('keyword'):
        fields = "concat_ws(' ',name,email)" if admin else "concat_ws(' ',name,email,company_name)"
        where.append(fields+' ILIKE %s'); params.append('%'+args['keyword']+'%')
    for field in (['status', 'role'] if admin else ['status']):
        if args.get(field):
            where.append(f'{field}=%s'); params.append(args[field])
    clause = ' AND '.join(where)
    total = db._fetch_one(f'SELECT COUNT(*) AS total FROM {table} WHERE {clause}', tuple(params))['total']
    sort = {'name':'name', 'createdAt':'created_at', 'id':'id'}.get(args.get('sort'), 'id')
    direction = 'ASC' if args.get('direction') == 'asc' else 'DESC'
    fields = 'id,name,email,status,created_at,' + ('role,permissions' if admin else 'company_name')
    rows = db._fetch_all(f'SELECT {fields} FROM {table} WHERE {clause} ORDER BY {sort} {direction},id LIMIT %s OFFSET %s', tuple([*params,size,(page-1)*size]))
    items = [db._build_user_dict(row, include_password_hash=False, company_name=not admin) for row in rows]
    return {'items':items,'total':total,'page':page,'pageSize':size}


def audit_page(args):
    page, size = paging(args)
    where, params = ['TRUE'], []
    for key, expression in [('module','module'),('action','action'),('objectId','object_id'),('batchId','batch_id')]:
        if args.get(key):
            where.append(expression+'=%s'); params.append(args[key])
    if args.get('keyword'):
        where.append("(actor->>'name' ILIKE %s OR object_id ILIKE %s)"); params.extend(['%'+args['keyword']+'%']*2)
    for field, op, extra in [('dateFrom','>=',0),('dateTo','<',1)]:
        if args.get(field):
            where.append(f'occurred_at {op} %s'); params.append(datetime.combine(date.fromisoformat(args[field])+timedelta(days=extra),datetime.min.time(),SHANGHAI))
    clause=' AND '.join(where)
    total=db._fetch_one('SELECT COUNT(*) AS total FROM admin_audit_logs WHERE '+clause,tuple(params))['total']
    rows=db._fetch_all('SELECT id,occurred_at,actor,module,action,entity_table,object_id,batch_id FROM admin_audit_logs WHERE '+clause+' ORDER BY occurred_at DESC,id DESC LIMIT %s OFFSET %s',tuple([*params,size,(page-1)*size]))
    return {'items':[serialize_audit(row) for row in rows], 'total':total,'page':page,'pageSize':size}


def serialize_audit(row):
    return {('occurredAt' if k=='occurred_at' else 'objectId' if k=='object_id' else 'batchId' if k=='batch_id' else 'entityTable' if k=='entity_table' else 'before' if k=='before_data' else 'after' if k=='after_data' else k):
            (db._iso(v) if isinstance(v,datetime) else v) for k,v in row.items()}


def dashboard(args):
    end=date.fromisoformat(args.get('dateTo') or datetime.now(SHANGHAI).date().isoformat())
    start=date.fromisoformat(args.get('dateFrom') or (end-timedelta(days=29)).isoformat())
    if start>end:
        raise ValueError('开始日期不能晚于结束日期')
    if (end-start).days>1095:
        raise ValueError('查询时间不能超过三年')
    span=(end-start).days+1
    def period(a,b):
        where, params=order_where({**dict(args),'dateFrom':a.isoformat(),'dateTo':b.isoformat()})
        line_clause=''
        if args.get('style') not in {None,'','all'}:
            line_clause += f" AND ({_style_code_sql('p')}=%s OR COALESCE(NULLIF(p.product_code,''),i.sku)=%s)"
            params.extend([args['style']] * 2)
        if args.get('category') not in {None,'','all'}:
            line_clause += ' AND EXISTS(SELECT 1 FROM product_categories c WHERE c.id=p.category_id AND c.category_key=%s)'
            params.append(args['category'])
        base=f''' FROM orders o JOIN store_users su ON su.id=o.store_user_id JOIN order_items i ON i.order_id=o.id
                  JOIN products p ON p.id=i.product_id WHERE {where} AND o.status <> 'cancelled' {line_clause}'''
        metrics=db._fetch_one('SELECT COUNT(DISTINCT o.id) AS orders,COUNT(DISTINCT o.store_user_id) AS customers,COALESCE(SUM(i.quantity),0) AS units,COALESCE(SUM(i.total_price),0) AS amount'+base,tuple(params))
        metrics={k:float(v) if isinstance(v,Decimal) else v for k,v in metrics.items()}
        metrics['average']=round(metrics['amount']/metrics['orders'],2) if metrics['orders'] else 0
        return base,params,metrics
    base,params,metrics=period(start,end)
    _,_,previous=period(start-timedelta(days=span),start-timedelta(days=1))
    trend=db._fetch_all("SELECT (o.created_at AT TIME ZONE 'Asia/Shanghai')::date AS day,COUNT(DISTINCT o.id) AS orders,SUM(i.total_price) AS amount"+base+' GROUP BY day ORDER BY day',tuple(params))
    indexed={row['day']:row for row in trend}
    points=[{'date':(d:=start+timedelta(days=n)).isoformat(),'orders':indexed.get(d,{}).get('orders',0),'amount':float(indexed.get(d,{}).get('amount',0))} for n in range(span)]
    top=db._fetch_all("SELECT COALESCE(NULLIF(p.product_code,''),i.sku) AS sku,MAX(i.product_name) AS name,SUM(i.quantity) AS units,SUM(i.total_price) AS amount"+base+' GROUP BY 1 ORDER BY units DESC,sku LIMIT 10',tuple(params))
    top_amount=db._fetch_all("SELECT COALESCE(NULLIF(p.product_code,''),i.sku) AS sku,MAX(i.product_name) AS name,SUM(i.quantity) AS units,SUM(i.total_price) AS amount"+base+' GROUP BY 1 ORDER BY amount DESC,sku LIMIT 10',tuple(params))
    countries=db._fetch_all("SELECT COALESCE(NULLIF(o.country,''),'未填写') AS country,COUNT(DISTINCT o.id) AS orders,SUM(i.total_price) AS amount"+base+' GROUP BY 1 ORDER BY orders DESC,country',tuple(params))
    global_counts=db._fetch_all('SELECT status,COUNT(*) AS count FROM orders GROUP BY status')
    inventory=db._fetch_one('SELECT COALESCE(SUM(s.stock),0) AS stock,COALESCE(SUM(GREATEST(s.stock,0)),0) AS "availableStock",COALESCE(SUM(GREATEST(-s.stock::bigint,0)),0) AS "shortageUnits",COUNT(*) FILTER(WHERE s.stock<0) AS "shortageSizeCount",COALESCE(SUM(s.contract_pending),0) AS pending,COALESCE(SUM(s.pending_inspection),0) AS inspection,COALESCE(SUM(s.pending_inbound),0) AS inbound,COUNT(*) FILTER(WHERE s.stock=0) AS empty FROM product_size_prices s JOIN products p ON p.id=s.product_id WHERE p.is_active=TRUE OR EXISTS(SELECT 1 FROM product_size_prices debt WHERE debt.product_id=p.id AND (debt.stock<0 OR debt.contract_pending>0 OR debt.pending_inspection>0 OR debt.pending_inbound>0))')
    filtered_counts=orders_page({**dict(args),'dateFrom':start.isoformat(),'dateTo':end.isoformat(),'page':1,'pageSize':25})
    return {'metrics':metrics,'previous':previous,'trend':points,
            'topProducts':[{**r,'amount':float(r['amount'])} for r in top],
            'topProductsByAmount':[{**r,'amount':float(r['amount'])} for r in top_amount],
            'countries':[{**r,'amount':float(r['amount'])} for r in countries],
            'recentOrders':filtered_counts['items'][:5],'statusCounts':filtered_counts['statusCounts'],
            'snapshot':{**{k:int(v) for k,v in inventory.items()},'statuses':{r['status']:r['count'] for r in global_counts}},
            'filters':{'countries':[r['country'] for r in db._fetch_all("SELECT DISTINCT country FROM orders WHERE country IS NOT NULL ORDER BY country")],
                       'styles':[r['style'] for r in db._fetch_all(f"SELECT DISTINCT {_style_code_sql('p')} AS style FROM products p WHERE p.is_active=TRUE ORDER BY style")],
                       'categories':[dict(r) for r in db._fetch_all("SELECT pc.category_key AS key,COALESCE(NULLIF(pct.label,''),pc.category_key) AS label FROM product_categories pc LEFT JOIN product_category_translations pct ON pct.category_id=pc.id AND pct.lang_code='zh' WHERE pc.is_active=TRUE ORDER BY label")]},
            'dateFrom':start.isoformat(),'dateTo':end.isoformat(),'updatedAt':datetime.now(timezone.utc).isoformat()}
