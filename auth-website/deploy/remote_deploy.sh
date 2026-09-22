#!/usr/bin/env bash
# Runs ON THE TARGET SERVER (invoked over SSH by .github/workflows/deploy.yml).
# Idempotent: safe to re-run. Only ever creates/touches files and units it
# owns (prefixed "auth-website"). The one exception is an existing nginx
# config for the domain: it gets a marker-bounded /auth/ location added,
# always backed up first and validated with `nginx -t` before reload, with
# an automatic rollback to the backup if that check fails.
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

# 1. venv + deps (rebuild if a prior run left a broken venv without pip)
if [ ! -x "$VENV_DIR/bin/pip" ]; then
  rm -rf "$VENV_DIR"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq python3-venv python3-pip >/dev/null
  fi
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

# 5. nginx: wire the app at $DOMAIN_PRIMARY/auth/
#    - if no config references the domain, create a brand-new server block
#    - if one already exists (this server's case), ADD a marker-bounded
#      location block to it: full backup first, nginx -t before reload,
#      instant rollback to the backup if the test fails. Every other line
#      in that file is left exactly as it was. Re-running updates only the
#      content between the markers (e.g. if the port changes).
if command -v nginx >/dev/null 2>&1; then
  EXISTING_CONF=$(grep -RlsE "$DOMAIN_PRIMARY" /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)

  if [ -z "$EXISTING_CONF" ]; then
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
  else
    # Resolve the symlink so we edit and back up the real file.
    REAL_CONF=$(readlink -f "$EXISTING_CONF")
    echo "==> found existing config for $DOMAIN_PRIMARY: $REAL_CONF -- adding /auth/ location only"
    BACKUP="${REAL_CONF}.bak.$(date +%s)"
    cp -p "$REAL_CONF" "$BACKUP"

    PORT="$PORT" REAL_CONF="$REAL_CONF" "$VENV_DIR/bin/python" - <<'PY'
import os
import re
import sys

path = os.environ["REAL_CONF"]
port = os.environ["PORT"]
begin = "# BEGIN auth-website /auth (managed by deploy/remote_deploy.sh)"
end = "# END auth-website /auth"

with open(path) as f:
    content = f.read()

block = f"""    {begin}
    location = /auth {{
        return 301 /auth/;
    }}

    location /auth/ {{
        proxy_pass http://127.0.0.1:{port}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Script-Name /auth;
    }}
    {end}
"""

if begin in content:
    # Re-deploy: replace only the previously-inserted block (e.g. port changed).
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
    if not pattern.search(content):
        print("marker start found but end marker missing -- refusing to touch the file", file=sys.stderr)
        sys.exit(1)
    new_content = pattern.sub(block, content)
else:
    # First run: insert just before the closing brace of the server{} block
    # that terminates in "listen 443" (falls back to the first server{} if
    # there is no 443 block, e.g. no TLS configured yet).
    idx = content.find("listen 443")
    if idx == -1:
        start = content.find("server {")
    else:
        start = content.rfind("server {", 0, idx)
    if start == -1:
        print("could not find a server {} block to attach to -- aborting", file=sys.stderr)
        sys.exit(1)

    depth = 0
    end_idx = None
    i = start
    while i < len(content):
        c = content[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end_idx = i
                break
        i += 1
    if end_idx is None:
        print("unbalanced braces while locating server {} block -- aborting", file=sys.stderr)
        sys.exit(1)

    new_content = content[:end_idx] + block + content[end_idx:]

with open(path, "w") as f:
    f.write(new_content)
PY

    if [ $? -ne 0 ]; then
      echo "==> ERROR: could not safely edit $REAL_CONF -- left unchanged (backup at $BACKUP, unused)"
      rm -f "$BACKUP"
    elif nginx -t; then
      systemctl reload nginx
      echo "==> added /auth/ -> 127.0.0.1:$PORT to $REAL_CONF (backup: $BACKUP)"
    else
      echo "==> nginx -t failed after editing $REAL_CONF -- restoring the original file"
      cp -p "$BACKUP" "$REAL_CONF"
      nginx -t && systemctl reload nginx
      echo "==> restored. Nothing changed on the live site."
    fi
  fi
else
  echo "==> nginx not found on this server -- app is only reachable at 127.0.0.1:$PORT"
fi

echo "==> Deploy finished. Service: $SERVICE_NAME, internal port: $PORT"
