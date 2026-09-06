"""Deterministic BM25 baseline for course-scoped hybrid retrieval and offline evaluation."""
import math
import re
from collections import Counter


def tokenize(text):
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.lower())
    return [token for word in words for token in
            ([word] if word.isascii() or len(word) == 1 else [word[i:i + 2] for i in range(len(word) - 1)])]


def bm25(query, documents, top_k=10):
    counts = [Counter(tokenize(d["content"])) for d in documents]
    average = sum(sum(c.values()) for c in counts) / max(1, len(counts)) or 1
    terms = set(tokenize(query))
    frequencies = {t: sum(t in c for c in counts) for t in terms}
    ranked = []
    for doc, count in zip(documents, counts):
        length = sum(count.values())
        score = sum(math.log(1 + (len(counts) - frequencies[t] + .5) / (frequencies[t] + .5)) *
                    count[t] * 2.5 / (count[t] + 1.5 * (.25 + .75 * length / average))
                    for t in terms if count[t])
        if score:
            ranked.append({**doc, "lexical_score": score})
    return sorted(ranked, key=lambda d: d["lexical_score"], reverse=True)[:top_k]


def reciprocal_rank_fusion(*rankings, top_k=10):
    merged = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, 1):
            key = doc["chunk_id"]
            if key not in merged:
                merged[key] = {**doc, "fusion_score": 0, "score": doc.get("score", 0)}
            merged[key]["score"] = max(merged[key]["score"], doc.get("score", 0))
            merged[key]["fusion_score"] += 1 / (60 + rank)
    return sorted(merged.values(), key=lambda d: d["fusion_score"], reverse=True)[:top_k]
