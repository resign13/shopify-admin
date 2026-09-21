"""Export the migration snapshot for manual reconciliation; never adjust inventory."""
import argparse
import csv
from pathlib import Path
import sys

vendor = Path(__file__).resolve().parent / '_vendor'
if vendor.exists(): sys.path.insert(0, str(vendor))
import db


def export_report(output):
    with db.get_connection() as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        rows = conn.execute("""SELECT h.order_id,h.order_no,h.order_updated_at,h.captured_at,
          COALESCE(o.status,'deleted') AS current_status,i.product_id,i.sku,i.size_code,i.quantity,
          s.stock AS current_size_balance,'人工核对是否曾退库；本清单不代表应自动补退' AS review_note
          FROM inventory_legacy_cancelled_orders h LEFT JOIN orders o ON o.id=h.order_id
          LEFT JOIN order_items i ON i.order_id=h.order_id
          LEFT JOIN product_size_prices s ON s.product_id=i.product_id AND s.size_code=i.size_code
          ORDER BY h.order_id,i.id""").fetchall()
    fields = ['order_id','order_no','order_updated_at','captured_at','current_status','product_id',
              'sku','size_code','quantity','current_size_balance','review_note']
    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader();writer.writerows(rows)
    return len(rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(f'Exported {export_report(args.output)} reconciliation rows; inventory unchanged.')
