#!/bin/bash
# One-time bootstrap for Let's Encrypt certs, following the standard
# dummy-cert -> nginx up -> real cert -> reload flow. Safe to re-run;
# skips issuance if a real cert already exists.
set -e

DOMAIN="berlanggan.web.id"
EMAIL="rusydani.sh@gmail.com"
DATA_PATH="./certbot"
COMPOSE="docker compose"

if [ -d "$DATA_PATH/conf/live/$DOMAIN" ]; then
  echo "Certificate for $DOMAIN already exists, skipping issuance."
  exit 0
fi

if [ ! -f "$DATA_PATH/conf/ssl-dhparams.pem" ]; then
  echo "Generating dhparams (this takes a minute)..."
  $COMPOSE run --rm --entrypoint "openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048" certbot
fi

echo "Creating dummy certificate for $DOMAIN..."
mkdir -p "$DATA_PATH/conf/live/$DOMAIN"
$COMPOSE run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout '/etc/letsencrypt/live/$DOMAIN/privkey.pem' \
    -out '/etc/letsencrypt/live/$DOMAIN/fullchain.pem' \
    -subj '/CN=localhost'" certbot

echo "Starting nginx with dummy certificate..."
$COMPOSE up -d nginx

echo "Deleting dummy certificate..."
$COMPOSE run --rm --entrypoint "\
  rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

echo "Requesting real certificate for $DOMAIN..."
$COMPOSE run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    --email $EMAIL -d $DOMAIN \
    --rsa-key-size 4096 --agree-tos --non-interactive" certbot

echo "Reloading nginx..."
$COMPOSE exec nginx nginx -s reload

echo "Done. https://$DOMAIN should now be serving a valid certificate."
