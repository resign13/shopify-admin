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
rollback() {
  status=$?
  trap - ERR
  echo "Deployment failed; restoring previous code. Database additions are retained."
  tar -xzf "$backup/code.tar.gz" -C "$root"
  systemctl restart "$service"
  exit "$status"
}
trap rollback ERR
rsync -a --exclude=.env --exclude='.env.*' --exclude=.venv --exclude=_vendor --exclude=uploads --exclude=data --exclude=__pycache__ "$stage/$backend/" "$root/$backend/"
rsync -a "$stage/scripts/" "$root/scripts/"
rsync -a "$stage/db/" "$root/db/"
cd "$root/$backend"
.venv/bin/python -m py_compile app.py db.py workbench.py image_delivery.py order_management.py module_permissions.py
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
    trap - ERR
    echo "Deployment healthy. Backup: $backup"
    exit 0
  fi
  sleep 2
done
false
