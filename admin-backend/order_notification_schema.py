"""Shared, additive notification schema. Keep identical in both repositories."""

SCHEMA = r"""
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
"""


def migrate(cur):
    # Startup DDL in the two services is serialized independently of publishing.
    cur.execute('SELECT pg_advisory_xact_lock(7192041)')
    cur.execute(SCHEMA)
