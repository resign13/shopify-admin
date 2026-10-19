"""Additive machine API boundary. Shared verbatim by the two applications."""
from style_catalog import style_sql

VERSION = 'external-api-v2'
VIEWS = ('external_api_credentials_v', 'external_api_products_v',
         'external_api_images_v', 'external_api_sizes_v')


def migrate(cur):
    cur.execute("""
    ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'admin';
    ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS permissions JSONB;
    CREATE TABLE IF NOT EXISTS api_integrations (
      admin_user_id BIGINT PRIMARY KEY REFERENCES admin_users(id) ON DELETE CASCADE,
      token_hash VARCHAR(64) UNIQUE, key_id UUID UNIQUE,
      enabled BOOLEAN NOT NULL DEFAULT true, admin_blocked BOOLEAN NOT NULL DEFAULT false,
      expires_at TIMESTAMPTZ, version BIGINT NOT NULL DEFAULT 0 CHECK(version>=0),
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), last_used_at TIMESTAMPTZ,
      CHECK ((token_hash IS NULL) = (key_id IS NULL)));
    CREATE TABLE IF NOT EXISTS api_integration_events (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      actor_id BIGINT, subject_id BIGINT NOT NULL, key_id UUID,
      event_code VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE TABLE IF NOT EXISTS api_call_logs (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      admin_user_id BIGINT NOT NULL, key_id UUID NOT NULL,
      route VARCHAR(100) NOT NULL, status SMALLINT NOT NULL,
      duration_ms INTEGER NOT NULL CHECK(duration_ms>=0), request_id UUID NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE INDEX IF NOT EXISTS api_call_logs_owner_time ON api_call_logs(admin_user_id,created_at DESC,id DESC);
    CREATE INDEX IF NOT EXISTS api_call_logs_retention ON api_call_logs(created_at);
    CREATE INDEX IF NOT EXISTS api_integration_events_retention ON api_integration_events(created_at);
    CREATE TABLE IF NOT EXISTS api_rate_buckets (
      bucket_key VARCHAR(64) PRIMARY KEY, ticks TIMESTAMPTZ[] NOT NULL DEFAULT '{}',
      updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
    CREATE TABLE IF NOT EXISTS api_request_leases (
      request_id UUID PRIMARY KEY, key_id UUID NOT NULL,
      expires_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX IF NOT EXISTS api_request_leases_expiry ON api_request_leases(expires_at);
    CREATE OR REPLACE VIEW external_api_credentials_v WITH(security_barrier=true) AS
      SELECT k.admin_user_id,k.token_hash,k.key_id,k.enabled,k.admin_blocked,k.expires_at,k.version,
        u.status='active' AND u.role IN ('admin','sales','warehouse','finance') AND
        ((u.permissions IS NULL AND u.role='admin') OR COALESCE(u.permissions ? 'api-integrations',false)) AS allowed
      FROM api_integrations k JOIN admin_users u ON u.id=k.admin_user_id;
    """)
    cur.execute(f"""CREATE OR REPLACE VIEW external_api_products_v WITH(security_barrier=true) AS
      SELECT p.id,{style_sql('p')} AS style_code,p.sku,p.color_name,p.category_id,
        c.category_key,COALESCE(ct.label,'') AS category_name,
        COALESCE(t.name,'') AS title,COALESCE(t.summary,'') AS summary,
        COALESCE(t.description,'') AS description,p.main_image_url,p.size_chart_image_url,p.description_image_url
      FROM products p JOIN product_categories c ON c.id=p.category_id
      LEFT JOIN product_category_translations ct ON ct.category_id=c.id AND ct.lang_code='en'
      LEFT JOIN product_translations t ON t.product_id=p.id AND t.lang_code='en'
      WHERE p.is_active;
      CREATE OR REPLACE VIEW external_api_images_v WITH(security_barrier=true) AS
        SELECT i.product_id,i.image_url,i.sort_order,i.id FROM product_images i
        JOIN products p ON p.id=i.product_id WHERE p.is_active;
      CREATE OR REPLACE VIEW external_api_sizes_v WITH(security_barrier=true) AS
        SELECT s.product_id,s.size_code,GREATEST(COALESCE(v.stock,0),0) AS stock,s.sort_order,s.id
        FROM product_sizes s JOIN products p ON p.id=s.product_id
        JOIN product_size_prices v ON v.product_id=s.product_id AND v.size_code=s.size_code
        WHERE p.is_active;
    """)
    for view in VIEWS:
        cur.execute(f'REVOKE ALL ON {view} FROM PUBLIC')
    cur.execute("""
    CREATE OR REPLACE FUNCTION revoke_ineligible_api_key() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN
        INSERT INTO api_integration_events(subject_id,key_id,event_code)
          SELECT OLD.id,key_id,'owner_deleted' FROM api_integrations
          WHERE admin_user_id=OLD.id AND token_hash IS NOT NULL;
        RETURN OLD;
      END IF;
      IF NEW.status<>'active' OR NEW.role NOT IN ('admin','sales','warehouse','finance') OR
        NOT ((NEW.permissions IS NULL AND NEW.role='admin') OR COALESCE(NEW.permissions ? 'api-integrations',false)) THEN
        INSERT INTO api_integration_events(subject_id,key_id,event_code)
          SELECT NEW.id,key_id,'owner_access_revoked' FROM api_integrations
          WHERE admin_user_id=NEW.id AND token_hash IS NOT NULL;
        UPDATE api_integrations SET token_hash=NULL,key_id=NULL,enabled=false,
          version=version+1,updated_at=clock_timestamp() WHERE admin_user_id=NEW.id AND token_hash IS NOT NULL;
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION revoke_ineligible_api_key() FROM PUBLIC;
    DROP TRIGGER IF EXISTS admin_user_api_revocation ON admin_users;
    CREATE TRIGGER admin_user_api_revocation AFTER UPDATE OF status,role,permissions ON admin_users
      FOR EACH ROW EXECUTE FUNCTION revoke_ineligible_api_key();
    DROP TRIGGER IF EXISTS admin_user_api_deletion ON admin_users;
    CREATE TRIGGER admin_user_api_deletion BEFORE DELETE ON admin_users
      FOR EACH ROW EXECUTE FUNCTION revoke_ineligible_api_key();
    INSERT INTO security_schema_versions(version) VALUES('external-api-v1'),('external-api-v2') ON CONFLICT DO NOTHING;
    """)
