from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.config.settings import get_settings
from core.knowledge.indexer import knowledge_summary


def build_readiness_report(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    settings = get_settings()
    knowledge = knowledge_summary(root)

    checks = [
        _build_check(
            key="env_file",
            label=".env 配置",
            ok=(root / ".env").exists(),
            detail="检测根目录 `.env` 是否存在。",
        ),
        _build_check(
            key="modelscope_api_key",
            label="ModelScope API",
            ok=bool(settings.modelscope_api_key),
            detail="检测是否已配置真实 ModelScope Token。",
        ),
        _build_check(
            key="embedding_model_path",
            label="本地 Embedding 模型",
            ok=bool(knowledge.get("embedding_model_ready")),
            detail=f"检测 `EMBEDDING_MODEL_PATH` 是否存在：{settings.embedding_model_path}",
        ),
        _build_check(
            key="embedding_runtime",
            label="Embedding 运行时",
            ok=bool(knowledge.get("embedding_runtime_ready")),
            detail="检测 `sentence-transformers` 等本地向量运行时是否可用。",
        ),
        _build_check(
            key="knowledge_parsed",
            label="知识解析产物",
            ok=bool(knowledge.get("parsed_ready")),
            detail="检测 `knowledge/parsed` 是否已生成。",
        ),
        _build_check(
            key="vector_search",
            label="向量检索",
            ok=bool(knowledge.get("vector_search_ready")),
            detail="检测 LanceDB + embedding 是否已经进入真实召回链路。",
        ),
        _build_check(
            key="web_workspace",
            label="前端工程",
            ok=(root / "apps" / "web" / "package.json").exists(),
            detail="检测前端工程目录是否完整。",
        ),
        _build_check(
            key="regression_script",
            label="回归脚本",
            ok=(root / "scripts" / "run_current_sample_regression.py").exists(),
            detail="检测当前样本真实回归脚本是否存在。",
        ),
    ]

    overall_ok = all(check["ok"] for check in checks)
    blockers = [check["label"] for check in checks if not check["ok"]]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "overall_status": "ready" if overall_ok else "needs_attention",
        "blockers": blockers,
        "checks": checks,
        "knowledge": {
            "parsed_ready": knowledge.get("parsed_ready", False),
            "vector_search_ready": knowledge.get("vector_search_ready", False),
            "search_status": knowledge.get("search_status", {}),
            "index_status": knowledge.get("index_status", {}),
        },
        "recommended_commands": [
            r".\venv\Scripts\python.exe -m pytest -q",
            r"$env:PYTHONPATH='.'; .\venv\Scripts\python.exe .\scripts\run_current_sample_regression.py",
            r"pnpm --filter voucher-auto-entry-web build",
        ],
    }


def _build_check(*, key: str, label: str, ok: bool, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "ok": ok,
        "status": "ready" if ok else "missing",
        "detail": detail,
    }
