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
  lang_code VARCHAR(8) NOT NULL CHECK (lang_code IN ('zh', 'en', 'fr')),
  label VARCHAR(255) NOT NULL,
  UNIQUE (category_id, lang_code)
);

CREATE TABLE IF NOT EXISTS products (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_id BIGINT NOT NULL REFERENCES product_categories(id),
  slug VARCHAR(160) NOT NULL UNIQUE,
  sku VARCHAR(80) NOT NULL UNIQUE,
  price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
  stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
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
  lang_code VARCHAR(8) NOT NULL CHECK (lang_code IN ('zh', 'en', 'fr')),
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
  stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (product_id, size_code)
);

CREATE INDEX IF NOT EXISTS idx_product_size_prices_product_id
  ON product_size_prices (product_id);

CREATE TABLE IF NOT EXISTS product_price_tiers (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  min_qty INTEGER NOT NULL CHECK (min_qty > 0),
  max_qty INTEGER,
  discount_percent NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (discount_percent >= 0 AND discount_percent <= 100),
  tier_price NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (tier_price >= 0),
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_product_price_tiers_product_id
  ON product_price_tiers (product_id);

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
  lang_code VARCHAR(8) NOT NULL CHECK (lang_code IN ('zh', 'en', 'fr')),
  title VARCHAR(255) NOT NULL,
  subtitle TEXT,
  cta_label VARCHAR(120),
  UNIQUE (banner_id, lang_code)
);

CREATE TABLE IF NOT EXISTS orders (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_no VARCHAR(40) NOT NULL UNIQUE,
  store_user_id BIGINT NOT NULL REFERENCES store_users(id),
  status VARCHAR(30) NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'paid', 'packed', 'shipped', 'completed', 'cancelled')),
  contact_name VARCHAR(120) NOT NULL,
  phone VARCHAR(50) NOT NULL,
  country VARCHAR(120),
  shipping_address TEXT NOT NULL,
  note TEXT,
  total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_store_user_id
  ON orders (store_user_id);

CREATE INDEX IF NOT EXISTS idx_orders_status
  ON orders (status);

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

INSERT INTO admin_users (name, email, password_hash, status, created_at, updated_at)
SELECT
  'Admin',
  'admin@lumiere.com',
  'scrypt:32768:8:1$8G1pSpHAm2g3o3xX$2c3d5d2ac89fe8051f57b4d9c1f1b5c880fa0a4291dfb59f4e4f2ca5580d6117769f052505616f46846071f2cdcb4e31737dd7424521af27840f26f7ef2f3ea8',
  'active',
  '2026-04-23T00:00:00+00:00',
  NOW()
WHERE NOT EXISTS (
  SELECT 1 FROM admin_users WHERE LOWER(email) = 'admin@lumiere.com'
);

INSERT INTO store_users (name, company_name, email, password_hash, status, created_at, updated_at)
SELECT
  'Lina Buyer',
  'Lumiere Demo Buyer',
  'buyer@lumiere.com',
  'scrypt:32768:8:1$uR8Zf27oBTOELkZI$16b4be72cd23d88ce0a344fa124ed6c3e0274b0ce2f891f1c24c67c79bb738446425ce0d8168ec029155cfb3dbe65cc1f9788bf742af5eb35d5de625454aab7b',
  'active',
  '2026-04-23T00:00:00+00:00',
  NOW()
WHERE NOT EXISTS (
  SELECT 1 FROM store_users WHERE LOWER(email) = 'buyer@lumiere.com'
);

INSERT INTO product_categories (category_key, sort_order)
VALUES
  ('womenswear', 10),
  ('menswear', 20),
  ('pants', 30),
  ('denim', 40),
  ('outerwear', 50)
ON CONFLICT (category_key) DO NOTHING;

INSERT INTO product_category_translations (category_id, lang_code, label)
SELECT pc.id, v.lang_code, v.label
FROM product_categories pc
JOIN (
  VALUES
    ('womenswear', 'zh', '濂宠'),
    ('womenswear', 'en', 'Womenswear'),
    ('womenswear', 'fr', 'Mode femme'),
    ('menswear', 'zh', '鐢疯'),
    ('menswear', 'en', 'Menswear'),
    ('menswear', 'fr', 'Mode homme'),
    ('pants', 'zh', '瑁よ'),
    ('pants', 'en', 'Pants'),
    ('pants', 'fr', 'Pantalons'),
    ('denim', 'zh', '鐗涗粩'),
    ('denim', 'en', 'Denim'),
    ('denim', 'fr', 'Denim'),
    ('outerwear', 'zh', '澶栧'),
    ('outerwear', 'en', 'Outerwear'),
    ('outerwear', 'fr', 'Vetements d''exterieur')
) AS v(category_key, lang_code, label)
  ON v.category_key = pc.category_key
ON CONFLICT (category_id, lang_code) DO NOTHING;

INSERT INTO products (category_id, slug, sku, price, stock, featured, origin, main_image_url, is_active, created_at, updated_at)
SELECT
  pc.id,
  'atelier-linen-shirt-dress',
  'LA-DR-001',
  34.00,
  320,
  TRUE,
  'Guangzhou, China',
  'https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=1200&q=80',
  TRUE,
  NOW(),
  NOW()
FROM product_categories pc
WHERE pc.category_key = 'womenswear'
  AND NOT EXISTS (SELECT 1 FROM products WHERE slug = 'atelier-linen-shirt-dress');

INSERT INTO products (category_id, slug, sku, price, stock, featured, origin, main_image_url, is_active, created_at, updated_at)
SELECT
  pc.id,
  'signature-oxford-shirt',
  'LA-MS-008',
  21.00,
  540,
  TRUE,
  'Ningbo, China',
  'https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?auto=format&fit=crop&w=1200&q=80',
  TRUE,
  NOW(),
  NOW()
FROM product_categories pc
WHERE pc.category_key = 'menswear'
  AND NOT EXISTS (SELECT 1 FROM products WHERE slug = 'signature-oxford-shirt');

INSERT INTO product_translations (product_id, lang_code, name, summary, description)
SELECT p.id, v.lang_code, v.name, v.summary, v.description
FROM products p
JOIN (
  VALUES
    ('atelier-linen-shirt-dress', 'zh', 'Atelier 浜氶夯琛～杩炶。瑁?, '绮惧搧搴﹀亣椋庝簹楹昏锛岄€傚悎濂宠绯诲垪寮€鍙戙€?, '鍨傚潬鎰熶笌鑸掗€傜増鍨嬪吋鍏凤紝鏀寔闈㈡枡銆佽緟鏂欏拰鍚婄墝瀹氬埗銆?),
    ('atelier-linen-shirt-dress', 'en', 'Atelier Linen Shirt Dress', 'Premium resort-style linen dress for boutique fashion programs.', 'Fluid drape and easy silhouette with customization support for fabric, trims and labels.'),
    ('atelier-linen-shirt-dress', 'fr', 'Robe chemise en lin Atelier', 'Robe en lin premium esprit resort pour les programmes mode boutique.', 'Beau tombe et silhouette decontractee avec personnalisation des tissus, finitions et etiquettes.'),
    ('signature-oxford-shirt', 'zh', 'Signature 鐗涙触绾鸿‖琛?, '缁忓吀琛～绯诲垪锛岄€傚悎鐢疯鍝佺墝涓庡埗鏈嶉噰璐€?, '楂樺瘑妫夌罕鏉愯川锛屾敮鎸侀鏍囥€佸埡缁ｅ拰鍖呰瀹氬埗銆?),
    ('signature-oxford-shirt', 'en', 'Signature Oxford Shirt', 'Classic shirt program for menswear brands and uniform buyers.', 'High-density cotton yarn with customizable labels, embroidery and packaging.'),
    ('signature-oxford-shirt', 'fr', 'Chemise Oxford Signature', 'Programme chemise classique pour les marques homme et l uniforme.', 'Coton haute densite avec etiquettes, broderies et packaging personnalisables.')
) AS v(slug, lang_code, name, summary, description)
  ON v.slug = p.slug
ON CONFLICT (product_id, lang_code) DO NOTHING;

INSERT INTO product_images (product_id, image_url, sort_order)
SELECT p.id, v.image_url, v.sort_order
FROM products p
JOIN (
  VALUES
    ('atelier-linen-shirt-dress', 'https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=1200&q=80', 1),
    ('atelier-linen-shirt-dress', 'https://images.unsplash.com/photo-1529139574466-a303027c1d8b?auto=format&fit=crop&w=1200&q=80', 2),
    ('atelier-linen-shirt-dress', 'https://images.unsplash.com/photo-1496747611176-843222e1e57c?auto=format&fit=crop&w=1200&q=80', 3),
    ('signature-oxford-shirt', 'https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?auto=format&fit=crop&w=1200&q=80', 1),
    ('signature-oxford-shirt', 'https://images.unsplash.com/photo-1521572267360-ee0c2909d518?auto=format&fit=crop&w=1200&q=80', 2)
) AS v(slug, image_url, sort_order)
  ON v.slug = p.slug
WHERE NOT EXISTS (
  SELECT 1 FROM product_images pi
  WHERE pi.product_id = p.id AND pi.image_url = v.image_url
);

INSERT INTO product_sizes (product_id, size_code, sort_order)
SELECT p.id, v.size_code, v.sort_order
FROM products p
JOIN (
  VALUES
    ('atelier-linen-shirt-dress', 'S', 1),
    ('atelier-linen-shirt-dress', 'M', 2),
    ('atelier-linen-shirt-dress', 'L', 3),
    ('atelier-linen-shirt-dress', 'XL', 4),
    ('signature-oxford-shirt', 'S', 1),
    ('signature-oxford-shirt', 'M', 2),
    ('signature-oxford-shirt', 'L', 3),
    ('signature-oxford-shirt', 'XL', 4),
    ('signature-oxford-shirt', 'XXL', 5)
) AS v(slug, size_code, sort_order)
  ON v.slug = p.slug
ON CONFLICT (product_id, size_code) DO NOTHING;

INSERT INTO banners (image_url, cta_path, sort_order, is_active, created_at, updated_at)
SELECT
  'https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=1600&q=80',
  '/shop',
  1,
  TRUE,
  NOW(),
  NOW()
WHERE NOT EXISTS (
  SELECT 1
  FROM banners
  WHERE image_url = 'https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=1600&q=80'
);

INSERT INTO banners (image_url, cta_path, sort_order, is_active, created_at, updated_at)
SELECT
  'https://images.unsplash.com/photo-1512436991641-6745cdb1723f?auto=format&fit=crop&w=1600&q=80',
  '/shop',
  2,
  TRUE,
  NOW(),
  NOW()
WHERE NOT EXISTS (
  SELECT 1
  FROM banners
  WHERE image_url = 'https://images.unsplash.com/photo-1512436991641-6745cdb1723f?auto=format&fit=crop&w=1600&q=80'
);

INSERT INTO banner_translations (banner_id, lang_code, title, subtitle, cta_label)
SELECT b.id, v.lang_code, v.title, v.subtitle, v.cta_label
FROM banners b
JOIN (
  VALUES
    ('https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=1600&q=80', 'zh', '2026 鏄ュ鏈嶈涓绘帹绯诲垪', '鑱氱劍濂宠銆佺敺瑁呬笌瑁よ澶ц揣娆惧紡锛屽簱瀛樺疄鏃跺彲鏌ャ€?, '杩涘叆鍟嗗煄'),
    ('https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=1600&q=80', 'en', 'Spring Summer 2026 Apparel Highlights', 'Focus on dresses, shirts and pants with live stock visibility.', 'Shop Now'),
    ('https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=1600&q=80', 'fr', 'Temps forts apparel printemps ete 2026', 'Focus sur robes, chemises et pantalons avec stock visible en temps reel.', 'Entrer en boutique'),
    ('https://images.unsplash.com/photo-1512436991641-6745cdb1723f?auto=format&fit=crop&w=1600&q=80', 'zh', '瑁よ涓庣墰浠旂郴鍒楁寔缁ˉ璐?, '鏀寔瀹㈡埛鍦ㄧ嚎涓嬪崟锛岃鍗曡嚜鍔ㄨ繘鍏ュ悗鍙扮鐞嗙銆?, '鏌ョ湅搴撳瓨'),
    ('https://images.unsplash.com/photo-1512436991641-6745cdb1723f?auto=format&fit=crop&w=1600&q=80', 'en', 'Pants and Denim Restock Program', 'Customers can place orders online and sync them to the admin panel.', 'Check Inventory'),
    ('https://images.unsplash.com/photo-1512436991641-6745cdb1723f?auto=format&fit=crop&w=1600&q=80', 'fr', 'Programme de reassort pantalons et denim', 'Les clients commandent en ligne et les commandes remontent dans l admin.', 'Voir le stock')
) AS v(image_url, lang_code, title, subtitle, cta_label)
  ON v.image_url = b.image_url
ON CONFLICT (banner_id, lang_code) DO NOTHING;

COMMIT;


