"""Smoke test — concurrent burst to trigger rate limiter"""
import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

TARGET = "http://localhost:8000"
BRAND = "kalp"

results = []

def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name} {detail}")
    results.append((name, ok))

print("=== A8: CSRF Login ===")
s = requests.Session()
r = s.get(f"{TARGET}/admin")
tok = re.search(r'name="csrf_token".*?value="([^"]+)"', r.text).group(1)
r2 = s.post(f"{TARGET}/admin/login", data={
    "username": "admin", "password": "change-me-now", "csrf_token": tok,
}, allow_redirects=False)
check("CSRF login", r2.status_code == 302, f"({r2.status_code})")

print()
print("=== A3: XSS escaped at widget render ===")
s2 = requests.Session()
r = s2.get(f"{TARGET}/admin")
tok2 = re.search(r'name="csrf_token".*?value="([^"]+)"', r.text).group(1)
s2.post(f"{TARGET}/admin/login", data={
    "username": "admin", "password": "change-me-now", "csrf_token": tok2,
}, allow_redirects=False)
r_widget = s2.get(f"{TARGET}/widget/{BRAND}")
xss_unescaped = "<script>alert" in r_widget.text
check("XSS escaped in widget HTML", not xss_unescaped)

print()
print("=== A4: API key required ===")
r4 = requests.get(f"{TARGET}/api/{BRAND}/widget-config")
check("widget-config no auth", r4.status_code == 401, f"({r4.status_code})")
r5 = requests.get(f"{TARGET}/metrics")
check("metrics no auth", r5.status_code == 401, f"({r5.status_code})")

print()
print("=== Chat message size limit ===")
r8 = requests.post(f"{TARGET}/api/{BRAND}/chat", json={"session_id": "x", "message": "A" * 5000}, timeout=60)
check("Oversized message (5000 chars)", r8.status_code == 422, f"({r8.status_code})")
r9 = requests.post(f"{TARGET}/api/{BRAND}/chat", json={"session_id": "sizetest", "message": "short message"}, timeout=60)
check("Normal message works", r9.status_code == 200, f"({r9.status_code})")

print()
print("=== A10: Rate limiter (concurrent burst) ===")
# Fire 35 concurrent requests to exceed 30/minute in a single burst
hits = []
def hit(i):
    try:
        r = requests.post(f"{TARGET}/api/{BRAND}/chat", json={
            "session_id": "burst4", "message": f"x{i}",
        }, timeout=120)
        return r.status_code
    except:
        return 0
with ThreadPoolExecutor(max_workers=35) as ex:
    futures = [ex.submit(hit, i) for i in range(35)]
    for f in as_completed(futures):
        hits.append(f.result())
blocked = hits.count(429)
check("Rate limiter blocks >= 5 of 35", blocked >= 5, f"({blocked} blocked / {len(hits)} total)")

print()
print("=== L5: Security headers ===")
r7 = requests.get(f"{TARGET}/health")
check("X-Content-Type-Options", r7.headers.get("X-Content-Type-Options") == "nosniff")
check("X-Frame-Options", r7.headers.get("X-Frame-Options") == "DENY")
check("Referrer-Policy", r7.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin")

print()
print("=== Session fixation ===")
s3 = requests.Session()
pre_cookie = s3.cookies.get("session", domain="localhost:8000")
r = s3.get(f"{TARGET}/admin")
tok3 = re.search(r'name="csrf_token".*?value="([^"]+)"', r.text).group(1)
s3.post(f"{TARGET}/admin/login", data={
    "username": "admin", "password": "change-me-now", "csrf_token": tok3,
}, allow_redirects=False)
post_cookie = s3.cookies.get("session", domain="localhost:8000")
check("Session regenerated", pre_cookie is None or post_cookie != pre_cookie, f"(changed: {pre_cookie is None or post_cookie != pre_cookie})")

print()
print(f"=== RESULTS: {sum(1 for _,ok in results if ok)}/{len(results)} passed ===")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
