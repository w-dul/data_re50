#!/usr/bin/env python3
"""Summarize the frozen RE-50 experiment table without hiding failures."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "02_results/experiment_results.csv"
SUMMARY = ROOT / "02_results/metrics_summary.csv"
BY_STRATUM = ROOT / "02_results/metrics_by_stratum.csv"


METHODS = {
    "direct": ("direct_label", "direct_status", "直接 Qwen"),
    "fixed_rule": ("fixed_rule_label", "fixed_rule_status", "固定规则 balance/call"),
    "llm_keyword": ("llm_keyword_label", "llm_keyword_status", "LLM keyword 检测"),
}


def prediction(row: dict[str, str], label_col: str, status_col: str) -> int | None:
    if row[label_col] != "":
        return int(row[label_col])
    if row[status_col] == "no_candidate":
        return 0
    return None


def metric_rows(rows: list[dict[str, str]], scope: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for method, (label_col, status_col, display) in METHODS.items():
        scoped = [row for row in rows if scope == "overall" or row["stratum"] == scope]
        pairs = [(int(row["original_label"]), prediction(row, label_col, status_col)) for row in scoped]
        valid = [(truth, pred) for truth, pred in pairs if pred is not None]
        tp = sum(truth == 1 and pred == 1 for truth, pred in valid)
        tn = sum(truth == 0 and pred == 0 for truth, pred in valid)
        fp = sum(truth == 0 and pred == 1 for truth, pred in valid)
        fn = sum(truth == 1 and pred == 0 for truth, pred in valid)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        accuracy = (tp + tn) / len(valid) if valid else 0.0
        denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
        mcc = ((tp * tn - fp * fn) / denominator) if denominator else 0.0
        statuses = Counter(row[status_col] for row in scoped)
        output.append({
            "scope": scope, "method": method, "method_name": display,
            "n_total": len(scoped), "n_valid": len(valid),
            "coverage": round(len(valid) / len(scoped), 4) if scoped else 0.0,
            "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "mcc": round(mcc, 4), "accuracy": round(accuracy, 4),
            "success": statuses.get("success", 0),
            "no_candidate": statuses.get("no_candidate", 0),
            "parse_failed": statuses.get("parse_failed", 0) + statuses.get("keyword_parse_failed", 0),
        })
    return output


def main() -> None:
    with TABLE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    # Preserve the model-reported text before replacing the public evidence
    # columns with source-derived, line-number-verified text.
    for prefix in METHODS:
        reported = f"{prefix}_reported_evidence_text"
        verified = f"{prefix}_verified_evidence_status"
        for row in rows:
            row[reported] = row.get(reported) or row[f"{prefix}_evidence_text"]
            try:
                line_numbers = json.loads(row[f"{prefix}_evidence_lines"] or "[]")
            except json.JSONDecodeError:
                line_numbers = []
            source = (ROOT / f"01_sources/{row['contract_id']}.sol").read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            resolved = [source[line - 1] for line in line_numbers if isinstance(line, int) and 1 <= line <= len(source)]
            row[f"{prefix}_evidence_text"] = json.dumps(resolved, ensure_ascii=False)
            if not line_numbers:
                row[verified] = "empty"
            elif len(resolved) == len(line_numbers):
                row[verified] = "verified"
            else:
                row[verified] = "invalid_line"
    # A no-candidate outcome is an executed non-detection, while parse failures
    # remain unsupported and are represented by a blank prediction.
    for row in rows:
        for label_col, status_col, _ in METHODS.values():
            if row[label_col] == "" and row[status_col] == "no_candidate":
                row[label_col] = "0"
    fields = list(rows[0])
    with TABLE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    overall = metric_rows(rows, "overall")
    strata = [metric_rows(rows, scope) for scope in ("<100", "100-300", ">300")]
    summary_fields = list(overall[0])
    with SUMMARY.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(overall)
    with BY_STRATUM.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        for group in strata:
            writer.writerows(group)

    print(f"wrote {SUMMARY}, {BY_STRATUM}, and refreshed {TABLE}")


if __name__ == "__main__":
    main()
