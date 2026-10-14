#!/usr/bin/env bash
set -Eeuo pipefail
# Compatibility CLI only. Upload a verified archive first; this script never
# sources staged shell code, installs dependencies as root, or restores a DB.
release_id="${1:?Release identifier required}"
if [[ "$release_id" == /opt/smawell/incoming/* ]]; then release_id="${release_id##*/}"; fi
[[ "$release_id" =~ ^admin-[1-9][0-9]{0,18}-[1-9][0-9]{0,4}$ ]]
exec sudo -n /usr/local/sbin/gingtto-release deploy admin "$release_id"
