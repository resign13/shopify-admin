"""Exact order-currency arithmetic, independent from finance cost permissions."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

CENT = Decimal('0.01')
MAX_AMOUNT = Decimal('9999999999.99')
CURRENCIES = ('USD', 'CNY')


def migrate(cur):
    cur.execute("""ALTER TABLE orders ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NOT NULL DEFAULT 'USD';
      ALTER TABLE orders ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(16,6);
      ALTER TABLE order_items ADD COLUMN IF NOT EXISTS price_source TEXT NOT NULL DEFAULT 'legacy';
      ALTER TABLE order_items ADD COLUMN IF NOT EXISTS reference_price_usd NUMERIC(12,2);
      DO $$ BEGIN
        IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='orders_currency_valid' AND conrelid='orders'::regclass) THEN
          ALTER TABLE orders ADD CONSTRAINT orders_currency_valid CHECK(currency IN ('USD','CNY'));
          ALTER TABLE orders ADD CONSTRAINT orders_exchange_rate_valid CHECK(
            (exchange_rate IS NULL OR exchange_rate>0) AND (currency='USD' OR exchange_rate IS NOT NULL));
        END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='order_items_price_source_valid' AND conrelid='order_items'::regclass) THEN
          ALTER TABLE order_items ADD CONSTRAINT order_items_price_source_valid CHECK(price_source IN ('legacy','catalog','manual'));
          ALTER TABLE order_items ADD CONSTRAINT order_items_reference_valid CHECK(reference_price_usd IS NULL OR reference_price_usd>=0);
        END IF;
      END $$;""")


def decimal(value, label, *, rate=False):
    if value is None or isinstance(value, bool) or str(value).strip() == '':
        raise ValueError(f'请填写有效{label}')
    try:
        result = Decimal(str(value))
        unit = Decimal('.000001') if rate else CENT
        if (not result.is_finite() or result < 0 or (rate and result == 0)
                or result > MAX_AMOUNT or result != result.quantize(unit)):
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise ValueError(f'{label}须为'+('正数，最多六位小数' if rate else '非负金额，最多两位小数'))
    return result


def terms(payload, old=None, *, draft=False):
    old = old or {}
    currency = payload.get('currency', old.get('currency') or 'USD')
    if currency not in CURRENCIES:
        raise ValueError('订单币种仅支持 USD 或 CNY')
    value = payload.get('exchangeRate', old.get('exchange_rate'))
    rate = None if value in (None, '') else decimal(value, '本单汇率', rate=True)
    if currency == 'CNY' and rate is None and not draft:
        raise ValueError('人民币订单必须填写本单汇率（1 USD = CNY）')
    if old.get('status') in {'paid','shipped','completed','cancelled'}:
        if currency != (old.get('currency') or 'USD') or rate != old.get('exchange_rate'):
            raise ValueError('已付款、已发货、已完成或已取消订单的币种及汇率已锁定')
    return currency, rate


def catalog_price(usd, currency, rate):
    with localcontext() as context:
        context.prec = 48
        if currency == 'CNY' and not rate:
            raise ValueError('请先填写本单汇率')
        result = (Decimal(str(usd)) * (rate if currency == 'CNY' else 1)).quantize(CENT, rounding=ROUND_HALF_UP)
        if result > MAX_AMOUNT: raise ValueError('换算后的目录单价超出金额范围，请使用有效成交价')
        return result


def usd_sql(expression, alias='o'):
    # CNY orders always have a positive snapshot rate, enforced by the schema.
    return f"(CASE WHEN {alias}.currency='CNY' THEN ROUND(({expression})/{alias}.exchange_rate,2) ELSE ({expression}) END)"


def to_usd(amount, currency='USD', exchange_rate=None):
    with localcontext() as context:
        context.prec = 48
        value = Decimal(str(amount or 0))
        if currency == 'CNY':
            value /= decimal(exchange_rate, '本单汇率', rate=True)
        return value.quantize(CENT, rounding=ROUND_HALF_UP)


def default_rate(db):
    row = db._fetch_one('SELECT exchange_rate FROM finance_settings WHERE id=1')
    return row['exchange_rate'] if row else None


def settings(db):
    rate = default_rate(db)
    return {'defaultCurrency':'USD', 'currencies':list(CURRENCIES),
            'exchangeRate':format(rate, '.6f') if rate is not None else None}


def financial_changed(old, total, currency):
    return bool(old and (old['total_amount'] != total or (old.get('currency') or 'USD') != currency))


def excel_format(currency):
    return ('"CNY ¥"' if currency == 'CNY' else '"USD $"') + '#,##0.00'
