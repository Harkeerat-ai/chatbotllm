"""Benchmark legal questions against the RAG pipeline (cold + warm)."""

from __future__ import annotations
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.db import SessionLocal, init_db
from app.seed_service import seed_knowledge
from app.main import app

LEGAL_QUESTIONS = [
    "What is your return policy? How long do I have to return an item?",
    "How long does it take to get a refund after returning an item?",
    "Can I return sale items?",
    "How do I exchange a defective or damaged item?",
    "What personal information do you collect when I purchase?",
    "What payment methods do you use and how is my payment data secured?",
    "How do you use cookies on your website?",
    "How long does shipping take and when will my order be processed?",
    "What are the terms of service for using your website?",
    "Can I modify or cancel my order after placing it?",
    "How can I contact your privacy compliance officer?",
    "What is your policy on returning gift items?",
]

client = TestClient(app)

def benchmark_legal(warm: bool = False) -> list[dict]:
    label = "warm" if warm else "cold"
    results = []
    for question in LEGAL_QUESTIONS:
        payload = {
            "message": question,
            "session_id": f"bench-legal-{label}",
            "top_k": 10,
        }
        t0 = time.monotonic()
        resp = client.post("/api/kalp/chat", json=payload)
        wall = time.monotonic() - t0
        data = resp.json()
        results.append({
            "name": question[:60],
            "warm": warm,
            "api_latency_ms": data.get("latency_ms", 0),
            "wall_clock_s": round(wall, 3),
            "status": resp.status_code,
            "answer": data.get("answer", "")[:80],
            "sources": data.get("sources", []),
        })
        has_legal = any("legal" in s.lower() for s in data.get("sources", []))
        flag = " [LEGAL]" if has_legal else " [NO LEGAL]"
        print(f"  {label:5s} {resp.status_code:3d} "
              f"{data.get('latency_ms', 0):>6}ms "
              f"{wall:>5.2f}s  "
              f"{question[:50]:50s}{flag}")
    return results

def main():
    print("=" * 80)
    print("BENCHMARK: Legal Questions — Cold & Warm")
    print("=" * 80)

    init_db()

    print("\n--- COLD ---")
    cold = benchmark_legal(warm=False)

    print("\n--- WARM ---")
    warm = benchmark_legal(warm=True)

    report = {"cold": cold, "warm": warm}

    out_path = Path(__file__).resolve().parent.parent / "benchmark_results.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nResults saved to {out_path}")

    cold_legal = sum(1 for r in cold if any("legal" in s.lower() for s in r["sources"]))
    warm_legal = sum(1 for r in warm if any("legal" in s.lower() for s in r["sources"]))
    cold_avg = sum(r["api_latency_ms"] for r in cold) / len(cold)
    warm_avg = sum(r["api_latency_ms"] for r in warm) / len(warm)

    print("\n--- SUMMARY ---")
    print(f"  Cold: {cold_legal}/{len(cold)} legal sources found, avg {cold_avg:.0f}ms")
    print(f"  Warm: {warm_legal}/{len(warm)} legal sources found, avg {warm_avg:.0f}ms")

if __name__ == "__main__":
    main()
