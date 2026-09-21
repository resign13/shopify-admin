#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
stage="${1:?Release directory required}"
root=/opt/smawell/shopify-admin
backend=admin-backend
service=smawell-admin-api
exec 9>/var/lock/smawell-deploy.lock
flock -w 600 9
backup="/opt/smawell/backups/actions-admin-$(date -u +%Y%m%dT%H%M%S)-$$"
mkdir -p "$backup"
test -f "$stage/$backend/app.py"
test -f "$stage/frontend/dist/index.html"
test -f "$root/$backend/.env"
# Capture code and configuration; uploaded business data stays in place.
tar --exclude=.venv --exclude=_vendor --exclude=__pycache__ --exclude=uploads --exclude=data -czf "$backup/code.tar.gz" -C "$root" "$backend" frontend/dist scripts
sudo -u postgres pg_dump -Fc smawell_admin > "$backup/database.dump"
sudo -u postgres pg_restore --list < "$backup/database.dump" > /dev/null
# Record balances without customer data so migrations can be checked after release.
stock_snapshot() {
  sudo -u postgres psql -X -d smawell_admin -At -c "SELECT json_build_object(
    'products',(SELECT count(*) FROM products),
    'sizes',(SELECT count(*) FROM product_size_prices),
    'orders',(SELECT count(*) FROM orders),
    'cancelledOrders',(SELECT count(*) FROM orders WHERE status='cancelled'),
    'negativeSizes',(SELECT count(*) FROM product_size_prices WHERE stock<0),
    'productBalances',(SELECT md5(string_agg(id::text||':'||stock::text,',' ORDER BY id)) FROM products),
    'sizeBalances',(SELECT md5(string_agg(id::text||':'||stock::text,',' ORDER BY id)) FROM product_size_prices));"
}
stock_snapshot > "$backup/inventory-before.json"
rollback() {
  status=$?
  trap - ERR
  # Never restart a legacy balance-resetting backend after negative balances exist.
  systemctl stop "$service" || true
  negative=$(sudo -u postgres psql -X -d smawell_admin -At -c "SELECT EXISTS(SELECT 1 FROM products WHERE stock<0) OR EXISTS(SELECT 1 FROM product_size_prices WHERE stock<0)" 2>/dev/null) || negative=unknown
  if ! tar -xOf "$backup/code.tar.gz" "$backend/db.py" | grep 'inventory_policy.migrate(cur)' > /dev/null; then
    if [ "$negative" != f ]; then
      echo "Legacy rollback blocked: negative balances exist or could not be checked. Keeping signed-stock code; database and backup retained at $backup."
      systemctl restart "$service" || true
      exit "$status"
    fi
  fi
  echo "Deployment failed; restoring compatible previous code. Database additions are retained."
  tar -xzf "$backup/code.tar.gz" -C "$root"
  systemctl restart "$service"
  exit "$status"
}
trap rollback ERR
rsync -a --exclude=.env --exclude='.env.*' --exclude=.venv --exclude=_vendor --exclude=uploads --exclude=data --exclude=__pycache__ "$stage/$backend/" "$root/$backend/"
rsync -a "$stage/scripts/" "$root/scripts/"
rsync -a "$stage/db/" "$root/db/"
cd "$root/$backend"
.venv/bin/python -m py_compile app.py db.py inventory_policy.py workbench.py image_delivery.py order_management.py module_permissions.py order_matrix_export.py contracts.py
.venv/bin/pip install --disable-pip-version-check -q -r requirements.txt gunicorn
# Existing initialization applies additive migrations; data is never re-seeded.
.venv/bin/python -c 'import app'
# Keep older hashed assets so already-open browser tabs continue working.
rsync -a "$stage/frontend/dist/assets/" "$root/frontend/dist/assets/"
rsync -a --exclude=index.html --exclude=assets "$stage/frontend/dist/" "$root/frontend/dist/"
install -m 644 "$stage/frontend/dist/index.html" "$root/frontend/dist/index.html.next"
mv "$root/frontend/dist/index.html.next" "$root/frontend/dist/index.html"
systemctl restart "$service"
for attempt in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:5302/api/health" > /dev/null; then
    systemctl is-active --quiet "$service"
    stock_snapshot > "$backup/inventory-after.json"
    echo "Inventory before release: $(cat "$backup/inventory-before.json")"
    echo "Inventory after release: $(cat "$backup/inventory-after.json")"
    .venv/bin/python report_legacy_cancelled_inventory.py --output "$backup/legacy-cancelled-inventory.csv"
    trap - ERR
    echo "Deployment healthy. Backup: $backup"
    exit 0
  fi
  sleep 2
done
false
