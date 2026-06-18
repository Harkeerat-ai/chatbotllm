#!/usr/bin/env python3
"""Simple diagnostic script to inspect Chroma collections and run a sample query."""
import argparse
import pprint
import sys
import os

# Ensure project root is on sys.path so local package imports work when run as a script
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings
from app.chroma_client import get_client, get_collection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", "-b", default="default", help="Brand slug / collection name")
    parser.add_argument("--query", "-q", default="hello", help="Query text to search")
    parser.add_argument("--top_k", "-k", type=int, default=5, help="Number of results to return")
    args = parser.parse_args()

    settings = get_settings()
    print(f"CHROMA_PATH={settings.chroma_path}")

    client = get_client()

    try:
        collection = get_collection(args.brand)
    except Exception as e:
        print("Failed to get or create collection:", e)
        sys.exit(2)

    # best-effort collection count
    try:
        count = collection.count()
    except Exception as e:
        count = None
        print("Could not fetch collection.count():", e)

    print(f"Collection '{args.brand}' count: {count}")

    try:
        results = collection.query(query_texts=[args.query], n_results=args.top_k)
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        print(f"Query returned {len(docs)} documents")
        if docs:
            print("--- First document (snippet) ---")
            print(docs[0][:500])
            print("--- metadata ---")
            pprint.pprint(metas[0] if metas else {})
    except Exception as e:
        print("Query failed:", e)
        sys.exit(3)


if __name__ == "__main__":
    main()
