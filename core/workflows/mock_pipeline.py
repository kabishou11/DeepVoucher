from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from core.config.settings import get_settings
from core.knowledge.parsers import search_accounts
from core.rules.accounting import validate_trial_balance
from core.schemas.models import VoucherLine


def run_mock_pipeline(project_root: str | Path, task_meta: dict) -> dict:
    attachments = task_meta["attachments"]
    attachment_ids = [item["attachment_id"] for item in attachments]

    facts = [
        {
            "fact_id": "fact-001",
            "fact_type": "voucher_date_hint",
            "fact_value": "2026-01-31",
            "normalized_value": "2026-01-31",
            "source_attachment_id": attachment_ids[0] if attachment_ids else "",
            "confidence": 0.88,
        },
        {
            "fact_id": "fact-002",
            "fact_type": "amount",
            "fact_value": "100.00",
            "normalized_value": "100.00",
            "source_attachment_id": attachment_ids[0] if attachment_ids else "",
            "confidence": 0.82,
        },
        {
            "fact_id": "fact-003",
            "fact_type": "amount",
            "fact_value": "200.00",
            "normalized_value": "200.00",
            "source_attachment_id": attachment_ids[1] if len(attachment_ids) > 1 else attachment_ids[0] if attachment_ids else "",
            "confidence": 0.8,
        },
    ]

    amount_items = [
        {
            "amount_item_id": "amt-001",
            "purpose": "示例公益支出A",
            "amount": "100.00",
            "direction_hint": "debit",
            "evidence_ids": attachment_ids[:1],
        },
        {
            "amount_item_id": "amt-002",
            "purpose": "示例公益支出B",
            "amount": "200.00",
            "direction_hint": "debit",
            "evidence_ids": attachment_ids[1:2] if len(attachment_ids) > 1 else attachment_ids[:1],
        },
        {
            "amount_item_id": "amt-003",
            "purpose": "示例银行付款",
            "amount": "300.00",
            "direction_hint": "credit",
            "evidence_ids": attachment_ids,
        },
    ]

    debit_primary = _pick_first(search_accounts(project_root, "社区活动", limit=3))
    debit_secondary = _pick_first(search_accounts(project_root, "其他", limit=3))
    credit = _pick_first(search_accounts(project_root, "银行存款 基本户", limit=3))

    posting_candidates = [
        {
            "posting_id": "post-001",
            "summary": "示例公益支出A",
            "amount": "100.00",
            "direction": "debit",
            "account_candidates": [debit_primary] if debit_primary else [],
            "evidence_ids": amount_items[0]["evidence_ids"],
        },
        {
            "posting_id": "post-002",
            "summary": "示例公益支出B",
            "amount": "200.00",
            "direction": "debit",
            "account_candidates": [debit_secondary or debit_primary] if (debit_secondary or debit_primary) else [],
            "evidence_ids": amount_items[1]["evidence_ids"],
        },
        {
            "posting_id": "post-003",
            "summary": "示例银行付款",
            "amount": "300.00",
            "direction": "credit",
            "account_candidates": [credit] if credit else [],
            "evidence_ids": amount_items[2]["evidence_ids"],
        },
    ]

    preview_lines = [
        _to_voucher_line(0, posting_candidates[0], True),
        _to_voucher_line(1, posting_candidates[1], True),
        _to_voucher_line(2, posting_candidates[2], False),
    ]
    trial_balance_ok = validate_trial_balance(preview_lines)

    blockers = []
    if not trial_balance_ok:
        blockers.append(
            {
                "blocker_id": "blk-001",
                "blocker_type": "trial_balance",
                "message": "借贷金额不平衡，不能导出最终 JSON。",
                "target_id": task_meta["task_id"],
            }
        )

    nodes = [
        {
            "id": "ingest_attachments",
            "label": "接收附件",
            "status": "success",
            "summary": f"已接收 {len(attachments)} 张附件",
        },
        {
            "id": "extract_facts_multimodal",
            "label": "多模态事实抽取",
            "status": "success",
            "summary": "当前为 seeded/mock 数据流，用于打通可视化与后续真实模型接入。",
        },
        {
            "id": "split_amount_items",
            "label": "金额单元拆分",
            "status": "success",
            "summary": f"生成 {len(amount_items)} 个金额单元（2 借 1 贷示例）。",
        },
        {
            "id": "retrieve_account_candidates",
            "label": "候选科目召回",
            "status": "warning" if not get_settings().embedding_model_path else "success",
            "summary": "优先走 LanceDB，若不可用则回退到结构化 JSON 搜索。",
        },
        {
            "id": "validate_voucher",
            "label": "凭证校验",
            "status": "success" if trial_balance_ok else "blocked",
            "summary": "借贷平衡校验通过。" if trial_balance_ok else "借贷平衡校验失败。",
        },
    ]

    return {
        "status": "mock_ready" if trial_balance_ok else "blocked",
        "mode": "mock",
        "voucher_date": "2026-01-31",
        "facts": facts,
        "amount_items": amount_items,
        "posting_candidates": posting_candidates,
        "preview_lines": [line.model_dump() for line in preview_lines],
        "blockers": blockers,
        "nodes": nodes,
        "debug": {
            "knowledge_backend": "lancedb-or-json-fallback",
            "attachment_names": [item["file_name"] for item in attachments],
            "note": "下一阶段将以真实 ModelScope 多模态结果替换当前 seeded/mock 数据。",
        },
    }


def _pick_first(items: list[dict]) -> dict | None:
    return items[0] if items else None


def _to_voucher_line(row: int, posting: dict, is_debit: bool) -> VoucherLine:
    candidate = posting["account_candidates"][0] if posting["account_candidates"] else {
        "code": "",
        "path": "",
    }
    amount = Decimal(posting["amount"])
    return VoucherLine(
        row=row,
        zy=posting["summary"],
        kmdm=str(candidate.get("code", "")),
        kmmc=str(candidate.get("path", "")),
        jie=f"{amount:.2f}" if is_debit else "0.00",
        dai="0.00" if is_debit else f"{amount:.2f}",
    )
