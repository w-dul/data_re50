#!/usr/bin/env python3
"""Run the three RE strategies on the frozen 50-case sample."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "00_contract"
SOURCES = ROOT / "01_sources"
RESULTS = ROOT / "02_results"
EVIDENCE = ROOT / "03_raw_evidence"
MANIFEST = CONTRACT / "sample_manifest.csv"
RESULTS_CSV = RESULTS / "experiment_results.csv"
RAW_JSONL = EVIDENCE / "raw_results.jsonl"
RUN_METADATA = EVIDENCE / "run_metadata.json"
MODEL = "qwen3.5:9b"
OLLAMA_URL = os.environ.get("RE50_OLLAMA_URL", "http://127.0.0.1:11436")
TIMEOUT = float(os.environ.get("RE50_TIMEOUT", "600"))
WINDOW = 8
MAX_CONTEXT_CHARS = 16000
FIXED_KEYWORDS = ["balance", "call"]

RE_DEFINITION = (
    "Reentrancy (RE) exists when an externally reachable interaction can occur "
    "before a relevant state update, allowing the callee to re-enter the contract "
    "and observe or modify an inconsistent state. The mere presence of balance or "
    "call is not sufficient; judge the interaction order, relevant state reads/writes, "
    "and protection conditions."
)

CSV_FIELDS = [
    "sample_id", "contract_id", "stratum", "physical_loc", "original_label",
    "direct_label", "direct_reason", "direct_evidence_lines", "direct_evidence_text", "direct_status",
    "fixed_rule_candidates", "fixed_rule_label", "fixed_rule_reason",
    "fixed_rule_evidence_lines", "fixed_rule_evidence_text", "fixed_rule_status",
    "llm_keywords", "llm_keyword_candidates", "llm_keyword_label", "llm_keyword_reason",
    "llm_keyword_evidence_lines", "llm_keyword_evidence_text", "llm_keyword_status",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_cases() -> list[dict[str, Any]]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    cases: list[dict[str, Any]] = []
    for row in rows:
        source = ROOT / row["source_file"]
        cases.append({
            "sample_id": row["sample_id"],
            "contract_id": row["contract_id"],
            "stratum": row["stratum"],
            "physical_loc": int(row["physical_loc"]),
            "original_label": int(row["final_label"]),
            "source": source.read_text(encoding="utf-8", errors="replace"),
            "source_sha256": row["source_sha256"],
        })
    return cases


def empty_row(case: dict[str, Any]) -> dict[str, str]:
    row = {field: "" for field in CSV_FIELDS}
    row.update({
        "sample_id": case["sample_id"],
        "contract_id": case["contract_id"],
        "stratum": case["stratum"],
        "physical_loc": str(case["physical_loc"]),
        "original_label": str(case["original_label"]),
        "direct_status": "pending",
        "fixed_rule_status": "pending",
        "llm_keyword_status": "pending",
    })
    return row


def write_table(rows: list[dict[str, str]]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def init_table(cases: list[dict[str, Any]], force: bool = False) -> list[dict[str, str]]:
    if RESULTS_CSV.exists() and not force:
        with RESULTS_CSV.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        return rows
    rows = [empty_row(case) for case in cases]
    write_table(rows)
    return rows


def post_chat(prompt: str) -> tuple[str, float]:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_predict": 512},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL.rstrip("/") + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=TIMEOUT) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    content = str(parsed.get("message", {}).get("content") or "")
    return content, round(time.monotonic() - started, 3)


def parse_json(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)
    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def candidate_windows(source: str, keywords: list[str]) -> tuple[list[int], str, bool]:
    lines = source.splitlines()
    lowered = [line.lower() for line in lines]
    hits = [
        index + 1 for index, line in enumerate(lowered)
        if any(keyword.lower() in line for keyword in keywords if keyword.strip())
    ]
    selected: set[int] = set()
    for hit in hits:
        selected.update(range(max(1, hit - WINDOW), min(len(lines), hit + WINDOW) + 1))
    context = "\n".join(f"{line_no}: {lines[line_no - 1]}" for line_no in sorted(selected))
    truncated = False
    if len(context) > MAX_CONTEXT_CHARS:
        truncated = True
        half = MAX_CONTEXT_CHARS // 2
        context = context[:half] + "\n... [candidate context truncated] ...\n" + context[-half:]
    return hits, context, truncated


def judge_prompt(code: str, *, full_source: bool, method: str) -> str:
    scope = "完整 Solidity 源码" if full_source else "关键词定位得到的候选代码窗口"
    return f"""你是智能合约漏洞审计员。请根据下面固定的 RE 定义，对{scope}进行判断。

RE 定义：{RE_DEFINITION}

实验方法：{method}

要求：
1. 只输出一个 JSON 对象，不要 Markdown 代码块。
2. label 只能是整数 0 或 1。
3. reason 用简短中文说明调用、状态读写顺序和保护条件。
4. evidence_lines 是支持判断的原始源码行号数组；没有可靠证据时返回空数组。
    5. evidence_text 必须是与 evidence_lines 一一对应的源码原文数组，逐字复制，不得改写；每个元素只能包含一行源码，不能包含换行符。

JSON 格式：{{"label": 0, "reason": "...", "evidence_lines": [1], "evidence_text": ["原始源码行"]}}

源码或候选窗口如下：
```solidity
{code}
```
"""


def keyword_prompt(source: str) -> str:
    return f"""你是智能合约漏洞审计员。请根据 RE 定义，从原始 Solidity 源码中生成用于确定性检索的关键词。

RE 定义：{RE_DEFINITION}

要求：
1. 只输出一个 JSON 对象，不要 Markdown 代码块。
2. 只允许输出 keywords 字符串数组，最多 10 个元素。
3. 关键词应是源码中可能出现的字面片段，可包括变量名、函数名或 API 名。
4. 不要输出 label、reason、正则表达式、Cypher、依赖路径或漏洞结论。

JSON 格式：{{"keywords": ["balance", "withdraw"]}}

原始 Solidity 源码：
```solidity
{source}
```
"""


def json_field(payload: dict[str, Any], key: str, default: Any) -> Any:
    value = payload.get(key, default)
    return value


def normalized_judgement(raw: str, elapsed: float, context: bool = False) -> dict[str, Any]:
    parsed = parse_json(raw)
    if parsed is None or parsed.get("label") not in (0, 1):
        return {"status": "parse_failed", "raw": raw, "latency_seconds": elapsed}
    lines = parsed.get("evidence_lines", [])
    texts = parsed.get("evidence_text", [])
    if not isinstance(lines, list):
        lines = []
    if not isinstance(texts, list):
        texts = []
    return {
        "status": "success",
        "label": int(parsed["label"]),
        "reason": str(parsed.get("reason") or ""),
        "evidence_lines": lines,
        "evidence_text": texts,
        "raw": raw,
        "latency_seconds": elapsed,
        "context_truncated": context,
    }


def run_direct(case: dict[str, Any]) -> dict[str, Any]:
    raw, elapsed = post_chat(judge_prompt(case["source"], full_source=True, method="M1 direct"))
    return normalized_judgement(raw, elapsed)


def run_fixed(case: dict[str, Any]) -> dict[str, Any]:
    hits, context, truncated = candidate_windows(case["source"], FIXED_KEYWORDS)
    if not hits:
        return {"status": "no_candidate", "candidate_lines": [], "context_truncated": False}
    raw, elapsed = post_chat(judge_prompt(context, full_source=False, method="M2 fixed balance/call"))
    result = normalized_judgement(raw, elapsed, truncated)
    result.update({"candidate_lines": hits, "keywords": FIXED_KEYWORDS})
    return result


def run_llm_keyword(case: dict[str, Any]) -> dict[str, Any]:
    keyword_raw, keyword_elapsed = post_chat(keyword_prompt(case["source"]))
    parsed = parse_json(keyword_raw)
    keywords = parsed.get("keywords", []) if parsed else []
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(item).strip() for item in keywords if str(item).strip()][:10]
    hits, context, truncated = candidate_windows(case["source"], keywords)
    result: dict[str, Any] = {
        "keywords": keywords,
        "keyword_raw": keyword_raw,
        "keyword_latency_seconds": keyword_elapsed,
        "candidate_lines": hits,
        "context_truncated": truncated,
    }
    if not hits:
        result["status"] = "no_candidate" if parsed is not None else "keyword_parse_failed"
        return result
    judge_raw, judge_elapsed = post_chat(judge_prompt(context, full_source=False, method="M3 LLM keyword"))
    result.update(normalized_judgement(judge_raw, judge_elapsed, truncated))
    result["judge_raw"] = judge_raw
    return result


def result_entry(case: dict[str, Any], method: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": utc_now(), "sample_id": case["sample_id"], "contract_id": case["contract_id"],
        "method": method, "model": MODEL, "ollama_url": OLLAMA_URL,
        "source_sha256": case["source_sha256"], "original_label": case["original_label"],
        "result": result,
    }


def put_row(row: dict[str, str], method: str, result: dict[str, Any]) -> None:
    prefix = {"direct": "direct", "fixed": "fixed_rule", "llm_keyword": "llm_keyword"}[method]
    row[f"{prefix}_status"] = str(result.get("status") or "failed")
    if "label" in result:
        row[f"{prefix}_label"] = str(result["label"])
    row[f"{prefix}_reason"] = str(result.get("reason") or "")
    row[f"{prefix}_evidence_lines"] = json.dumps(result.get("evidence_lines", []), ensure_ascii=False)
    row[f"{prefix}_evidence_text"] = json.dumps(result.get("evidence_text", []), ensure_ascii=False)
    if method == "fixed":
        row["fixed_rule_candidates"] = json.dumps(result.get("candidate_lines", []), ensure_ascii=False)
    if method == "llm_keyword":
        row["llm_keywords"] = json.dumps(result.get("keywords", []), ensure_ascii=False)
        row["llm_keyword_candidates"] = json.dumps(result.get("candidate_lines", []), ensure_ascii=False)


def read_raw_successes() -> dict[tuple[str, str], dict[str, Any]]:
    successes: dict[tuple[str, str], dict[str, Any]] = {}
    if not RAW_JSONL.exists():
        return successes
    for line in RAW_JSONL.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = entry.get("result") or {}
        key = (str(entry.get("sample_id")), str(entry.get("method")))
        if result.get("status") in {"success", "no_candidate"}:
            successes[key] = result
    return successes


def write_metadata() -> None:
    tags: dict[str, Any] = {}
    try:
        request = urllib.request.Request(OLLAMA_URL.rstrip("/") + "/api/tags")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as response:
            tags = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # metadata failure must not hide case-level evidence
        tags = {"error": str(exc)}
    models = [m for m in tags.get("models", []) if m.get("name") == MODEL]
    RUN_METADATA.write_text(json.dumps({
        "schema_version": 1, "started_at": utc_now(), "model": MODEL,
        "ollama_url": OLLAMA_URL, "gpu": "3", "temperature": 0,
        "num_predict": 512, "ollama_format": "json", "protocol_revision": 2,
        "window_lines": WINDOW, "max_context_chars": MAX_CONTEXT_CHARS,
        "fixed_keywords": FIXED_KEYWORDS, "re_definition": RE_DEFINITION,
        "sample_manifest_sha256": sha256(MANIFEST), "model_records": models,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(resume: bool) -> None:
    cases = load_cases()
    rows = init_table(cases)
    by_id = {row["sample_id"]: row for row in rows}
    successes = read_raw_successes() if resume else {}
    write_metadata()
    methods = [("direct", run_direct), ("fixed", run_fixed), ("llm_keyword", run_llm_keyword)]
    with RAW_JSONL.open("a", encoding="utf-8") as raw_handle:
        for case in cases:
            for method, runner in methods:
                key = (case["sample_id"], method)
                if key in successes:
                    put_row(by_id[case["sample_id"]], method, successes[key])
                    continue
                try:
                    result = runner(case)
                except Exception as exc:
                    result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                raw_handle.write(json.dumps(result_entry(case, method, result), ensure_ascii=False) + "\n")
                raw_handle.flush()
                put_row(by_id[case["sample_id"]], method, result)
                write_table(rows)
                print(json.dumps({"sample_id": case["sample_id"], "method": method, "status": result.get("status")}, ensure_ascii=False), flush=True)
    write_table(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="resume successful method/case entries")
    parser.add_argument("--init-only", action="store_true", help="only create the original-label table")
    args = parser.parse_args()
    cases = load_cases()
    init_table(cases)
    if args.init_only:
        print(f"initialized {RESULTS_CSV}")
        return
    run(args.resume)


if __name__ == "__main__":
    main()
