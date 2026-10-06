"""Category priority shared by every catalog presentation."""
CATEGORY_ORDER_LOCK = 7192043


def category_sql(alias='pc'):
    return f'{alias}.sort_order ASC, {alias}.id ASC'


def arrange_config(config, products, categories):
    product_ranks = {row['id']: (row['sort_order'], row['category_id']) for row in products}
    category_ranks = {row['category_key']: (row['sort_order'], row['id']) for row in categories}
    last = (2147483648, 9223372036854775807)
    for field in ('sectionProductIds', 'collectionProductIds'):
        config[field] = {key: sorted(ids, key=lambda pid: product_ranks.get(pid, last))
                         for key, ids in config[field].items()}
    config['displayCategoryKeys'] = sorted(config['displayCategoryKeys'], key=lambda key: category_ranks.get(key, last))
    return config
