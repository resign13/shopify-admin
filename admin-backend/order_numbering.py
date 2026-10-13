"""Canonical order numbers. Keep identical in both applications."""
from datetime import timedelta, timezone
import re
import unicodedata

BEIJING = timezone(timedelta(hours=8))


def make_order_number(order_id, created_at, contact_name):
    if created_at.tzinfo is None:
        raise ValueError('Order timestamp must include its timezone')
    return f"PO{created_at.astimezone(BEIJING):%m%d}-{contact_name}-{int(order_id):06d}"


def migrate(cur):
    # Only widen old schemas. Repeated startup neither rewrites numbers nor
    # obtains another ALTER lock on an already compatible column.
    cur.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='orders'
          AND column_name='order_no' AND character_maximum_length < 255) THEN
        ALTER TABLE orders ALTER COLUMN order_no TYPE VARCHAR(255);
      END IF;
    END $$""")


def sheet_title(number):
    match = re.fullmatch(r'(PO[0-9]{4})-(.+)-([0-9]{6,})', str(number), re.DOTALL)
    return f'{match[1]}-{match[3]}' if match else str(number)


def display_width(text):
    return sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in {'W','F'} else 1 for ch in str(text))


def wrapped_lines(text, width):
    return sum(max(1, (display_width(line) + width - 1) // width) for line in str(text).split('\n'))
