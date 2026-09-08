from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path


TEP_ROOT = Path(__file__).resolve().parents[4]
DATA_RE = Path(__file__).resolve().parents[1]
DATASET = TEP_ROOT / "04-datasets/dive/splits/DIVE_balanced/dataset"
TASK_MANIFEST = DATASET / "manifests/task_manifest.csv"
SOURCE_MANIFEST = DATASET / "manifests/source_manifest.csv"
CONTRACT = DATA_RE / "00_contract"
SOURCES_OUT = DATA_RE / "01_sources"
SEED = 42
QUOTAS = {
    ("<100", "1"): 8,
    ("<100", "0"): 7,
    ("100-300", "1"): 5,
    ("100-300", "0"): 10,
    (">300", "1"): 12,
    (">300", "0"): 8,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def physical_loc(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def stratum(loc: int) -> str:
    if loc < 100:
        return "<100"
    if loc <= 300:
        return "100-300"
    return ">300"


def load_sources() -> dict[str, dict[str, object]]:
    sources: dict[str, dict[str, object]] = {}
    with SOURCE_MANIFEST.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            cid = row["contractID"].strip()
            path = DATASET / row["source_file"].strip()
            observed = sha256(path)
            expected = row["source_sha256"].strip().lower()
            if observed != expected:
                raise ValueError(f"source hash mismatch: {cid}")
            sources[cid] = {
                "contract_id": cid,
                "source_file": row["source_file"].strip(),
                "source_sha256": observed,
                "source_bytes": int(row["source_bytes"]),
                "source_path": path,
                "physical_loc": physical_loc(path),
            }
    return sources


def main() -> None:
    if (CONTRACT / "sample_manifest.csv").exists() or any(SOURCES_OUT.glob("*.sol")):
        raise FileExistsError(
            f"refusing to overwrite frozen sample; remove outputs only when intentionally re-sampling: {DATA_RE}"
        )

    sources = load_sources()
    pools: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    with TASK_MANIFEST.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["task"].strip().upper() != "RE":
                continue
            cid = row["contractID"].strip()
            if cid not in sources:
                raise ValueError(f"RE case missing from source manifest: {cid}")
            if row["source_sha256"].strip().lower() != sources[cid]["source_sha256"]:
                raise ValueError(f"task/source hash mismatch: {cid}")
            label = row["final_label"].strip()
            item = {
                **sources[cid],
                "task": "RE",
                "final_label": int(label),
                "stratum": stratum(int(sources[cid]["physical_loc"])),
                "label_basis": row.get("label_basis", ""),
                "vote_status": row.get("vote_status", ""),
                "source_manifest": row.get("source_manifest", ""),
            }
            pools[(item["stratum"], label)].append(item)

    rng = random.Random(SEED)
    selected: list[dict[str, object]] = []
    for cell, quota in QUOTAS.items():
        candidates = sorted(pools[cell], key=lambda item: str(item["contract_id"]))
        if len(candidates) < quota:
            raise ValueError(f"insufficient candidates for {cell}: {len(candidates)} < {quota}")
        selected.extend(rng.sample(candidates, quota))
    rng.shuffle(selected)
    if len({str(item["contract_id"]) for item in selected}) != len(selected):
        raise AssertionError("duplicate contract selected")

    CONTRACT.mkdir(exist_ok=True)
    SOURCES_OUT.mkdir(exist_ok=True)
    records: list[dict[str, object]] = []
    for index, item in enumerate(selected, start=1):
        filename = f"{item['contract_id']}.sol"
        shutil.copyfile(item["source_path"], SOURCES_OUT / filename)
        records.append({
            "sample_id": f"re-case-{index:02d}",
            "task": "RE",
            "contract_id": item["contract_id"],
            "final_label": item["final_label"],
            "stratum": item["stratum"],
            "physical_loc": item["physical_loc"],
            "source_file": f"01_sources/{filename}",
            "source_sha256": item["source_sha256"],
            "source_bytes": item["source_bytes"],
            "label_basis": item["label_basis"],
            "vote_status": item["vote_status"],
            "source_manifest": item["source_manifest"],
        })

    fields = list(records[0])
    with (CONTRACT / "sample_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    (CONTRACT / "sample_manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report = {
        "schema_version": 1,
        "dataset": "DIVE_balanced",
        "unit": "contract-vulnerability task case",
        "task": "RE",
        "sample_size": len(records),
        "seed": SEED,
        "stratum_basis": "physical lines in frozen source_file; <100, 100-300, >300",
        "quotas": {f"{s}/label-{label}": quota for (s, label), quota in QUOTAS.items()},
        "stratum_distribution": dict(sorted(Counter(str(row["stratum"]) for row in records).items())),
        "label_distribution": dict(sorted(Counter(str(row["final_label"]) for row in records).items())),
        "cell_distribution": dict(sorted(Counter(f"{row['stratum']}/label-{row['final_label']}" for row in records).items())),
        "input_sha256": {
            "task_manifest": sha256(TASK_MANIFEST),
            "source_manifest": sha256(SOURCE_MANIFEST),
            "sampling_script": sha256(Path(__file__)),
        },
    }
    (CONTRACT / "sampling_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    checks = {
        "sample_size_50": len(records) == 50,
        "unique_contracts": len({row["contract_id"] for row in records}) == 50,
        "labels_25_25": Counter(row["final_label"] for row in records) == Counter({0: 25, 1: 25}),
        "strata_15_15_20": Counter(row["stratum"] for row in records) == Counter({"<100": 15, "100-300": 15, ">300": 20}),
        "cell_quotas": Counter((row["stratum"], str(row["final_label"])) for row in records) == Counter(QUOTAS),
    }
    for row in records:
        copied = DATA_RE / row["source_file"]
        checks[f"hash_{row['contract_id']}"] = sha256(copied) == row["source_sha256"]
    validation = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "sample_manifest_sha256": sha256(CONTRACT / "sample_manifest.csv"),
    }
    (CONTRACT / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": validation["status"], **report}, ensure_ascii=False, sort_keys=True))
    if validation["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
