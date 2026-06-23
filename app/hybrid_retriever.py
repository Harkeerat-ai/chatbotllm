from __future__ import annotations
import math
import re
import threading
from collections import Counter
from typing import NamedTuple

import app.chroma_client as chroma_client

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


class ScoredDoc(NamedTuple):
    score: float
    document: str
    metadata: dict


class BM25Index:
    def __init__(self, documents: list[str], metadatas: list[dict], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents = documents
        self.metadatas = metadatas
        self.n_docs = len(documents)
        self.avgdl = 0.0
        self.doc_lens: list[int] = []
        self.idf: dict[str, float] = {}
        self.doc_terms: list[Counter] = []
        self._build()

    def _tokenize(self, text: str) -> list[str]:
        return _TOKEN_RE.findall(text.lower())

    def _build(self) -> None:
        self.doc_terms = []
        self.doc_lens = []
        df: Counter = Counter()
        for doc in self.documents:
            tokens = self._tokenize(doc)
            self.doc_terms.append(Counter(tokens))
            self.doc_lens.append(len(tokens))
            df.update(set(tokens))
        self.avgdl = sum(self.doc_lens) / max(self.n_docs, 1)
        n = self.n_docs
        for term, freq in df.items():
            self.idf[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)

    def score(self, query: str) -> list[float]:
        query_terms = self._tokenize(query)
        if not query_terms:
            return [0.0] * self.n_docs
        scores = [0.0] * self.n_docs
        for i in range(self.n_docs):
            s = 0.0
            doc_len = self.doc_lens[i]
            term_counts = self.doc_terms[i]
            for term in query_terms:
                tf = term_counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self.idf.get(term, 0.0)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                s += idf * numerator / denominator
            scores[i] = s
        return scores


def _rrf(ranked_lists: list[list[int]], k: int = 60) -> dict[int, float]:
    rrf_scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, doc_idx in enumerate(ranked):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + 1.0 / (k + rank + 1)
    max_score = max(rrf_scores.values()) if rrf_scores else 1.0
    return {idx: score / max_score for idx, score in rrf_scores.items()}


class HybridRetriever:
    def __init__(self, brand_slug: str):
        self.brand_slug = brand_slug
        self._lock = threading.Lock()
        self._bm25: BM25Index | None = None
        self._last_doc_count: int = 0

    def rebuild(self) -> None:
        coll = chroma_client.get_collection(self.brand_slug)
        all_data = coll.get(include=["documents", "metadatas"])
        docs = all_data.get("documents", []) or []
        metas = all_data.get("metadatas", []) or []
        with self._lock:
            self._bm25 = BM25Index(docs, metas)
            self._last_doc_count = len(docs)

    def needs_rebuild(self) -> bool:
        coll = chroma_client.get_collection(self.brand_slug)
        current_count = coll.count()
        return current_count != self._last_doc_count

    def hybrid_query(
        self,
        query: str,
        top_k: int = 10,
        vector_weight: float = 0.5,
    ) -> list[ScoredDoc]:
        coll = chroma_client.get_collection(self.brand_slug)

        if self.needs_rebuild():
            self.rebuild()

        vector_results = coll.query(query_texts=[query], n_results=top_k)
        vec_docs = vector_results.get("documents", [[]])[0]
        vec_metas = vector_results.get("metadatas", [[]])[0]

        if not vec_docs:
            return []

        if self._bm25 and self._bm25.n_docs > 0:
            bm25_scores = self._bm25.score(query)
            all_docs_data = coll.get(include=["documents"])
            all_docs = all_docs_data.get("documents", []) or []

            # Map each vector result to its position in all_docs (common index space)
            vec_positions = []
            for d in vec_docs:
                try:
                    vec_positions.append(all_docs.index(d))
                except ValueError:
                    vec_positions.append(-1)

            vec_ranked = [idx for idx in vec_positions if idx >= 0][:top_k]
            bm25_ranked = sorted(range(self._bm25.n_docs), key=lambda i: bm25_scores[i], reverse=True)[:top_k]

            rrf_scores = _rrf([vec_ranked, bm25_ranked])

            scored = [
                (rrf_scores.get(vec_positions[i], 0.0), vec_docs[i], vec_metas[i])
                for i in range(len(vec_docs))
                if vec_positions[i] >= 0
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            return [ScoredDoc(s, d, m) for s, d, m in scored]
        else:
            return [ScoredDoc(1.0, d, m) for d, m in zip(vec_docs, vec_metas)][:top_k]


_retrievers: dict[str, HybridRetriever] = {}
_retriever_lock = threading.Lock()


def get_hybrid_retriever(brand_slug: str) -> HybridRetriever:
    with _retriever_lock:
        if brand_slug not in _retrievers:
            _retrievers[brand_slug] = HybridRetriever(brand_slug)
            _retrievers[brand_slug].rebuild()
        return _retrievers[brand_slug]


def invalidate_retriever(brand_slug: str) -> None:
    with _retriever_lock:
        if brand_slug in _retrievers:
            del _retrievers[brand_slug]
