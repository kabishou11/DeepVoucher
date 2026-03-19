from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import fitz
import pandas as pd
from lancedb import connect

from core.config.settings import get_settings
from core.rules.accounting import (
    build_children_map,
    account_code_level,
    account_path,
    normalize_account_code,
    parent_account_code,
)


CHAPTER_PATTERN = re.compile(r"^第[一二三四五六七八九十]+章")
ARTICLE_PATTERN = re.compile(r"^第[一二三四五六七八九十百零]+条")
VECTOR_COLUMN = "vector"


def stage_default_assets(project_root: str | Path) -> dict[str, str]:
    root = Path(project_root)
    source_root = root / "ai验证"
    knowledge_raw = root / "knowledge" / "raw"
    reference_dir = root / "reference"
    test_input_dir = root / "test_input"
    ground_truth_dir = root / "ground_truth"

    knowledge_raw.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    test_input_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_dir.mkdir(parents=True, exist_ok=True)

    staged = {
        "institution_pdf": str(
            _copy_if_needed(
                source_root / "农村集体经济组织会计制度.pdf",
                knowledge_raw / "农村集体经济组织会计制度.pdf",
            )
        ),
        "account_chart_xls": str(
            _copy_if_needed(
                source_root / "会计科目表 (1).xls",
                knowledge_raw / "会计科目表 (1).xls",
            )
        ),
        "format_reference_xls": str(
            _copy_if_needed(
                source_root / "凭证列表 (2).xls",
                reference_dir / "凭证列表 (2).xls",
            )
        ),
        "test_input_dir": str(_copy_tree(source_root / "附件", test_input_dir / "附件")),
        "ground_truth_dir": str(_copy_tree(source_root / "正确答案", ground_truth_dir / "正确答案")),
    }
    return staged


def parse_account_chart(xls_path: str | Path) -> list[dict[str, Any]]:
    frame = pd.read_excel(xls_path, header=2)
    frame = frame.dropna(subset=["科目代码", "科目名称"])
    frame["科目代码"] = frame["科目代码"].map(normalize_account_code)
    frame["科目名称"] = frame["科目名称"].astype(str).str.strip()
    frame["科目性质"] = frame["科目性质"].astype(str).str.strip()
    rows = frame.to_dict(orient="records")
    names_by_code = {row["科目代码"]: row["科目名称"] for row in rows}
    children_map = build_children_map(names_by_code.keys())

    parsed: list[dict[str, Any]] = []
    for row in rows:
        code = row["科目代码"]
        parsed.append(
            {
                "code": code,
                "name": row["科目名称"],
                "nature": row["科目性质"],
                "status": str(row.get("状态", "")).strip(),
                "quantity_accounting": str(row.get("数量核算", "")).strip(),
                "auxiliary_accounting": "" if pd.isna(row.get("辅助核算")) else str(row.get("辅助核算")).strip(),
                "level": account_code_level(code),
                "parent_code": parent_account_code(code),
                "is_leaf": len(children_map.get(code, [])) == 0,
                "children_codes": children_map.get(code, []),
                "path": account_path(code, names_by_code),
            }
        )
    return parsed


def parse_institution_pdf(pdf_path: str | Path) -> list[dict[str, Any]]:
    doc = fitz.open(pdf_path)
    chunks: list[dict[str, Any]] = []
    current_chapter = ""
    current_article = ""
    buffer: list[str] = []
    article_page = 1

    def flush() -> None:
        nonlocal buffer, current_article, article_page
        text = "\n".join(buffer).strip()
        if text:
            chunks.append(
                {
                    "chunk_id": f"article-{len(chunks) + 1:04d}",
                    "chapter": current_chapter,
                    "article": current_article,
                    "page": article_page,
                    "text": text,
                }
            )
        buffer = []

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        lines = [line.strip() for line in page.get_text("text").splitlines() if line.strip()]
        for line in lines:
            if CHAPTER_PATTERN.match(line):
                current_chapter = line
                continue
            if ARTICLE_PATTERN.match(line):
                flush()
                current_article = line
                article_page = page_index + 1
            if current_article:
                buffer.append(line)
    flush()
    return chunks


def write_parsed_knowledge(
    project_root: str | Path,
    account_records: list[dict[str, Any]],
    institution_chunks: list[dict[str, Any]],
) -> dict[str, str]:
    root = Path(project_root)
    parsed_dir = root / "knowledge" / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    account_path_file = parsed_dir / "account_chart.json"
    institution_path_file = parsed_dir / "institution_chunks.json"
    manifest_path = parsed_dir / "manifest.json"

    account_path_file.write_text(
        json.dumps(account_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    institution_path_file.write_text(
        json.dumps(institution_chunks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "account_count": len(account_records),
                "institution_chunk_count": len(institution_chunks),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "account_chart_json": str(account_path_file),
        "institution_chunks_json": str(institution_path_file),
        "manifest_json": str(manifest_path),
    }


def build_lancedb_indexes(
    project_root: str | Path,
    account_records: list[dict[str, Any]],
    institution_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = get_settings()
    db_path = Path(project_root) / Path(settings.lancedb_uri)
    db = connect(str(db_path))

    account_rows = [
        {
            "id": row["code"],
            "code": row["code"],
            "name": row["name"],
            "path": row["path"],
            "nature": row["nature"],
            "is_leaf": row["is_leaf"],
            "text": f'{row["code"]} {row["path"]} {row["nature"]}',
        }
        for row in account_records
    ]
    institution_rows = [
        {
            "id": row["chunk_id"],
            "chapter": row["chapter"],
            "article": row["article"],
            "page": row["page"],
            "text": row["text"],
        }
        for row in institution_chunks
    ]

    account_embedding_status = _embedding_runtime_status()
    if account_embedding_status["available"]:
        try:
            account_vectors = _encode_texts([row["text"] for row in account_rows])
        except Exception as exc:
            account_embedding_status = {
                **account_embedding_status,
                "available": False,
                "error": str(exc),
            }
        else:
            for row, vector in zip(account_rows, account_vectors, strict=True):
                row["vector"] = vector
            account_embedding_status = {
                **account_embedding_status,
                "vector_ready": True,
                "dimension": len(account_vectors[0]) if account_vectors else 0,
            }

    try:
        account_table = db.create_table("account_chart", account_rows, mode="overwrite")
        institution_table = db.create_table("institution_chunks", institution_rows, mode="overwrite")
        account_table.create_fts_index("text", replace=True, with_position=True)
        institution_table.create_fts_index("text", replace=True, with_position=True)
        vector_index_ready = False
        vector_index_error = ""
        if account_rows and "vector" in account_rows[0]:
            try:
                account_table.create_index(
                    metric="cosine",
                    vector_column_name="vector",
                    index_type="IVF_FLAT",
                    num_partitions=max(1, min(32, len(account_rows) // 8 or 1)),
                )
                vector_index_ready = True
            except Exception as exc:
                vector_index_error = str(exc)
        return {
            "backend": "lancedb",
            "available": True,
            "tables": ["account_chart", "institution_chunks"],
            "account_rows": len(account_rows),
            "institution_rows": len(institution_rows),
            "error": "",
            "path": str(db_path),
            "vector_ready": vector_index_ready,
            "vector_dimension": account_embedding_status.get("dimension", 0),
            "embedding_backend": account_embedding_status.get("backend", ""),
            "embedding_model_path": account_embedding_status.get("model_path", ""),
            "embedding_error": account_embedding_status.get("error", ""),
            "vector_index_error": vector_index_error,
        }
    except Exception as exc:
        return {
            "backend": "lancedb",
            "available": False,
            "tables": [],
            "account_rows": len(account_rows),
            "institution_rows": len(institution_rows),
            "error": str(exc),
            "path": str(db_path),
            "vector_ready": False,
            "vector_dimension": account_embedding_status.get("dimension", 0),
            "embedding_backend": account_embedding_status.get("backend", ""),
            "embedding_model_path": account_embedding_status.get("model_path", ""),
            "embedding_error": account_embedding_status.get("error", ""),
            "vector_index_error": "",
        }


def bootstrap_knowledge(project_root: str | Path) -> dict[str, Any]:
    staged = stage_default_assets(project_root)
    account_records = parse_account_chart(staged["account_chart_xls"])
    institution_chunks = parse_institution_pdf(staged["institution_pdf"])
    parsed = write_parsed_knowledge(project_root, account_records, institution_chunks)
    indexes = build_lancedb_indexes(project_root, account_records, institution_chunks)
    index_status_path = Path(project_root) / "knowledge" / "parsed" / "index_status.json"
    index_status_path.write_text(json.dumps(indexes, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "staged": staged,
        "parsed": parsed,
        "indexes": indexes,
    }


def knowledge_summary(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    parsed_dir = root / "knowledge" / "parsed"
    manifest_path = parsed_dir / "manifest.json"
    settings = get_settings()
    lancedb_dir = Path(project_root) / Path(settings.lancedb_uri)
    account_chart_path = parsed_dir / "account_chart.json"

    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    index_status = {}
    index_status_path = parsed_dir / "index_status.json"
    if index_status_path.exists():
        index_status = json.loads(index_status_path.read_text(encoding="utf-8"))
    embedding_status = _embedding_runtime_status()

    return {
        "parsed_ready": manifest_path.exists(),
        "manifest": manifest,
        "index_status": index_status,
        "lancedb_path": str(lancedb_dir),
        "lancedb_ready": lancedb_dir.exists(),
        "json_fallback_ready": account_chart_path.exists(),
        "embedding_model_path": settings.embedding_model_path,
        "embedding_model_ready": Path(settings.embedding_model_path).exists(),
        "embedding_runtime_ready": bool(embedding_status.get("available", False)),
        "vector_search_ready": bool(index_status.get("vector_ready", False) and index_status.get("available", False)),
        "search_status": _load_search_status(project_root),
    }


def search_accounts(project_root: str | Path, query: str, limit: int = 10) -> list[dict[str, Any]]:
    results, _status = _search_accounts_with_status(project_root, query, limit)
    return results


def _search_accounts_with_status(
    project_root: str | Path,
    query: str,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = get_settings()
    lancedb_path = Path(project_root) / Path(settings.lancedb_uri)
    fallback_path = Path(project_root) / "knowledge" / "parsed" / "account_chart.json"
    status: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "backend": "lancedb",
        "path": str(lancedb_path),
        "fallback_path": str(fallback_path),
        "available": False,
        "error": "",
        "fts_error": "",
        "vector_error": "",
        "fts_result_count": 0,
        "vector_result_count": 0,
        "result_count": 0,
        "vector_used": False,
        "vector_ready": False,
        "search_mode": "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        db = connect(str(lancedb_path))
        table = db.open_table("account_chart")
        fts_rows: list[dict[str, Any]] = []
        vector_rows: list[dict[str, Any]] = []

        try:
            fts_rows = _run_lancedb_fts_search(table, query, limit=max(limit * 2, limit))
        except Exception as exc:
            status["fts_error"] = str(exc)

        vector_status = _embedding_runtime_status()
        status["vector_ready"] = bool(vector_status.get("available", False))
        if vector_status["available"]:
            try:
                query_vector = _encode_texts([query])[0]
                vector_rows = _run_lancedb_vector_search(table, query_vector, limit=max(limit * 2, limit))
                status["vector_used"] = True
            except Exception as exc:
                status["vector_error"] = str(exc)
        else:
            status["vector_error"] = str(vector_status.get("error", ""))

        status["fts_result_count"] = len(fts_rows)
        status["vector_result_count"] = len(vector_rows)
        merged_rows = _merge_account_search_rows(fts_rows, vector_rows, limit)
        if merged_rows:
            status["available"] = True
            status["result_count"] = len(merged_rows)
            if fts_rows and vector_rows:
                status["backend"] = "lancedb_hybrid"
                status["search_mode"] = "fts_plus_vector"
            elif vector_rows:
                status["backend"] = "lancedb_vector"
                status["search_mode"] = "vector_only"
            else:
                status["backend"] = "lancedb_fts"
                status["search_mode"] = "fts_only"
            _write_search_status(project_root, status)
            return merged_rows, status
    except Exception as exc:
        status["error"] = str(exc)

    status.update(
        {
            "backend": "json_fallback",
            "available": False,
            "search_mode": "json_fallback",
        }
    )
    records = _load_json_account_records(project_root)
    filtered = _score_json_fallback_records(records, query, limit)
    status["result_count"] = len(filtered)
    _write_search_status(project_root, status)
    return filtered, status


def _load_json_account_records(project_root: str | Path) -> list[dict[str, Any]]:
    parsed_path = Path(project_root) / "knowledge" / "parsed" / "account_chart.json"
    if not parsed_path.exists():
        return []
    return json.loads(parsed_path.read_text(encoding="utf-8"))


def _run_lancedb_fts_search(table: Any, query: str, limit: int) -> list[dict[str, Any]]:
    return table.search(query, query_type="fts", fts_columns="text").limit(limit).to_list()


def _run_lancedb_vector_search(table: Any, vector: list[float], limit: int) -> list[dict[str, Any]]:
    return table.search(vector, query_type="vector", vector_column_name="vector").limit(limit).to_list()


def _merge_account_search_rows(
    fts_rows: list[dict[str, Any]],
    vector_rows: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for index, row in enumerate(fts_rows, start=1):
        code = str(row.get("code", "")).strip()
        if not code:
            continue
        entry = merged.setdefault(code, _normalize_account_search_row(row))
        entry.setdefault("search_sources", [])
        if "fts" not in entry["search_sources"]:
            entry["search_sources"].append("fts")
        entry["fts_rank"] = index
        entry["fts_score"] = _safe_float(row.get("_score"))
        entry["retrieval_score"] = float(entry.get("retrieval_score", 0.0)) + max(0.0, 40.0 - index)

    for index, row in enumerate(vector_rows, start=1):
        code = str(row.get("code", "")).strip()
        if not code:
            continue
        entry = merged.setdefault(code, _normalize_account_search_row(row))
        entry.setdefault("search_sources", [])
        if "vector" not in entry["search_sources"]:
            entry["search_sources"].append("vector")
        entry["vector_rank"] = index
        entry["vector_distance"] = _safe_float(row.get("_distance"))
        entry["retrieval_score"] = float(entry.get("retrieval_score", 0.0)) + max(0.0, 40.0 - index)

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            float(item.get("retrieval_score", 0.0)),
            1 if item.get("is_leaf") else 0,
            -int(item.get("vector_rank") or 9999),
            -int(item.get("fts_rank") or 9999),
        ),
        reverse=True,
    )
    return ranked[:limit]


def _normalize_account_search_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "path": row["path"],
        "nature": row["nature"],
        "is_leaf": row["is_leaf"],
        "search_sources": [],
        "fts_rank": None,
        "vector_rank": None,
        "fts_score": None,
        "vector_distance": None,
        "retrieval_score": 0.0,
    }


def _score_json_fallback_records(
    records: list[dict[str, Any]],
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    query_text = str(query).strip().lower()
    if not query_text:
        return []
    tokens = [token for token in re.split(r"\s+", query_text) if token]
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in records:
        code = str(row.get("code", "")).lower()
        name = str(row.get("name", "")).lower()
        path = str(row.get("path", "")).lower()
        text = f"{code} {name} {path}"
        score = 0
        if query_text in code:
            score += 60
        if query_text in name:
            score += 45
        if query_text in path:
            score += 35
        for token in tokens:
            if token in name:
                score += 12
            if token in path:
                score += 8
        if row.get("is_leaf"):
            score += 5
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    **row,
                    "search_sources": ["json_fallback"],
                    "retrieval_score": float(score),
                },
            )
        )
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _embedding_runtime_status() -> dict[str, Any]:
    settings = get_settings()
    model_path = Path(settings.embedding_model_path)
    status = {
        "backend": "sentence_transformers",
        "available": False,
        "model_path": str(model_path),
        "dimension": 0,
        "error": "",
    }
    if not model_path.exists():
        status["error"] = f"Embedding model path not found: {model_path}"
        return status
    try:
        _load_embedding_model(str(model_path))
    except Exception as exc:
        status["error"] = str(exc)
        return status
    status["available"] = True
    return status


def _encode_texts(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    model = _load_embedding_model(str(Path(settings.embedding_model_path)))
    normalized = [text if str(text).strip() else " " for text in texts]
    vectors = model.encode(
        normalized,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return vectors.tolist()


@lru_cache(maxsize=1)
def _load_embedding_model(model_path: str):
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - exercised through runtime status
        raise RuntimeError(
            "sentence-transformers is not installed; install it in the project venv to enable local embeddings."
        ) from exc
    return SentenceTransformer(model_path, device="cpu", trust_remote_code=True)


def _search_status_path(project_root: str | Path) -> Path:
    return Path(project_root) / "knowledge" / "parsed" / "search_status.json"


def _write_search_status(project_root: str | Path, status: dict[str, Any]) -> None:
    status_path = _search_status_path(project_root)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_search_status(project_root: str | Path) -> dict[str, Any]:
    status_path = _search_status_path(project_root)
    if not status_path.exists():
        return {}
    return json.loads(status_path.read_text(encoding="utf-8"))


def _copy_if_needed(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or source.stat().st_mtime > target.stat().st_mtime:
        shutil.copy2(source, target)
    return target


def _copy_tree(source: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            _copy_tree(item, destination)
        else:
            _copy_if_needed(item, destination)
    return target
