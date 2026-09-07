# KALP Chatbot — Runbook (Dokploy)

The chatbot runs on a **Hostinger KVM 2 VPS under Dokploy** (Docker Swarm +
Traefik). It is **not** a systemd + nginx deployment.

> The files `provision.sh`, `chatbot.service`, and `chatbot-nginx.conf` in this
> directory describe the **old, superseded** systemd + nginx approach. They are
> not used and will not work against the current server. Kept only for history.

## What is running

| | |
|---|---|
| VPS | `200.234.45.226` (`srv1962056.hstgr.cloud`), Ubuntu 26.04 |
| Public URL | https://chat.kalp-shop.in |
| Dokploy UI | http://200.234.45.226:3000 |
| App | `kalp-chatbot`, built by Nixpacks from `runtime.txt` (Python 3.12) |
| Volume | `kalp-chatbot-data` → `/app/data` |
| TLS | Let's Encrypt via Traefik |

## Day-to-day: deploying a change

1. Push to `main` on `github.com/Harkeerat-ai/chatbotllm` (public — no deploy key).
2. Dokploy UI → `kalp-chatbot` → **Deploy**.

That is the whole loop. No SSH.

## Things that are NOT steps (and used to be)

- **Do not run `seed.py` by hand.** `app/main.py` `lifespan()` calls
  `seed_knowledge(db)` on every startup, scanning `knowledge/<brand_slug>/`.
  Seeding is automatic and idempotent.
- **Do not set `GROQ_API_KEY` to an OpenRouter key.** The LLM client has had
  first-class OpenRouter support since `de3103c`. Set `OPENROUTER_API_KEY`.
  Groq remains only as a fallback when OpenRouter is unset.

## Persistent state — `/app/data`

Everything that must survive a redeploy lives on the volume:

| Path | Holds |
|---|---|
| `/app/data/app.db` | SQLite — brands, admin users, leads, conversations |
| `/app/data/vector_db` | Chroma vector store |
| `/app/data/hf-cache` | Embedding + reranker model weights (~176 MB) |

`DATABASE_URL` uses **four** slashes (`sqlite:////app/data/app.db`). Three makes
it relative and it writes to a non-persistent path.

## `CORS_ORIGINS` controls framing, not just API access

Since `b6a2ef4`, the widget routes derive CSP `frame-ancestors` from
`CORS_ORIGINS`, because `X-Frame-Options` has no allowlist form. Removing an
origin stops that site embedding the widget. All non-widget routes stay
`X-Frame-Options: DENY` + `frame-ancestors 'none'`.

`www.kalp-shop.in` does not need listing — it 301s to the apex before any page
renders.

## Putting the widget on the shop

```html
<script src="https://chat.kalp-shop.in/widget.js"
        data-brand="kalp"
        data-position="bottom-right"></script>
```

Before `</body>` in the theme footer. Then the manual theme deploy:

1. SFTP the theme file to Hostinger
2. Bump `KALP_THEME_VERSION` in `functions.php`
3. LiteSpeed → Toolbox → **Purge All**
4. Cloudflare → **Purge Everything**
5. Verify in Incognito

## Cloudflare

The `chat` A record must be **grey (DNS-only)** while Let's Encrypt runs its
HTTP-01 challenge. Once the cert is issued it can go **orange**. If a renewal
ever fails, go grey, renew, then orange again.

## Health checks

```
curl https://chat.kalp-shop.in/health
curl https://chat.kalp-shop.in/api/kalp/health     # -> chunk_count
curl -X POST https://chat.kalp-shop.in/api/kalp/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What flavours does KALP offer?","session_id":"check"}'
```

If chat returns an API-key error string, `OPENROUTER_API_KEY` is unset in the
Dokploy environment.
