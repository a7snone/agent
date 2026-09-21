#!/usr/bin/env bash
# Runs ON THE TARGET SERVER (invoked over SSH by .github/workflows/deploy.yml).
# Idempotent: safe to re-run. Only ever creates/touches files and units it
# owns (prefixed "auth-website"); never edits an existing nginx server block.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$APP_DIR/.venv"
SERVICE_NAME="auth-website"
ENV_FILE="/etc/auth-website.env"
PORT_FILE="/etc/auth-website.port"
OAUTH_TMP="/tmp/auth-website-oauth.env"
DOMAIN_PRIMARY="fractionksa.com"
DOMAIN_WWW="www.fractionksa.com"

echo "==> App dir: $APP_DIR"

# 1. venv + deps
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt" gunicorn

# 2. env file: keep SECRET_KEY stable across deploys, refresh optional Google creds
EXISTING_SECRET=""
if [ -f "$ENV_FILE" ]; then
  EXISTING_SECRET=$(grep -m1 '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- || true)
fi
if [ -z "$EXISTING_SECRET" ]; then
  EXISTING_SECRET=$("$VENV_DIR/bin/python" -c "import secrets; print(secrets.token_hex(32))")
  echo "==> generated new SECRET_KEY"
fi

GOOGLE_ID_LINE=""
GOOGLE_SECRET_LINE=""
if [ -f "$OAUTH_TMP" ]; then
  GOOGLE_ID_LINE=$(grep -m1 '^GOOGLE_CLIENT_ID=' "$OAUTH_TMP" || true)
  GOOGLE_SECRET_LINE=$(grep -m1 '^GOOGLE_CLIENT_SECRET=' "$OAUTH_TMP" || true)
fi

{
  echo "SECRET_KEY=$EXISTING_SECRET"
  [ -n "$GOOGLE_ID_LINE" ] && [ "$GOOGLE_ID_LINE" != "GOOGLE_CLIENT_ID=" ] && echo "$GOOGLE_ID_LINE"
  [ -n "$GOOGLE_SECRET_LINE" ] && [ "$GOOGLE_SECRET_LINE" != "GOOGLE_CLIENT_SECRET=" ] && echo "$GOOGLE_SECRET_LINE"
  true
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
rm -f "$OAUTH_TMP"

# 3. pick (and persist) a free internal port for gunicorn
if [ -f "$PORT_FILE" ]; then
  PORT=$(cat "$PORT_FILE")
else
  PORT=$("$VENV_DIR/bin/python" - <<'PY'
import socket
for p in range(8010, 8100):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", p)) != 0:
            print(p)
            break
PY
)
  echo "$PORT" > "$PORT_FILE"
  echo "==> allocated internal port $PORT"
fi

# 4. systemd unit -- unique name, never touches any other service
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=auth-website (Flask + gunicorn)
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/gunicorn -w 2 -b 127.0.0.1:$PORT app:app
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 1
systemctl --no-pager --lines=5 status "$SERVICE_NAME" || true

# 5. nginx: only add a brand-new server block; never edit an existing one
if command -v nginx >/dev/null 2>&1; then
  if grep -RqsE "$DOMAIN_PRIMARY" /etc/nginx/sites-enabled/ 2>/dev/null; then
    echo "==> WARNING: an nginx config already references $DOMAIN_PRIMARY -- leaving nginx untouched."
    echo "    App is running locally on 127.0.0.1:$PORT. Wire it up manually if you want it public."
  else
    NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}.conf"
    cat > "$NGINX_CONF" <<NGINX
server {
    listen 80;
    server_name $DOMAIN_PRIMARY $DOMAIN_WWW;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
    ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/${SERVICE_NAME}.conf"
    if nginx -t; then
      systemctl reload nginx
      echo "==> nginx server block created for $DOMAIN_PRIMARY -> 127.0.0.1:$PORT"
    else
      echo "==> nginx config test failed -- removing the block we just added, leaving nginx as it was"
      rm -f "$NGINX_CONF" "/etc/nginx/sites-enabled/${SERVICE_NAME}.conf"
    fi
  fi
else
  echo "==> nginx not found on this server -- app is only reachable at 127.0.0.1:$PORT"
fi

echo "==> Deploy finished. Service: $SERVICE_NAME, internal port: $PORT"
