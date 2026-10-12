"""Canonical style identity and additive presale schema, mirrored in both services."""
import re
from decimal import Decimal


def style_code(product_code='', color_group='', sku='', explicit=''):
    if str(explicit or '').strip():
        return str(explicit).strip()
    code = str(product_code or sku or '').strip()
    group = str(color_group or '').strip()
    if group and group.casefold() != code.casefold():
        return group
    return re.sub(r'[-_－][^-_－]+$', '', code) or code


def style_sql(alias='p'):
    return f"""COALESCE(NULLIF(BTRIM({alias}.style_code),''),
      CASE WHEN NULLIF(BTRIM({alias}.color_group),'') IS NOT NULL
        AND LOWER(BTRIM({alias}.color_group))<>LOWER(BTRIM({alias}.product_code))
      THEN BTRIM({alias}.color_group)
      ELSE COALESCE(NULLIF(regexp_replace(BTRIM(COALESCE(NULLIF({alias}.product_code,''),NULLIF({alias}.sku,''))),
        '[-_－][^-_－]+$',''),''),NULLIF(BTRIM({alias}.product_code),''),NULLIF(BTRIM({alias}.sku),''),'未归类') END)"""


def migrate(cur):
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS style_code VARCHAR(160) NOT NULL DEFAULT ''")
    cur.execute("""CREATE TABLE IF NOT EXISTS presale_configs (
      id SMALLINT PRIMARY KEY DEFAULT 1 CHECK(id=1),
      style_codes JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(style_codes)='array'),
      sort_mode TEXT NOT NULL DEFAULT 'automatic' CHECK(sort_mode IN ('automatic','manual')),
      version BIGINT NOT NULL DEFAULT 0 CHECK(version>=0),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
      INSERT INTO presale_configs(id) VALUES(1) ON CONFLICT DO NOTHING;""")


def config(row):
    return {'styleCodes': list(row['style_codes']), 'sortMode': row['sort_mode'], 'version': row['version']}


def chronological(items):
    return sorted(items, key=lambda item: (item['firstListedAt'], item['firstProductId']), reverse=True)


def group_variants(variants):
    groups = {}
    for variant in variants:
        code = variant['styleCode']
        group = groups.setdefault(code, {'styleCode': code, 'name': variant['name'],
            'summary': variant.get('summary', ''), 'firstListedAt': variant['firstListedAt'],
            'firstProductId': variant['firstProductId'], 'sizeCodes': [], 'categoryKeys': [], 'variants': []})
        group['variants'].append(variant)
        for size in variant.get('sizes', []):
            if size not in group['sizeCodes']: group['sizeCodes'].append(size)
        if variant['categoryKey'] not in group['categoryKeys']: group['categoryKeys'].append(variant['categoryKey'])
    for group in groups.values():
        prices = [Decimal(str(s['price'])) for v in group['variants']
                  for s in (v.get('sizePrices') or [{'price': v['price']}])]
        group['priceRange'] = {'min': float(min(prices)), 'max': float(max(prices))}
    return chronological(list(groups.values()))


def filter_groups(items, *, keyword='', category='', stock_only=False):
    keyword = str(keyword).strip().casefold()
    def matches(group):
        if category and category not in group['categoryKeys']: return False
        if stock_only and not any(v['stock'] > 0 for v in group['variants']): return False
        text = ' '.join(str(v.get(k) or '') for v in group['variants'] for k in
                        ('name','summary','sku','productCode','colorName','categoryLabel'))
        return not keyword or keyword in (group['styleCode']+' '+text).casefold()
    return [g for g in items if matches(g)]


def presale_groups(items, settings):
    chosen = set(settings['styleCodes'])
    selected = [g for g in items if g['styleCode'] in chosen]
    if settings['sortMode'] == 'manual':
        order = {code: index for index, code in enumerate(settings['styleCodes'])}
        selected.sort(key=lambda g: order[g['styleCode']])
    return selected
