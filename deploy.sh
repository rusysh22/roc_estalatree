#!/bin/bash
# Redeploy after a code change: pull, rebuild web/worker/beat, wait for the
# app to actually come up, then make nginx re-resolve the "web" container's
# new IP (the upstream block in nginx/conf.d/app.conf resolves the hostname
# once at start/reload and caches it — recreating the web container without
# reloading nginx is what causes a 502 after `git pull` + rebuild).
# Safe to re-run any time, even with nothing new to pull.
set -e

cd "$(dirname "${BASH_SOURCE[0]}")"

DOMAIN="berlanggan.web.id"

if docker info >/dev/null 2>&1; then
  DC="docker compose"
  DOCKER="docker"
else
  DC="sudo docker compose"
  DOCKER="sudo docker"
fi

log() { echo "[deploy $(date '+%H:%M:%S')] $*"; }

if [ -n "$(git status --porcelain)" ]; then
  log "ERROR: uncommitted local changes present, aborting so nothing gets clobbered:"
  git status --short
  exit 1
fi

BEFORE=$(git rev-parse HEAD)
log "Pulling latest code..."
git pull --ff-only
AFTER=$(git rev-parse HEAD)
if [ "$BEFORE" = "$AFTER" ]; then
  log "Already at $AFTER (no new commits) — continuing anyway to verify the stack is healthy."
else
  log "Updated $BEFORE -> $AFTER"
fi

log "Building web/worker/beat images..."
$DC build web worker beat

log "Recreating web/worker/beat containers..."
$DC up -d web worker beat

log "Waiting for the app to come up (migrations + collectstatic + gunicorn boot)..."
WEB_CID=$($DC ps -q web)
UP=""
for i in $(seq 1 30); do
  if $DOCKER exec "$WEB_CID" python -c "
import urllib.request, urllib.error, sys
try:
    code = urllib.request.urlopen('http://localhost:8000/', timeout=2).status
except urllib.error.HTTPError as e:
    code = e.code  # any HTTP response (even 4xx, e.g. DisallowedHost) means gunicorn is up
sys.exit(0 if code < 500 else 1)
" >/dev/null 2>&1; then
    UP=1
    break
  fi
  sleep 2
done
if [ -z "$UP" ]; then
  log "ERROR: web container never came up. Last 50 log lines:"
  $DOCKER logs --tail 50 "$WEB_CID"
  exit 1
fi
log "App is responding inside the container."

log "Reloading nginx so it re-resolves the web container's new IP..."
NGINX_CID=$($DC ps -q nginx)
$DOCKER exec "$NGINX_CID" nginx -t
$DOCKER exec "$NGINX_CID" nginx -s reload

log "Verifying https://$DOMAIN/ end-to-end..."
STATUS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$DOMAIN/" || echo "000")

if [ "$STATUS" -ge 500 ] 2>/dev/null || [ "$STATUS" = "000" ]; then
  log "Still broken after reload (got $STATUS) — falling back to a full nginx restart..."
  $DOCKER restart "$NGINX_CID" >/dev/null
  sleep 2
  STATUS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$DOMAIN/" || echo "000")
fi

if [ "$STATUS" -ge 500 ] 2>/dev/null || [ "$STATUS" = "000" ]; then
  log "ERROR: site still returning $STATUS after nginx restart. Diagnostics:"
  echo "--- web logs ---"; $DOCKER logs --tail 30 "$WEB_CID"
  echo "--- nginx logs ---"; $DOCKER logs --tail 30 "$NGINX_CID"
  exit 1
fi

log "Deploy OK — https://$DOMAIN/ returned $STATUS."
