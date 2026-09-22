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
  email VARCHAR(255) NOT NULL,
  password_hash TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_store_users_email_lower
  ON store_users (LOWER(email));

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
  stock INTEGER NOT NULL DEFAULT 0,
  contract_pending INTEGER NOT NULL DEFAULT 0 CHECK (contract_pending >= 0),
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
  order_no VARCHAR(40) NOT NULL UNIQUE,
  store_user_id BIGINT NOT NULL REFERENCES store_users(id),
  status VARCHAR(30) NOT NULL DEFAULT 'pending_payment'
    CHECK (status IN ('pending_payment', 'paid', 'shipped', 'completed', 'cancelled')),
  contact_name VARCHAR(120) NOT NULL,
  phone VARCHAR(50) NOT NULL,
  country VARCHAR(120),
  shipping_address TEXT NOT NULL,
  note TEXT,
  total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
  payment_link TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by_admin_id BIGINT REFERENCES admin_users(id)
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


COMMIT;
