"""Internal style picker and versioned curation; uses the request transaction."""
import db
import inventory_policy
import style_catalog
from psycopg.types.json import Jsonb
from workbench import Conflict


def catalog():
    code = style_catalog.style_sql('p')
    rows = db._fetch_all(f"""WITH all_styles AS (
      SELECT p.*, {code} AS canonical_style,
        MIN(p.created_at) OVER(PARTITION BY {code}) AS first_listed_at,
        MIN(p.id) OVER(PARTITION BY {code}) AS first_product_id FROM products p)
      SELECT p.id,p.slug,p.sku,p.product_code,p.color_name,p.main_image_url,p.is_active,
        p.canonical_style,p.first_listed_at,p.first_product_id,p.price,
        pc.category_key,COALESCE(ct.label,pc.category_key) AS category_label,
        COALESCE(NULLIF(pt.name,''),NULLIF(pte.name,''),p.product_code,p.sku) AS name,
        {inventory_policy.available_sql('p')} AS stock,
        COALESCE((SELECT jsonb_agg(size_code ORDER BY sort_order,id) FROM product_size_prices s WHERE s.product_id=p.id),'[]') AS sizes
      FROM all_styles p JOIN product_categories pc ON pc.id=p.category_id
      LEFT JOIN product_translations pt ON pt.product_id=p.id AND pt.lang_code='zh'
      LEFT JOIN product_translations pte ON pte.product_id=p.id AND pte.lang_code='en'
      LEFT JOIN product_category_translations ct ON ct.category_id=pc.id AND ct.lang_code='zh'
      ORDER BY p.id""")
    variants = [{'id': r['id'], 'styleCode': r['canonical_style'], 'firstListedAt': db._iso(r['first_listed_at']),
        'firstProductId': r['first_product_id'], 'sku': r['sku'], 'productCode': r['product_code'],
        'slug': r['slug'], 'name': r['name'], 'image': r['main_image_url'], 'colorName': r['color_name'],
        'active': r['is_active'], 'categoryKey': r['category_key'], 'categoryLabel': r['category_label'],
        'sizes': r['sizes'], 'price': float(r['price']), 'stock': int(r['stock'])} for r in rows]
    items = style_catalog.group_variants(variants)
    for item in items:
        item['active'] = any(v['active'] for v in item['variants'])
    return items


def get_config():
    return style_catalog.config(db._fetch_one('SELECT * FROM presale_configs WHERE id=1'))


def save_config(body):
    if not isinstance(body, dict) or set(body)-{'styleCodes','sortMode','version'}:
        raise ValueError('预售配置格式错误')
    codes, mode, version = body.get('styleCodes'), body.get('sortMode'), body.get('version')
    if (not isinstance(codes, list) or len(codes)>5000 or
        any(not isinstance(c,str) or not c.strip() or c!=c.strip() or len(c)>160 for c in codes) or len(set(codes))!=len(codes)):
        raise ValueError('请选择不重复的有效款号（最多 5000 款）')
    if mode not in {'automatic','manual'} or type(version) is not int or version<0:
        raise ValueError('排序模式或版本无效')
    previous = db._fetch_one('SELECT * FROM presale_configs WHERE id=1 FOR UPDATE')
    if previous['version'] != version: raise Conflict('预售配置已被其他人更新；草稿已保留，请读取最新配置后核对。')
    valid = {g['styleCode'] for g in catalog()}
    # Old references stay visible until explicitly removed/reselected, never silently reassigned.
    if set(codes)-valid-set(previous['style_codes']): raise ValueError('部分款号已变更，请重新选择')
    row = db._fetch_one('UPDATE presale_configs SET style_codes=%s,sort_mode=%s,version=version+1,updated_at=clock_timestamp() WHERE id=1 RETURNING *',
                        (Jsonb(codes),mode))
    return style_catalog.config(row)
