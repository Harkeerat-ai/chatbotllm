#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# KALP chatbot — Hostinger VPS provisioner
#
# One-shot setup for a fresh Ubuntu 22.04 VPS. Run as root AFTER:
#   1. You bought the VPS and can SSH in as root.
#   2. You have OpenRouter + HuggingFace keys (see deploy/kalp.env.example).
#   3. You created the Cloudflare DNS "chat" A record (DNS-only / grey cloud)
#      pointing at this VPS's public IP.
#
# Usage (as root):
#   bash provision.sh
#
# This is idempotent-ish: safe to re-run after fixing a step.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config — edit these ──────────────────────────────────────────────────────
DOMAIN="chat.kalp-shop.in"
REPO_URL="https://github.com/Harkeerat-ai/chatbotllm.git"
APP_USER="chatbot"
APP_DIR="/home/${APP_USER}/chatbot"
# ─────────────────────────────────────────────────────────────────────────────

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

# Sanity checks
[[ $EUID -eq 0 ]] || die "Run as root:  sudo bash provision.sh"
command -v curl >/dev/null || die "missing curl"
command -v git  >/dev/null || die "missing git"

log "Updating system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y

log "Installing base packages"
apt-get install -y python3 python3-pip python3-venv git nginx curl certbot python3-certbot-nginx

log "Creating app user: ${APP_USER}"
if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "${APP_USER}"
  usermod -aG sudo "${APP_USER}"
  echo "Created user ${APP_USER}. Set a password with:  passwd ${APP_USER}"
else
  echo "${APP_USER} already exists"
fi

log "Cloning repository"
if [[ ! -d "${APP_DIR}/.git" ]]; then
  git clone "${REPO_URL}" "${APP_DIR}"
  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
else
  echo "Repo already present — updating"
  git -C "${APP_DIR}" pull --ff-only || true
fi

log "Setting up Python venv + dependencies"
sudo -u "${APP_USER}" bash -s <<EOF
set -e
cd "${APP_DIR}"
if [[ ! -d venv ]]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
EOF

log "Environment file — EDIT THIS NOW"
if [[ ! -f "${APP_DIR}/.env" ]]; then
  sudo -u "${APP_USER}" cp "${APP_DIR}/deploy/kalp.env.example" "${APP_DIR}/.env"
  chown "${APP_USER}:${APP_USER}" "${APP_DIR}/.env"
fi
echo "Open ${APP_DIR}/.env and set:"
echo "  ADMIN_PASSWORD, SESSION_SECRET, CSRF_SECRET (generate with: python3 -c \"import secrets;print(secrets.token_urlsafe(48));print(secrets.token_urlsafe(48))\")"
echo "  GROQ_API_KEY (OpenRouter: sk-or-v1-...), HF_API_TOKEN (hf_...)"
read -r -p "Press Enter once you've filled in ${APP_DIR}/.env ..." _
sudo -u "${APP_USER}" bash -c "test -s '${APP_DIR}/.env' || echo 'WARNING: .env is empty'"

log "Installing systemd service"
cp "${APP_DIR}/deploy/chatbot.service" /etc/systemd/system/chatbot.service
systemctl daemon-reload
systemctl enable chatbot || true
systemctl restart chatbot
sleep 3
systemctl --no-pager status chatbot || true

log "Verifying the API is up on localhost:8000"
if curl -fsS http://127.0.0.1:8000/docs >/dev/null; then
  echo "API responding OK on 127.0.0.1:8000"
else
  echo "API not responding yet — check: journalctl -u chatbot -f"
fi

log "Installing Nginx reverse proxy"
rm -f /etc/nginx/sites-enabled/default
cp "${APP_DIR}/deploy/chatbot-nginx.conf" /etc/nginx/sites-available/chatbot
ln -sf /etc/nginx/sites-available/chatbot /etc/nginx/sites-enabled/chatbot
sudo nginx -t
systemctl reload nginx

log "Obtaining Let's Encrypt certificate (must already have Cloudflare DNS record, DNS-only)"
echo "certbot will prompt for an email + ToS acceptance. Complete the prompts."
if ! certbot --nginx -d "${DOMAIN}" --agree-tos --redirect; then
  die "Certbot failed. Confirm the ${DOMAIN} A record exists in Cloudflare (DNS only) and points at this VPS IP."
fi

log "Reloading nginx with certs"
systemctl reload nginx

log "◀ DONE ▶"
echo "Backend live at:  https://${DOMAIN}/docs"
echo "Admin panel at:   https://${DOMAIN}/admin"
echo
echo "Next steps:"
echo "  1. Seed knowledge:  sudo -u ${APP_USER} ${APP_DIR}/venv/bin/python ${APP_DIR}/seed.py"
echo "  2. In WordPress Customizer -> KALP Brand Settings -> Chat Widget, set URL to https://${DOMAIN}"
