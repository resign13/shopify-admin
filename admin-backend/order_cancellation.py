"""Internal cancellation notes; keep stock transitions in the existing order flow."""
MISSING = object()
MAX_LENGTH = 500


def migrate(cur):
    cur.execute("""ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancellation_note TEXT NOT NULL DEFAULT '';
      DO $$ BEGIN
        IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='orders_cancellation_note_length' AND conrelid='orders'::regclass) THEN
          ALTER TABLE orders ADD CONSTRAINT orders_cancellation_note_length CHECK(char_length(cancellation_note)<=500);
        END IF;
      END $$;""")


def normalize(value):
    if not isinstance(value, str):
        raise ValueError('取消备注须为文字')
    value = value.strip()
    if len(value) > MAX_LENGTH or '\x00' in value:
        raise ValueError('取消备注最多 500 字，且须为有效文字')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError('取消备注须为有效文字') from error
    return value


def next_note(previous_status, status, value=MISSING, current=''):
    note = normalize(value) if value is not MISSING else None
    if status != 'cancelled':
        if note and previous_status != 'cancelled':
            raise ValueError('仅已取消订单可填写取消备注')
        return ''
    if note is not None:
        return note
    return current if previous_status == 'cancelled' else ''
