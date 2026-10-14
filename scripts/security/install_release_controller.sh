#!/usr/bin/env bash
# Explicit operator preparation only. Never called by a release archive or CI.
set -Eeuo pipefail
[[ "${1:-}" == --install && $# == 1 && $EUID == 0 ]]
umask 077
source_dir="$(cd -- "$(dirname -- "$0")" && pwd -P)"
for user in gingtto-build gingtto-admin gingtto-store gingtto-maintenance; do
  if ! getent group "$user" >/dev/null; then groupadd --system "$user"; fi
  if ! id "$user" >/dev/null 2>&1; then
    useradd --system --gid "$user" --no-create-home --shell /usr/sbin/nologin "$user"
  fi
done
if ! id gingtto-deploy >/dev/null 2>&1; then
  useradd --create-home --user-group --home-dir /var/lib/gingtto-deploy --shell /bin/bash gingtto-deploy
fi
install -d -o root -g root -m 755 /usr/local/lib/gingtto-release /etc/gingtto /etc/gingtto/runtime /etc/gingtto/rollback
install -d -o root -g root -m 700 /var/lib/gingtto-release
install -d -o root -g root -m 755 /opt/smawell /opt/smawell/releases /opt/smawell/current /opt/smawell/public-assets
install -d -o root -g root -m 755 /opt/smawell/private-files
install -d -o gingtto-admin -g gingtto-admin -m 750 /opt/smawell/private-files/admin
install -d -o gingtto-store -g gingtto-store -m 750 /opt/smawell/private-files/store
install -d -o gingtto-deploy -g gingtto-deploy -m 700 /opt/smawell/incoming
install -d -o gingtto-deploy -g gingtto-deploy -m 700 /var/lib/gingtto-deploy/.ssh
install -o root -g root -m 644 "$source_dir/release_control.py" "$source_dir/build_release.py" /usr/local/lib/gingtto-release/
install -o root -g root -m 755 "$source_dir/gingtto-release" /usr/local/sbin/gingtto-release
candidate=/etc/sudoers.d/.gingtto-release.next
install -o root -g root -m 440 "$source_dir/gingtto-release.sudoers.example" "$candidate"
visudo -cf "$candidate"
mv -f -- "$candidate" /etc/sudoers.d/gingtto-release
# Check identities without exposing configuration or changing business accounts.
/usr/bin/python3 -I -c 'import sys; sys.path.insert(0,"/usr/local/lib/gingtto-release"); from release_control import Config,Files,SystemOps; c=Config(); SystemOps(c,Files(c)).principals()'
echo 'Controller prepared. Runtime configs, file ownership, units, schema, fallback releases and SSH acceptance remain explicit operator steps.'
