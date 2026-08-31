# KALP Chatbot — Hostinger VPS Deployment (OpenRouter + HuggingFace)

This is the complete manual for standing up the KALP chatbot backend on your own
Hostinger VPS. The WordPress site stays on your existing shared hosting; the VPS
runs only the FastAPI + ChromaDB bot. The answer model is **OpenRouter**
(`meta-llama/llama-3.3-70b-instruct`); embeddings are **HuggingFace**
(`all-MiniLM-L6-v2`).

Most steps are automated by `deploy/provision.sh`; this doc explains each part
so you understand what it does and can fix issues.

---

## Phase 0 — Buy the VPS
1. hostinger.com -> **Hosting -> VPS**.
2. Pick the **KVM 1** plan (1 vCPU, 1 GB RAM — plenty, because the LLM runs in
   the cloud, not on your VPS).
3. OS: **Ubuntu 22.04 LTS**.
4. After purchase Hostinger emails the **root IP**, **password**, and a temp
   root password.
5. Note your **public VPS IP** — you will use it for Cloudflare.

> Your existing WordPress stays on Hostinger shared hosting. Do NOT cancel it.

---

## Phase 1 — First SSH login
From your Windows machine (PowerShell / Windows Terminal):

```
ssh root@YOUR_VPS_IP
```

Enter the root password Hostinger gave you. Then change it:

```
passwd
```

---

## Phase 2 — Automated base setup
The fastest path is the bundled provisioner. Copy your repo to the VPS (run
from your local machine):

```
scp -r C:\Users\Harkeerat Bhasin\OneDrive\Desktop\chatbotllm root@YOUR_VPS_IP:/root/chatbotllm
```

Then on the VPS:

```
cd /root/chatbotllm
bash deploy/provision.sh
```

The script will pause for you to fill in `~/.env` (see Phase 4) and to have the
Cloudflare DNS record ready (Phase 7, before certbot runs).

If you prefer to run it manually instead, follow the mapping below.

---

## Phase 3 — Manual alternative: get the code
As root:

```
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git nginx curl certbot python3-certbot-nginx

useradd -m -s /bin/bash chatbot
usermod -aG sudo chatbot
passwd chatbot   # set the app user's password

su - chatbot
git clone https://github.com/Harkeerat-ai/chatbotllm.git chatbot
cd chatbot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Phase 4 — Environment file (`.env`)
Copy the template and fill it in:

```
cp deploy/kalp.env.example .env
nano .env
```

Generate random secrets:

```
python3 -c "import secrets; print(secrets.token_urlsafe(48)); print(secrets.token_urlsafe(48))"
```

Fill in at minimum:
- `ADMIN_PASSWORD` — strong admin panel password
- `SESSION_SECRET` + `CSRF_SECRET` — the two random strings
- `GROQ_API_KEY` — your **OpenRouter** key (`sk-or-v1-...`)
- `HF_API_TOKEN` — your HuggingFace read token (`hf_...`)

`GROQ_*` names are legacy in the code but are just the OpenAI-compatible
provider slot — they work with OpenRouter unchanged.

---

## Phase 5 — Local smoke test
```
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```
curl -X POST http://127.0.0.1:8000/api/kalp/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What flavours do you have?","session_id":"test"}'
```

Expect an answer (may say "I don't know" until you ingest knowledge). If your
`knowledge/kalp/` files are already populated, run the seeder first:

```
python seed.py
```

Stop the server with Ctrl+C.

---

## Phase 6 — Run as a service
Install the unit and start it:

```
sudo cp /home/chatbot/chatbot/deploy/chatbot.service /etc/systemd/system/chatbot.service
sudo systemctl daemon-reload
sudo systemctl enable chatbot
sudo systemctl start chatbot
sudo systemctl status chatbot        # active (running)
```

Seed knowledge now (must run as the app user so it writes to the right paths):

```
sudo -u chatbot /home/chatbot/chatbot/venv/bin/python /home/chatbot/chatbot/seed.py
```

---

## Phase 7 — Cloudflare DNS + Nginx + HTTPS

### 7a. Cloudflare DNS record
Cloudflare dashboard -> DNS -> Records -> Add record:
- **Type**: A
- **Name**: `chat`
- **IPv4**: your VPS public IP
- **Proxy status**: **DNS only (grey cloud)**  ← critical

Wait 1–2 minutes for propagation. Because the record is DNS-only, Let's Encrypt
can reach your Nginx directly to issue the certificate.

> If you ever enable the orange (proxied) cloud, put Cloudflare SSL/TLS mode on
> **Full (strict)** — the origin serves your Let's Encrypt cert.

### 7b. Install Nginx config
```
sudo cp /home/chatbot/chatbot/deploy/chatbot-nginx.conf /etc/nginx/sites-available/chatbot
sudo ln -sf /etc/nginx/sites-available/chatbot /etc/nginx/sites-enabled/chatbot
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### 7c. Get the certificate
```
sudo certbot --nginx -d chat.kalp-shop.in --agree-tos --redirect
```

Follow the prompts (email). It configures the cert and the HTTP→HTTPS redirect
automatically.

### 7d. Verify
Visit **https://chat.kalp-shop.in/docs** — you should see the FastAPI docs over
HTTPS.

---

## Phase 8 — Wire into WordPress
1. kalp-shop.in -> wp-admin -> **Appearance -> Customize -> KALP Brand Settings
   -> Chat Widget**
2. URL: **`https://chat.kalp-shop.in`** (no trailing slash)
3. Brand slug: `kalp`
4. **Save & Publish** — the placeholder disappears, the real widget appears.

---

## Phase 9 — Brand & config the widget
1. Visit **https://chat.kalp-shop.in/admin**
2. Log in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`
3. KALP brand -> **Widget Config**:
   - Colors: gold `#C9A84C`, brown `#1A0A03`, cream `#FFF8EE`
   - Welcome: "Hi! Ask me about KALP flavours, orders, or anything."
   - Language: `en`
4. Save.

---

## Adding more brands (same one backend)

This one VPS backend is multi-brand. Each brand gets its own API routes
(`/api/{brand_slug}/...`), its own ChromaDB collection, and its own widget
config/colors. Serving KALP + Vitnrich + Pranada from the single VPS.

**Brand slugs used:** `kalp` (kalp-shop.in, WordPress), `vitnrichchocolate`
(vitnrich.com, Shopify), `pranada` (pranadabiopharma.com, WordPress).

### 1. CORS (the only config edit that matters)
CORS is **global**, not per-brand (`CORS_ORIGINS` in `.env`, main.py). All three
custom domains must be listed:

```
CORS_ORIGINS=["https://kalp-shop.in","https://chat.kalp-shop.in","https://vitnrich.com","https://pranadabiopharma.com"]
```

After editing `.env`: `sudo systemctl restart chatbot`.

### 2. Create + brand each brand in the admin panel
`https://chat.kalp-shop.in/admin` → create Brand per slug → set per-brand
colors / welcome / language.

### 3. Ingest each brand's knowledge
Per-brand collection → either use the admin panel's per-brand ingest, or add
files under `knowledge/<slug>/` (e.g. `knowledge/vitnrichchocolate/faq.json`)
then re-run `seed.py`.

### 4. Per-site embed snippet (platform-specific)
The snippet reads `data-brand`, so the same backend serves whichever origin
embeds it.

**kalp (WordPress Customizer):** no snippet needed — use Customize → KALP Brand
Settings → Chat Widget → URL + slug `kalp`.

**Vitnrich (Shopify):** Admin → Online Store → Themes → Edit code →
`theme.liquid` → paste before `</body>`:
```html
<script src="https://chat.kalp-shop.in/widget.js" data-brand="vitnrichchocolate" defer></script>
```

**Pranada (WordPress / Elementor):** simplest is a WPCode ("Insert Headers and
Footers") snippet added site-wide, or the theme's `footer.php`:
```html
<script src="https://chat.kalp-shop.in/widget.js" data-brand="pranada" defer></script>
```

> **pranada caveat:** confirmed the site is WordPress (Elementor/Divi) and its
> `<title>` still shows a staging origin (`*.projectstack.in`). The widget origin
> in CORS must match the **custom domain** (`https://pranadabiopharma.com`)
> visitors actually use — fix the site's live URL before embedding.

---

## Component map
| Component            | Where                            |
|----------------------|----------------------------------|
| Answer model         | OpenRouter (cloud) `llama-3.3-70b-instruct` |
| Embeddings           | HuggingFace (cloud) `all-MiniLM-L6-v2` |
| Reranker             | Local ONNX (auto-download, no key) |
| Backend API          | Hostinger VPS (FastAPI + SQLite + ChromaDB) |
| kalp-shop.in         | WordPress, widget via Customizer (slug `kalp`) |
| vitnrich.com         | Shopify, widget via theme.liquid (slug `vitnrichchocolate`) |
| pranadabiopharma.com | WordPress, widget via WPCode/footer (slug `pranada`) |

---

## Troubleshooting
- **Mixed-content blocked in browser widget**: the Customizer URL or DNS still
  serves plain `http`; use the `https://chat.kalp-shop.in` value.
- **Chat returns "I don't know"**: knowledge not ingested — run
  `sudo -u chatbot /home/chatbot/chatbot/venv/bin/python /home/chatbot/chatbot/seed.py`.
- **418/rate limit on OpenRouter**: top up your OpenRouter credit or lower
  `DEFAULT_TOP_K`.
- **Embedding dimension mismatch**: if you ever change `HF_EMBED_MODEL`, delete
  `./vector_db` and re-seed — query vectors must match the ingested ones.
- **Check logs**: `journalctl -u chatbot -f` and `sudo tail -f /var/log/nginx/error.log`.
