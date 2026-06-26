"""Test rate limiter with parallel requests"""
import requests
import threading
import time

TARGET = "http://localhost:8000"
BRAND = "kalp"
results = []
lock = threading.Lock()

def send_req(i):
    try:
        r = requests.post(f"{TARGET}/api/{BRAND}/chat", json={
            "session_id": "parallel_rate_test", "message": f"x{i}",
        }, timeout=180)
        with lock:
            results.append(r.status_code)
    except Exception as e:
        with lock:
            results.append(0)

threads = []
start = time.time()
for i in range(35):
    t = threading.Thread(target=send_req, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

elapsed = time.time() - start
blocked = results.count(429)
success = results.count(200)
errors = results.count(0)
print(f"Elapsed: {elapsed:.1f}s")
print(f"success={success} blocked={blocked} errors={errors}")
if blocked >= 1:
    print("PASS: Rate limiter blocked requests")
else:
    print("FAIL: Rate limiter did not block")
