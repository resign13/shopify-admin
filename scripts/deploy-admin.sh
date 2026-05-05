#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/gingtto}"
REPO_DIR="$DEPLOY_ROOT/shopify-admin"
DEPLOY_DIR="$DEPLOY_ROOT/deploy"

echo "[admin] deploying from $REPO_DIR"

cd "$REPO_DIR"
git fetch --all --prune
git reset --hard "origin/${GITHUB_REF_NAME:-main}"

cd "$DEPLOY_DIR"
docker compose build admin-web admin-api
docker compose up -d admin-web admin-api

echo "[admin] deployment finished"
