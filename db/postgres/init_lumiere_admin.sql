BEGIN;

CREATE TABLE IF NOT EXISTS admin_users (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  email VARCHAR(255) NOT NULL,
  password_hash TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_users_email_lower
  ON admin_users (LOWER(email));

CREATE TABLE IF NOT EXISTS admin_sessions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admin_user_id BIGINT NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
  token VARCHAR(255) NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_admin_user_id
  ON admin_sessions (admin_user_id);

CREATE TABLE IF NOT EXISTS store_users (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  company_name VARCHAR(255),
  linked_admin_user_id BIGINT REFERENCES admin_users(id),
  email VARCHAR(255) NOT NULL,
  password_hash TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_store_users_email_lower
  ON store_users (LOWER(email));

CREATE TABLE IF NOT EXISTS order_customer_templates (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name VARCHAR(120) NOT NULL CHECK(length(btrim(name)) > 0),
  store_user_id BIGINT REFERENCES store_users(id) ON DELETE SET NULL,
  created_by_admin_id BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
  customer_info JSONB NOT NULL DEFAULT '{}'::jsonb,
  revision BIGINT NOT NULL DEFAULT 1 CHECK(revision > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_order_customer_templates_customer ON order_customer_templates(store_user_id);
CREATE INDEX IF NOT EXISTS idx_order_customer_templates_creator
    ON order_customer_templates(created_by_admin_id,updated_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS product_categories (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_key VARCHAR(80) NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product_category_translations (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_id BIGINT NOT NULL REFERENCES product_categories(id) ON DELETE CASCADE,
  lang_code VARCHAR(8) NOT NULL CHECK (lang_code IN ('zh', 'en')),
  label VARCHAR(255) NOT NULL,
  UNIQUE (category_id, lang_code)
);

CREATE TABLE IF NOT EXISTS products (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_id BIGINT NOT NULL REFERENCES product_categories(id),
  slug VARCHAR(160) NOT NULL UNIQUE,
  sku VARCHAR(80) NOT NULL UNIQUE,
  price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
  stock INTEGER NOT NULL DEFAULT 0,
  featured BOOLEAN NOT NULL DEFAULT FALSE,
  origin VARCHAR(255),
  main_image_url TEXT NOT NULL,
  size_chart_image_url TEXT,
  description_image_url TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_category_id
  ON products (category_id);

CREATE INDEX IF NOT EXISTS idx_products_featured
  ON products (featured);

CREATE TABLE IF NOT EXISTS product_translations (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  lang_code VARCHAR(8) NOT NULL CHECK (lang_code IN ('zh', 'en')),
  name VARCHAR(255) NOT NULL,
  summary TEXT,
  description TEXT,
  UNIQUE (product_id, lang_code)
);

CREATE TABLE IF NOT EXISTS product_images (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  image_url TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_product_images_product_id
  ON product_images (product_id);

CREATE TABLE IF NOT EXISTS product_sizes (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  size_code VARCHAR(32) NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (product_id, size_code)
);

CREATE INDEX IF NOT EXISTS idx_product_sizes_product_id
  ON product_sizes (product_id);

CREATE TABLE IF NOT EXISTS product_size_prices (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  size_code VARCHAR(32) NOT NULL,
  price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
  weight_grams INTEGER CONSTRAINT product_size_prices_weight_positive CHECK (weight_grams IS NULL OR weight_grams > 0),
  stock INTEGER NOT NULL DEFAULT 0,
  contract_pending INTEGER NOT NULL DEFAULT 0 CHECK (contract_pending >= 0),
  temporary_inbound INTEGER NOT NULL DEFAULT 0 CHECK (temporary_inbound >= 0),
  defective_pending INTEGER NOT NULL DEFAULT 0 CHECK (defective_pending >= 0),
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (product_id, size_code)
);

CREATE INDEX IF NOT EXISTS idx_product_size_prices_product_id
  ON product_size_prices (product_id);


CREATE TABLE IF NOT EXISTS banners (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  image_url TEXT NOT NULL,
  cta_path VARCHAR(255) NOT NULL DEFAULT '/shop',
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS banner_translations (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  banner_id BIGINT NOT NULL REFERENCES banners(id) ON DELETE CASCADE,
  lang_code VARCHAR(8) NOT NULL CHECK (lang_code IN ('zh', 'en')),
  title VARCHAR(255) NOT NULL,
  subtitle TEXT,
  cta_label VARCHAR(120),
  UNIQUE (banner_id, lang_code)
);

CREATE TABLE IF NOT EXISTS orders (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_no VARCHAR(255) NOT NULL UNIQUE,
  secondary_order_no VARCHAR(255) NOT NULL DEFAULT '',
  store_user_id BIGINT NOT NULL REFERENCES store_users(id),
  status VARCHAR(30) NOT NULL DEFAULT 'pending_payment'
    CHECK (status IN ('pending_payment', 'partially_allocated', 'allocated', 'paid', 'shipped', 'completed', 'cancelled')),
  contact_name VARCHAR(120) NOT NULL,
  phone VARCHAR(50) NOT NULL,
  country VARCHAR(120),
  shipping_address TEXT NOT NULL,
  note TEXT,
  cancellation_note TEXT NOT NULL DEFAULT '',
  total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
  payment_link TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by_admin_id BIGINT REFERENCES admin_users(id),
  owner_admin_id BIGINT REFERENCES admin_users(id),
  order_source VARCHAR(20) NOT NULL DEFAULT 'store' CHECK(order_source IN ('store','backend'))
);

CREATE INDEX IF NOT EXISTS idx_orders_store_user_id
  ON orders (store_user_id);

CREATE INDEX IF NOT EXISTS idx_orders_status
  ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_created_by_admin_id ON orders (created_by_admin_id);

CREATE TABLE IF NOT EXISTS order_items (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id BIGINT NOT NULL REFERENCES products(id),
  product_name VARCHAR(255) NOT NULL,
  sku VARCHAR(80) NOT NULL,
  size_code VARCHAR(32),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
  total_price NUMERIC(12, 2) NOT NULL CHECK (total_price >= 0)
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id
  ON order_items (order_id);

CREATE INDEX IF NOT EXISTS idx_order_items_product_id
  ON order_items (product_id);


CREATE TABLE IF NOT EXISTS inventory_registration_logs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id BIGINT NOT NULL,
  sku TEXT NOT NULL,
  actor JSONB NOT NULL,
  changes JSONB NOT NULL CHECK (jsonb_typeof(changes)='array'),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_inventory_registration_product_time
  ON inventory_registration_logs (product_id, occurred_at DESC, id DESC);


CREATE TABLE IF NOT EXISTS order_notification_state (
  singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
  last_sequence BIGINT NOT NULL DEFAULT 0 CHECK (last_sequence >= 0)
);
INSERT INTO order_notification_state(singleton) VALUES(TRUE) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS order_created_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  publish_sequence BIGINT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_order_events_unpublished ON order_created_events(id)
  WHERE publish_sequence IS NULL;
CREATE INDEX IF NOT EXISTS idx_order_events_recorded ON order_created_events(recorded_at);
CREATE TABLE IF NOT EXISTS order_notification_starts (
  session_id BIGINT NOT NULL REFERENCES admin_sessions(id) ON DELETE CASCADE,
  request_id UUID NOT NULL,
  baseline BIGINT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(session_id, request_id)
);
CREATE OR REPLACE FUNCTION capture_order_created_notification() RETURNS trigger AS $$
BEGIN
  IF COALESCE(current_setting('gingtto.notifications_paused', true), '') IN ('on','true','1') THEN
    RETURN NEW;
  END IF;
  INSERT INTO order_created_events(order_id) VALUES(NEW.id) ON CONFLICT(order_id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='orders'::regclass
                AND tgname='orders_created_notification' AND NOT tgisinternal) THEN
    CREATE TRIGGER orders_created_notification AFTER INSERT ON orders
      FOR EACH ROW EXECUTE FUNCTION capture_order_created_notification();
  END IF;
END $$;

COMMIT;

-- Independent display-only curation. Existing homepage selection is not migrated.
CREATE TABLE IF NOT EXISTS presale_configs (
 id SMALLINT PRIMARY KEY DEFAULT 1 CHECK(id=1),
 style_codes JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(style_codes)='array'),
 sort_mode TEXT NOT NULL DEFAULT 'automatic' CHECK(sort_mode IN ('automatic','manual')),
 version BIGINT NOT NULL DEFAULT 0 CHECK(version>=0),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO presale_configs(id) VALUES(1) ON CONFLICT DO NOTHING;

-- Private finance data: logical variant identity, deliberately no cascading product foreign key.
CREATE TABLE IF NOT EXISTS finance_cost_versions (
      product_id BIGINT NOT NULL, size_code TEXT NOT NULL, revision BIGINT NOT NULL DEFAULT 0,
      PRIMARY KEY(product_id,size_code));
    CREATE TABLE IF NOT EXISTS finance_cost_history (
      product_id BIGINT NOT NULL, size_code TEXT NOT NULL, effective_date DATE NOT NULL,
      cost_cny NUMERIC(12,2) CHECK(cost_cny>=0), sku TEXT NOT NULL, style_code TEXT NOT NULL,
      actor JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(product_id,size_code,effective_date));
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='finance_cost_history'::regclass
                AND attname='cost_cny' AND attnotnull AND NOT attisdropped) THEN
        ALTER TABLE finance_cost_history ALTER COLUMN cost_cny DROP NOT NULL;
      END IF;
    END $$;
    CREATE TABLE IF NOT EXISTS finance_cost_audit (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, product_id BIGINT NOT NULL,
      size_code TEXT NOT NULL, effective_date DATE NOT NULL, before_data JSONB NOT NULL,
      after_data JSONB NOT NULL, actor JSONB NOT NULL, request_id UUID NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE TABLE IF NOT EXISTS finance_cost_receipts (
      request_id UUID PRIMARY KEY, actor_id BIGINT NOT NULL, fingerprint TEXT NOT NULL,
      result JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE INDEX IF NOT EXISTS finance_cost_audit_variant ON finance_cost_audit(product_id,size_code,id DESC);
CREATE TABLE IF NOT EXISTS finance_settings (
  id SMALLINT PRIMARY KEY CHECK(id=1),
  exchange_rate NUMERIC(16,6) NOT NULL CHECK(exchange_rate>0),
  revision BIGINT NOT NULL DEFAULT 1,
  updated_by BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

    -- Keep the legacy variant timelines intact; they are not the active cost source.
    -- No product/size FK: changing or deleting catalog rows must not erase cost history.
    CREATE TABLE IF NOT EXISTS finance_style_costs (
      style_code TEXT PRIMARY KEY CHECK(length(btrim(style_code)) BETWEEN 1 AND 200),
      cost_cny NUMERIC(12,2) CHECK(cost_cny>=0), revision BIGINT NOT NULL DEFAULT 0,
      actor JSONB NOT NULL DEFAULT '{}'::jsonb,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE TABLE IF NOT EXISTS finance_style_cost_audit (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, style_code TEXT NOT NULL,
      old_cost_cny NUMERIC(12,2), cost_cny NUMERIC(12,2), actor JSONB NOT NULL,
      request_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      effective_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      is_initial BOOLEAN NOT NULL DEFAULT false);
    -- Preserve the actual original save time when upgrading existing cost events.
    ALTER TABLE finance_style_cost_audit ADD COLUMN IF NOT EXISTS effective_at TIMESTAMPTZ;
    UPDATE finance_style_cost_audit SET effective_at=created_at WHERE effective_at IS NULL;
    ALTER TABLE finance_style_cost_audit ALTER COLUMN effective_at SET DEFAULT clock_timestamp();
    ALTER TABLE finance_style_cost_audit ALTER COLUMN effective_at SET NOT NULL;
    ALTER TABLE finance_style_cost_audit ADD COLUMN IF NOT EXISTS is_initial BOOLEAN NOT NULL DEFAULT false;
    INSERT INTO finance_style_cost_audit(style_code,old_cost_cny,cost_cny,actor,request_id,created_at,effective_at)
      SELECT c.style_code,NULL,c.cost_cny,c.actor,md5('finance-style-baseline:'||c.style_code)::uuid,c.updated_at,c.updated_at
      FROM finance_style_costs c WHERE NOT EXISTS (
        SELECT 1 FROM finance_style_cost_audit a WHERE a.style_code=c.style_code);
    WITH initial AS (
      SELECT DISTINCT ON (a.style_code) a.id FROM finance_style_cost_audit a
      WHERE a.cost_cny IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM finance_style_cost_audit b WHERE b.style_code=a.style_code AND b.is_initial)
      ORDER BY a.style_code,a.effective_at,a.id)
    UPDATE finance_style_cost_audit a SET is_initial=true FROM initial i WHERE a.id=i.id;
    CREATE UNIQUE INDEX IF NOT EXISTS finance_style_cost_audit_initial
      ON finance_style_cost_audit(style_code) WHERE is_initial;
    CREATE INDEX IF NOT EXISTS finance_style_cost_audit_style
      ON finance_style_cost_audit(style_code,id DESC);
    CREATE INDEX IF NOT EXISTS finance_style_cost_audit_timeline
      ON finance_style_cost_audit(style_code,effective_at DESC,id DESC);

-- Order quotes: native USD/CNY amounts, immutable per-order FX snapshots.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NOT NULL DEFAULT 'USD';
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
      END $$;

-- First successful warehouse export; independent of order versions and stock.
CREATE TABLE IF NOT EXISTS order_warehouse_prints (
    order_id BIGINT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    printed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    printed_by_admin_id BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
    printed_by_name TEXT NOT NULL DEFAULT '',
    export_kind TEXT NOT NULL CHECK (export_kind IN ('export', 'export-by-sheet'))
);

-- Internal cancellation notes; additive and repeatable, no historical note rewrite.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancellation_note TEXT NOT NULL DEFAULT '';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='orders_cancellation_note_length' AND conrelid='orders'::regclass) THEN
    ALTER TABLE orders ADD CONSTRAINT orders_cancellation_note_length CHECK (char_length(cancellation_note)<=500);
  END IF;
END $$;
