# KALP Chatbot — GO-LIVE RUNBOOK (one page)

Follow top-to-bottom. Tick each box. Each step lists the command(s) and the
exact sign it worked. Full detail: `HOSTINGER_VPS.md`.

## 0. Prereqs (you, done BEFORE SSH)
- [ ] OpenRouter key: openrouter.ai/keys -> Create -> copy `sk-or-v1-...`
- [ ] HuggingFace token: huggingface.co/settings/tokens -> Read -> `hf_...`
- [ ] Hostinger KVM2 bought (Ubuntu 22.04) — you have IP + root password
- [ ] `chatbotllm` repo is pushed: `git log --oneline -1` shows `3694593`

## 1. SSH in
```
ssh root@YOUR_VPS_IP
passwd                       # set a new root password
```
Went OK: prompt returns, no connection refused.

## 2. Copy repo + one-command setup
FROM your Windows machine (not the VPS):
```
scp -r C:\Users\Harkeerat Bhasin\OneDrive\Desktop\chatbotllm root@YOUR_VPS_IP:/root/chatbotllm
```
THEN on the VPS:
```
cd /root/chatbotllm && bash deploy/provision.sh
```
Went OK: script installs deps, shows `API responding OK on 127.0.0.1:8000`,
certbot completes, prints DONE.

### 2b. The two pauses inside provision.sh
- Pause A — edit `.env`: set ADMIN_PASSWORD, SESSION_SECRET, CSRF_SECRET,
  `GROQ_API_KEY` (sk-or-v1...), `HF_API_TOKEN` (hf_...). Save.
- Pause B — before certbot: **create the Cloudflare DNS record** (next step),
  then press Enter.

## 3. Cloudflare DNS (do while script waits)
- DNS -> Add record: Type **A**, Name **chat**, IPv4 = your VPS IP,
  Proxy status = **DNS only (grey)**.
- Wait 1-2 min. Verify propagation, on your machine:
  ```
  nslookup chat.kalp-shop.in
  ```
  Went OK: it returns your VPS IP.

## 4. Confirm HTTPS is live
Browser -> `https://chat.kalp-shop.in/docs`
Went OK: FastAPI Swagger page loads (no cert warning).

## 5. Seed knowledge
On the VPS:
```
sudo -u chatbot /home/chatbot/chatbot/venv/bin/python /home/chatbot/chatbot/seed.py
```
Went OK: prints ingestion, no traceback.

## 6. Add swap (cheap insurance on 1-2 GB RAM)
On the VPS:
```
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h          # shows Swap: 2G
```

## 7. Verify a real chat round-trip
```
curl -s -X POST https://chat.kalp-shop.in/api/kalp/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What flavours does KALP offer?","session_id":"golang"}' 
```
Went OK: returns JSON with an answer referencing KALP flavours (not an error,
not "I don't know"). If "brand not found" -> admin panel must create `kalp`
first (Phase 9 / admin/brands).

## 8. Wire into kalp-shop.in
- wp-admin -> Customize -> KALP Brand Settings -> Chat Widget
- URL: `https://chat.kalp-shop.in`   Brand slug: `kalp`
- Save & Publish
Went OK: the gold placeholder disappears on kalp-shop.in; launcher opens widget.

## 9. Brand + go
- `https://chat.kalp-shop.in/admin` -> log in -> kalp brand -> widget config:
  gold `#C9A84C`, brown `#1A0A03`, cream `#FFF8EE`, welcome msg, language `en`.
- Test on the live site.

---

## If something fails

| Symptom | Fix |
|---------|-----|
| certbot error during provision | Cloudflare `chat` record not DNS-only, not propagated, or wrong IP. Fix DNS, wait, re-run `bash deploy/provision.sh` (it's idempotent). |
| `brand 'kalp' not found` | create brand `kalp` in admin panel, then re-run seed. |
| chat says "I don't know" | knowledge not ingested -> re-run seed.py (step 5). |
| OpenAI/AML 401 on OpenRouter | wrong/expired `sk-or-v1-...` in `.env`; edit, `systemctl restart chatbot`. |
| widget block / mixed content | Customizer URL must be `https://chat.kalp-shop.in` exactly, no trailing slash. |
| memory pressure | step 6 swap; only upgrade VM if still tight. |
| logs | `journalctl -u chatbot -f` / `sudo tail -f /var/log/nginx/error.log`. |
