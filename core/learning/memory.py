from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def learning_summary(project_root: str | Path) -> dict[str, Any]:
    entries = _load_learning_entries(project_root)
    return {
        "memory_path": str(_learning_memory_path(project_root)),
        "entry_count": len(entries),
        "account_count": len({entry["account_code"] for entry in entries}),
        "last_exported_at": entries[-1]["exported_at"] if entries else "",
    }


def list_learning_entries(project_root: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    entries = list(reversed(_load_learning_entries(project_root)))
    return entries[:limit]


def append_confirmed_export(task_detail: dict, payload: dict, project_root: str | Path) -> list[dict[str, Any]]:
    entries = _load_learning_entries(project_root)
    existing_keys = {
        (entry.get("task_id", ""), int(entry.get("row", -1)), entry.get("account_code", ""))
        for entry in entries
    }

    task = task_detail.get("task", {})
    workflow = task_detail.get("workflow", {})
    posting_candidates = workflow.get("posting_candidates", [])
    attachments = {
        str(item.get("attachment_id", "")): str(item.get("file_name", "")).strip()
        for item in task.get("attachments", [])
    }
    exported_at = datetime.now().isoformat(timespec="seconds")
    body = payload.get("body", {})
    new_entries: list[dict[str, Any]] = []

    for line in body.get("pzks", []):
        row = int(line.get("row", 0))
        amount = str(line.get("jie", "0.00")) if str(line.get("jie", "0.00")) != "0.00" else str(line.get("dai", "0.00"))
        direction = "debit" if str(line.get("jie", "0.00")) != "0.00" else "credit"
        key = (str(task.get("task_id", "")), row, str(line.get("kmdm", "")))
        if not line.get("kmdm") or key in existing_keys:
            continue

        posting = posting_candidates[row] if row < len(posting_candidates) else {}
        evidence_file_names = [
            attachments.get(str(evidence_id), str(evidence_id))
            for evidence_id in posting.get("evidence_ids", [])
            if str(evidence_id).strip()
        ]
        entry = {
            "task_id": str(task.get("task_id", "")),
            "row": row,
            "exported_at": exported_at,
            "voucher_date": str(body.get("dt", "")),
            "summary": str(line.get("zy", "")),
            "summary_key": normalize_summary_key(str(line.get("zy", ""))),
            "summary_keywords": extract_keywords(str(line.get("zy", ""))),
            "direction": direction,
            "account_code": str(line.get("kmdm", "")),
            "account_path": str(line.get("kmmc", "")),
            "amount": amount,
            "amount_bucket": amount_bucket(amount),
            "evidence_file_names": _dedupe_strings(evidence_file_names),
            "evidence_keywords": extract_keywords(" ".join(evidence_file_names)),
        }
        new_entries.append(entry)
        existing_keys.add(key)

    if not new_entries:
        return []

    memory_path = _learning_memory_path(project_root)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    with memory_path.open("a", encoding="utf-8") as handle:
        for entry in new_entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return new_entries


def search_learned_account_hints(
    project_root: str | Path,
    summary: str,
    direction: str,
    amount: str | None = None,
    evidence_file_names: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    summary_key = normalize_summary_key(summary)
    if not summary_key:
        return []
    query_amount_bucket = amount_bucket(amount or "")
    query_evidence_keywords = set(extract_keywords(" ".join(evidence_file_names or [])))

    aggregated: dict[str, dict[str, Any]] = {}
    for entry in _load_learning_entries(project_root):
        if entry.get("direction") != direction:
            continue
        score = _score_summary_match(summary_key, str(entry.get("summary_key", "")))
        if score <= 0:
            continue
        match_factors = [f"summary:{'exact' if score >= 100 else 'fuzzy'}"]

        if query_amount_bucket and query_amount_bucket == str(entry.get("amount_bucket", "")):
            score += 15
            match_factors.append("amount_bucket")

        memory_evidence_keywords = set(entry.get("evidence_keywords", []))
        if query_evidence_keywords and memory_evidence_keywords:
            overlap = sorted(query_evidence_keywords & memory_evidence_keywords)
            if overlap:
                score += min(12, 4 * len(overlap))
                match_factors.append(f"evidence:{'/'.join(overlap[:3])}")

        code = str(entry.get("account_code", ""))
        current = aggregated.get(code)
        candidate = {
            "account_code": code,
            "account_path": str(entry.get("account_path", "")),
            "score": score,
            "match_type": "exact" if score >= 100 else "fuzzy",
            "matched_summaries": [str(entry.get("summary", ""))],
            "evidence_file_names": list(entry.get("evidence_file_names", [])),
            "match_factors": match_factors,
            "last_exported_at": str(entry.get("exported_at", "")),
        }
        if current is None:
            aggregated[code] = candidate
            continue
        current["score"] = max(int(current["score"]), score)
        current["match_type"] = "exact" if current["score"] >= 100 else "fuzzy"
        current["last_exported_at"] = max(str(current["last_exported_at"]), candidate["last_exported_at"])
        current["matched_summaries"] = _dedupe_strings(current["matched_summaries"] + candidate["matched_summaries"])
        current["evidence_file_names"] = _dedupe_strings(current["evidence_file_names"] + candidate["evidence_file_names"])
        current["match_factors"] = _dedupe_strings(current["match_factors"] + candidate["match_factors"])

    ranked = sorted(aggregated.values(), key=lambda item: (int(item["score"]), str(item["last_exported_at"])), reverse=True)
    return ranked[:limit]


def normalize_summary_key(text: str) -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text).strip().lower())
    return normalized


def extract_keywords(text: str) -> list[str]:
    raw = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", str(text).lower())
    preferred = [
        token
        for token in raw
        if token not in {"jpg", "jpeg", "png", "pdf", "微信图片"}
    ]
    return _dedupe_strings(preferred)


def amount_bucket(amount: str) -> str:
    text = str(amount).strip()
    if not text:
        return ""
    value = float(text)
    if value < 100:
        return "lt100"
    if value < 500:
        return "100_499"
    if value < 1000:
        return "500_999"
    if value < 5000:
        return "1000_4999"
    return "5000_plus"


def _score_summary_match(query_key: str, memory_key: str) -> int:
    if not query_key or not memory_key:
        return 0
    if query_key == memory_key:
        return 100
    if query_key in memory_key or memory_key in query_key:
        return 70
    overlap = len(set(query_key) & set(memory_key))
    if overlap >= 4:
        return 40 + overlap
    return 0


def _load_learning_entries(project_root: str | Path) -> list[dict[str, Any]]:
    memory_path = _learning_memory_path(project_root)
    if not memory_path.exists():
        return []

    entries: list[dict[str, Any]] = []
    for line in memory_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        entries.append(json.loads(text))
    return entries


def _learning_memory_path(project_root: str | Path) -> Path:
    return Path(project_root) / "knowledge" / "learned" / "account_memory.jsonl"


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
