"""Optional per-real-size net weights, and exact current-weight presentation."""
import re

MAX_WEIGHT_GRAMS = 2147483647


def parse(value, label='单件净重'):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f'{label}须为正整数克，或留空')
    if isinstance(value, str) and not re.fullmatch(r'[0-9]+', value.strip()):
        raise ValueError(f'{label}须为正整数克，或留空')
    number = int(value)
    if not 1 <= number <= MAX_WEIGHT_GRAMS:
        raise ValueError(f'{label}须在 1–{MAX_WEIGHT_GRAMS} 克之间')
    return number


def migrate(cur):
    # Serialize the identical migration run by either producer; never backfill.
    cur.execute('SELECT pg_advisory_xact_lock(7192043)')
    cur.execute('ALTER TABLE product_size_prices ADD COLUMN IF NOT EXISTS weight_grams INTEGER')
    cur.execute("SELECT 1 FROM pg_constraint WHERE conrelid='product_size_prices'::regclass AND conname='product_size_prices_weight_positive'")
    if not cur.fetchone():
        cur.execute('ALTER TABLE product_size_prices ADD CONSTRAINT product_size_prices_weight_positive CHECK (weight_grams IS NULL OR weight_grams > 0)')


def summary(items):
    known, missing = 0, 0
    for item in items:
        weight, quantity = item.get('unitWeightGrams'), int(item.get('quantity') or 0)
        if weight is None:
            missing += quantity
        else:
            known += int(weight) * quantity
    complete = bool(items) and missing == 0
    # Strings retain exact grams even beyond JavaScript's safe-integer range.
    return {'knownWeightGrams': str(known), 'totalWeightGrams': str(known) if complete else None,
            'missingWeightQuantity': missing, 'weightStatus': 'complete' if complete else 'incomplete'}


def kilograms(grams):
    number = int(grams)
    return f'{number // 1000:,}.{number % 1000:03d}'


def description(order, *, english=False):
    values = summary(order.get('items') or []) if 'knownWeightGrams' not in order else order
    known, missing = int(values['knownWeightGrams']), int(values['missingWeightQuantity'])
    if values.get('totalWeightGrams') is not None:
        return (f"Net Weight: {kilograms(known)} kg (current product weights; excluding packaging)" if english
                else f"商品净重：{kilograms(known)} kg（按当前商品重量计算，不含包装）")
    if known:
        return (f"Known Net Weight: {kilograms(known)} kg; {missing} pcs missing weight (excluding packaging)" if english
                else f"已知净重：{kilograms(known)} kg，另有 {missing} 件未设置重量（不含包装）")
    return (f'Net Weight: Not set ({missing} pcs missing weight)' if english
            else f'商品净重：未设置（{missing} 件未设置重量）')
