"""
Live response timing benchmark — hits real server, asserts each < 4 seconds.
Usage:  python scripts/benchmark_live.py
"""
import requests
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

TARGET = "http://localhost:8000"
BRAND = "kalp"

tests = []

def test(name, category, question, expect_status=200, extra=None, brand=BRAND):
    tests.append((name, category, question, expect_status, extra or {}, brand))

# ── FAQ (3) ──
test("KALP brand intro", "FAQ", "What is KALP?")
test("Flavours offered", "FAQ", "What flavours does KALP offer?")
test("Sugar content", "FAQ", "Does KALP contain added sugar?")

# ── Legal (3) ──
test("Return policy", "Legal", "What is your return policy?")
test("Personal info collected", "Legal", "What personal information do you collect when I purchase?")
test("Shipping policy", "Legal", "What is your domestic shipping policy?")

# ── Go-to-link (3) ──
test("Shahi Gulab page", "Go-to-link", "Tell me about Shahi Gulab")
test("Royal Rajbhog page", "Go-to-link", "Tell me about Royal Rajbhog")
test("Nawabi Paan page", "Go-to-link", "Tell me about Nawabi Paan")

# ── Tracking (3) ──
test("Track KALP-1001", "Tracking", "Where is my order KALP-1001?")
test("Track TRK-KALP-1001", "Tracking", "What is the status of TRK-KALP-1001?")
test("Track kalp-1001 lower", "Tracking", "Track order kalp-1001")

# ── Edge cases ──
test("Empty message", "Edge", "", 422)
test("XSS attempt", "Edge", "<script>alert(1)</script>")
test("Very long session_id", "Edge", "hello", 200, extra={"session_id": "a" * 200})
test("Non-existent brand", "Edge", "hello", 404, brand="nonexistent")

results = []
all_under_4s = True

print()
print("=" * 72)
print("  LIVE RESPONSE TIMING BENCHMARK")
print(f"  Target: {TARGET}/api/{{brand}}/chat")
print("  Threshold: < 4.0 seconds per response")
print("=" * 72)
print()

# Warmup: discard the first request (cold-start cache miss on Groq)
print("  Warming up (sending first query to warm Groq cache)... ", end="", flush=True)
try:
    requests.post(f"{TARGET}/api/{BRAND}/chat", json={
        "message": "warmup", "session_id": "__warmup__",
    }, timeout=120)
    print("done")
except Exception:
    print("warmup failed, continuing anyway")
print()

for name, cat, question, expect, extra, brand in tests:
    payload = {"message": question, "session_id": "bench-live"}
    if extra:
        payload.update(extra)
    url = f"{TARGET}/api/{brand}/chat"
    t0 = time.monotonic()
    try:
        r = requests.post(url, json=payload, timeout=120)
    except requests.exceptions.Timeout:
        elapsed = time.monotonic() - t0
        results.append((name, cat, elapsed, "TIMEOUT"))
        all_under_4s = False
        print(f"  [TIMEOUT] {cat:12s} {name:<30s}  {elapsed:>6.1f}s")
        continue
    except requests.exceptions.ConnectionError as e:
        elapsed = time.monotonic() - t0
        results.append((name, cat, elapsed, "CONN_ERROR"))
        all_under_4s = False
        print(f"  [CONN_ERR] {cat:12s} {name:<30s}  {elapsed:>6.1f}s  {e}")
        continue
    elapsed = time.monotonic() - t0
    status_ok = r.status_code == expect
    under_4s = elapsed < 4.0
    if not status_ok:
        all_under_4s = False
    if not under_4s:
        all_under_4s = False

    if status_ok and under_4s:
        status_tag = "PASS"
    elif not status_ok and under_4s:
        status_tag = f"STATUS({r.status_code} != {expect})"
    elif status_ok and not under_4s:
        status_tag = "SLOW"
    else:
        status_tag = f"FAIL({r.status_code} != {expect}, {elapsed:.1f}s)"

    print(f"  [{status_tag:7s}] "
          f"{cat:12s} {name:<30s}  "
          f"{elapsed:>5.2f}s"
          f"{'  *** SLOW ***' if not under_4s and status_ok else ''}"
          f"{'  *** WRONG STATUS ***' if not status_ok else ''}")
    results.append((name, cat, elapsed, r.status_code, expect, under_4s, status_ok))

# ── Concurrent edge case: 5 rapid requests ──
print()
print("--- Concurrent burst: 5 rapid requests ---")
def fire(i):
    try:
        t0 = time.monotonic()
        r = requests.post(f"{TARGET}/api/{BRAND}/chat", json={
            "message": "What is KALP?",
            "session_id": f"burst-live",
        }, timeout=120)
        t = time.monotonic() - t0
        return i, t, r.status_code
    except Exception as e:
        return i, -1, 0

concurrent_results = []
with ThreadPoolExecutor(max_workers=5) as ex:
    futures = [ex.submit(fire, i) for i in range(5)]
    for f in as_completed(futures):
        i, t, code = f.result()
        concurrent_results.append((i, t, code))
        ok = t < 4.0 and code == 200
        if not ok:
            all_under_4s = False
        print(f"    [{ 'PASS' if ok else 'FAIL' }] "
              f"Request {i}: {t:.2f}s (HTTP {code})"
              f"{'  *** SLOW ***' if t >= 4.0 else ''}")

# ── Summary ──
pass_count = sum(1 for *_, under, ok in results if under and ok)
total = len(results)
print()
print("=" * 72)
print(f"  RESULTS: {pass_count}/{total} single tests under 4.0s")
print(f"          {'ALL UNDER 4s' if all_under_4s else 'SOME EXCEEDED 4s'}")
print("=" * 72)
print()

if not all_under_4s:
    print("  Slowest tests:")
    for name, cat, elapsed, status, expect, under, ok in sorted(results, key=lambda x: x[2], reverse=True)[:5]:
        print(f"    {cat:12s} {name:<30s}  {elapsed:.2f}s")
    sys.exit(1 if all_under_4s is not None else 0)
