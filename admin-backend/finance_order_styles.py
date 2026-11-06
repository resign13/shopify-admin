"""An order's first accounting style for each product survives line rebuilds."""
import style_catalog


VERSION = 'finance-order-style-bindings-v1'

# Use the original report lookup for legacy rows outside the normal product FK.
ORDER_ITEM_STYLE_JOINS = '''
  LEFT JOIN finance_order_style_bindings b ON b.order_id=i.order_id AND b.product_id=i.product_id
  LEFT JOIN products p ON p.id=i.product_id
  LEFT JOIN LATERAL (SELECT style_code FROM finance_cost_history c
    WHERE c.product_id=i.product_id AND c.size_code=i.size_code
    ORDER BY effective_date DESC LIMIT 1) ch ON p.id IS NULL'''
ORDER_ITEM_STYLE_SQL = f"COALESCE(b.style_code, CASE WHEN p.id IS NOT NULL THEN {style_catalog.style_sql()} ELSE COALESCE(ch.style_code,'未归类') END)"

# Keep bindings when an editor removes a line, but do not list unused bindings
# in the cost editor until the product actually appears on an order again.
USED_STYLES_SQL = '''SELECT DISTINCT b.style_code FROM finance_order_style_bindings b
  WHERE EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=b.order_id AND i.product_id=b.product_id)'''


def migrate(cur):
    cur.execute('SELECT 1 FROM security_schema_versions WHERE version=%s', (VERSION,))
    if cur.fetchone():
        return
    # All order writers share this table. The trigger can insert its own row
    # without granting the storefront direct access to any finance data.
    cur.execute(f'''
      CREATE TABLE IF NOT EXISTS public.finance_order_style_bindings (
        order_id BIGINT NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
        product_id BIGINT NOT NULL,
        style_code TEXT NOT NULL,
        PRIMARY KEY(order_id,product_id)
      );
      CREATE OR REPLACE FUNCTION public.capture_finance_order_style() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$
      BEGIN
        INSERT INTO public.finance_order_style_bindings(order_id,product_id,style_code)
        SELECT NEW.order_id,NEW.product_id,{style_catalog.style_sql()}
        FROM public.products p WHERE p.id=NEW.product_id
        ON CONFLICT(order_id,product_id) DO NOTHING;
        RETURN NEW;
      END;
      $body$;
      REVOKE ALL ON FUNCTION public.capture_finance_order_style() FROM PUBLIC;
      CREATE OR REPLACE TRIGGER order_items_capture_finance_style
        AFTER INSERT OR UPDATE OF order_id,product_id ON public.order_items
        FOR EACH ROW EXECUTE FUNCTION public.capture_finance_order_style();
      -- Backfill the same current catalog style the old report uses. The
      -- trigger DDL and the backfill commit together, with no write gap.
      INSERT INTO public.finance_order_style_bindings(order_id,product_id,style_code)
      SELECT DISTINCT i.order_id,i.product_id,{style_catalog.style_sql()}
      FROM public.order_items i JOIN public.products p ON p.id=i.product_id
      ON CONFLICT(order_id,product_id) DO NOTHING;
    ''')
    cur.execute('INSERT INTO security_schema_versions(version) VALUES(%s) ON CONFLICT DO NOTHING', (VERSION,))
