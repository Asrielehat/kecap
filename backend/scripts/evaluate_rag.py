"""Offline retrieval baseline; optional answer annotations measure citation correctness.

No provider calls, API keys, user database or uploaded files are read by this script.
--predictions accepts [{question, cited_chunk_ids, correct_citation_count,
                       citation_count, latency_ms, cost_cny}] from a manually reviewed run.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rag.lexical import bm25

parser = argparse.ArgumentParser()
parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parents[1] / "evaluation/study_qa.json")
parser.add_argument("--output", type=Path, default=Path("evaluation-report.json"))
parser.add_argument("--predictions", type=Path)
args = parser.parse_args()
dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
results = []
for case in dataset["questions"]:
    started = time.perf_counter()
    hits = bm25(case["question"], dataset["corpus"], 3)
    actual, expected = {h["chunk_id"] for h in hits}, set(case["expected"])
    results.append({**case, "retrieved": sorted(actual),
                    "recall_at_3": len(actual & expected) / len(expected) if expected else None,
                    "correct_empty": not actual if not expected else None,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3)})
positive = [r for r in results if r["expected"]]
negative = [r for r in results if not r["expected"]]
summary = {"mode": "offline_bm25_only", "questions": len(results),
           "recall_at_3": sum(r["recall_at_3"] for r in positive) / len(positive),
           "correct_empty_rate": sum(r["correct_empty"] for r in negative) / len(negative),
           "mean_latency_ms": sum(r["latency_ms"] for r in results) / len(results),
           "provider_calls": 0, "provider_cost_cny": 0, "citation_accuracy": None,
           "note": "Offline retrieval metrics do not establish answer quality or gains over semantic retrieval."}
if args.predictions:
    annotations = json.loads(args.predictions.read_text(encoding="utf-8"))
    count = sum(p["citation_count"] for p in annotations)
    summary["citation_accuracy"] = sum(p["correct_citation_count"] for p in annotations) / count if count else None
    summary["annotated_answer_cost_cny"] = sum(p["cost_cny"] for p in annotations)
    summary["annotated_answer_mean_latency_ms"] = sum(p["latency_ms"] for p in annotations) / max(1, len(annotations))
args.output.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
