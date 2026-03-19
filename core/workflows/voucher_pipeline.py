from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

from core.exporters.voucher_json import build_voucher_payload
from core.config.settings import get_settings
from core.learning.memory import search_learned_account_hints
from core.knowledge.parsers import search_accounts
from core.llm.extractors import SalesListSplitter
from core.llm.extractors import AttachmentFactExtractor, VoucherPacketSynthesizer
from core.rules.accounting import validate_trial_balance
from core.rules.split_rules import (
    SplitRuleContext,
    SplitRuleRegistry,
    rule_split_current_sales_list,
)
from core.schemas.models import ReviewLineUpdate, VoucherLine
from core.workflows.mock_pipeline import run_mock_pipeline


def run_voucher_pipeline(project_root: str | Path, task_meta: dict) -> dict:
    settings = get_settings()
    if not settings.modelscope_api_key:
        return run_mock_pipeline(project_root, task_meta)

    try:
        attachment_payloads = _extract_attachment_payloads(task_meta)
        packet_synthesis = _synthesize_packet(task_meta, attachment_payloads)
        packet_synthesis = _apply_packet_split_rules(task_meta, attachment_payloads, packet_synthesis)
        facts = _build_facts(attachment_payloads)
        amount_items, amount_notes = _build_amount_items(attachment_payloads, task_meta, packet_synthesis)
        posting_candidates = _build_posting_candidates(project_root, task_meta, amount_items)
        preview_lines = _build_preview_lines(posting_candidates)
        voucher_date = _pick_voucher_date(attachment_payloads, packet_synthesis) or ""
        blockers = _build_blockers(preview_lines, amount_items, amount_notes, voucher_date)
        nodes = _build_nodes(blockers, attachment_payloads, amount_notes)
        return {
            "status": "ready_for_review" if not blockers else "blocked",
            "mode": "modelscope_live",
            "voucher_date": voucher_date,
            "facts": facts,
            "extractions": attachment_payloads,
            "packet_synthesis": packet_synthesis,
            "amount_items": amount_items,
            "posting_candidates": posting_candidates,
            "preview_lines": [line.model_dump() for line in preview_lines],
            "blockers": blockers,
            "review_actions": [],
            "nodes": nodes,
            "debug": {
                "knowledge_backend": "lancedb",
                "attachment_names": [item["file_name"] for item in task_meta["attachments"]],
                "llm_model": settings.modelscope_chat_model,
                "amount_notes": amount_notes,
                "packet_review_notes": packet_synthesis.get("review_notes", []),
                "date_hints": _collect_voucher_date_hints(attachment_payloads, packet_synthesis),
                "rule_trace": packet_synthesis.get("rule_trace", {}),
            },
        }
    except Exception as exc:
        return _build_live_failure_payload(task_meta, settings.modelscope_chat_model, exc)


def _build_live_failure_payload(task_meta: dict, llm_model: str, exc: Exception) -> dict:
    blocker = {
        "blocker_id": "blk-live-extract",
        "blocker_type": "live_extraction_failed",
        "message": f"真实多模态抽取失败：{exc}",
        "target_id": "voucher",
    }
    return {
        "status": "blocked",
        "mode": "live_error",
        "voucher_date": "",
        "facts": [],
        "extractions": [],
        "packet_synthesis": {},
        "amount_items": [],
        "posting_candidates": [],
        "preview_lines": [],
        "blockers": [blocker],
        "review_actions": [],
        "nodes": [
            {
                "id": "ingest_attachments",
                "label": "接收附件",
                "status": "success",
                "summary": f"已接收 {len(task_meta['attachments'])} 张附件。",
            },
            {
                "id": "extract_facts_multimodal",
                "label": "多模态事实抽取",
                "status": "blocked",
                "summary": f"真实抽取失败，已阻断导出并等待人工处理：{exc}",
            },
            {
                "id": "split_amount_items",
                "label": "金额单元拆分",
                "status": "blocked",
                "summary": "由于真实抽取失败，未进入金额拆分。",
            },
            {
                "id": "retrieve_account_candidates",
                "label": "候选科目召回",
                "status": "blocked",
                "summary": "由于真实抽取失败，未进入科目召回。",
            },
            {
                "id": "validate_voucher",
                "label": "凭证校验",
                "status": "blocked",
                "summary": "真实抽取失败，凭证草案未生成。",
            },
        ],
        "debug": {
            "knowledge_backend": "lancedb",
            "attachment_names": [item["file_name"] for item in task_meta["attachments"]],
            "llm_model": llm_model,
            "fallback_reason": str(exc),
        },
    }


def _extract_attachment_payloads(task_meta: dict) -> list[dict]:
    extractor = AttachmentFactExtractor()
    payloads = []
    for attachment in task_meta["attachments"]:
        payloads.append(extractor.extract_from_attachment(attachment))
    return payloads


def _synthesize_packet(task_meta: dict, extractions: list[dict]) -> dict:
    synthesizer = VoucherPacketSynthesizer()
    return synthesizer.synthesize(task_meta["attachments"], extractions)


def _apply_packet_split_rules(task_meta: dict, extractions: list[dict], packet_synthesis: dict) -> dict:
    context = SplitRuleContext(
        task_meta=task_meta,
        extractions=extractions,
        packet_synthesis=packet_synthesis,
        sales_list_splitter=_split_current_sales_list,
    )
    result = SplitRuleRegistry().evaluate(context)
    if result is None:
        return packet_synthesis

    output = _normalize_rule_output(dict(result.output))
    output["rule_trace"] = result.trace
    output["rule_applied"] = result.rule_name
    return output


def _refine_current_sample_split(task_meta: dict, extractions: list[dict], packet_synthesis: dict) -> dict:
    return _apply_packet_split_rules(task_meta, extractions, packet_synthesis)


def _rule_split_current_sales_list(extraction: dict) -> dict | None:
    return rule_split_current_sales_list(extraction)


def _split_current_sales_list(attachment: dict, extraction: dict) -> dict:
    return SalesListSplitter().split(attachment)


def _normalize_rule_output(output: dict) -> dict:
    normalized = dict(output)
    normalized.setdefault("voucher_date_hint", "")
    normalized.setdefault("fdzs_hint", 0)
    normalized["review_notes"] = _dedupe_string_list(normalized.get("review_notes", []))

    for key in ("debit_groups", "credit_groups"):
        groups = []
        for group in normalized.get(key, []):
            normalized_group = dict(group)
            normalized_group.setdefault("summary", "")
            normalized_group.setdefault("amount", "0.00")
            normalized_group.setdefault("account_hint", "")
            normalized_group.setdefault("reason", "")
            normalized_group["evidence_file_names"] = _dedupe_string_list(
                normalized_group.get("evidence_file_names", [])
            )
            groups.append(normalized_group)
        normalized[key] = groups

    return normalized


def _dedupe_string_list(values: list[str] | tuple[str, ...]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _build_facts(extractions: list[dict]) -> list[dict]:
    facts = []
    fact_index = 1
    for extraction in extractions:
        if extraction["voucher_date_hint"]:
            facts.append(
                {
                    "fact_id": f"fact-{fact_index:03d}",
                    "fact_type": "voucher_date_hint",
                    "fact_value": extraction["voucher_date_hint"],
                    "normalized_value": extraction["voucher_date_hint"],
                    "source_attachment_id": extraction["attachment_id"],
                    "confidence": extraction["confidence"],
                }
            )
            fact_index += 1
        for item in extraction["line_items"]:
            facts.append(
                {
                    "fact_id": f"fact-{fact_index:03d}",
                    "fact_type": "line_item_amount",
                    "fact_value": item["description"],
                    "normalized_value": item["amount"],
                    "source_attachment_id": extraction["attachment_id"],
                    "confidence": extraction["confidence"],
                }
            )
            fact_index += 1
    return facts


def _build_amount_items(
    extractions: list[dict],
    task_meta: dict,
    packet_synthesis: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    debit_items: list[dict] = []
    notes: list[dict] = []
    attachment_ids = [item["attachment_id"] for item in task_meta["attachments"]]
    attachment_name_to_id = {item["file_name"]: item["attachment_id"] for item in task_meta["attachments"]}
    total_debit = Decimal("0.00")
    counter = 1

    if packet_synthesis:
        for group in packet_synthesis.get("debit_groups", []):
            amount = Decimal(group["amount"])
            debit_items.append(
                {
                    "amount_item_id": f"amt-{counter:03d}",
                    "purpose": group["summary"],
                    "amount": f"{amount:.2f}",
                    "direction_hint": "debit",
                    "category_hint": group.get("account_hint", ""),
                    "evidence_ids": [
                        attachment_name_to_id[name]
                        for name in group.get("evidence_file_names", [])
                        if name in attachment_name_to_id
                    ]
                    or attachment_ids,
                }
            )
            total_debit += amount
            counter += 1

        credit_groups = packet_synthesis.get("credit_groups", [])
        for group in credit_groups:
            amount = Decimal(group["amount"])
            debit_items.append(
                {
                    "amount_item_id": f"amt-{counter:03d}",
                    "purpose": group["summary"] or "银行付款",
                    "amount": f"{amount:.2f}",
                    "direction_hint": "credit",
                    "category_hint": group.get("account_hint", "银行存款"),
                    "evidence_ids": [
                        attachment_name_to_id[name]
                        for name in group.get("evidence_file_names", [])
                        if name in attachment_name_to_id
                    ]
                    or attachment_ids,
                }
            )
            counter += 1

        if debit_items:
            notes.extend(
                {
                    "attachment_id": "packet",
                    "type": "packet_review_note",
                    "message": note,
                }
                for note in packet_synthesis.get("review_notes", [])
            )
            return debit_items, notes

    for extraction in extractions:
        attachment_sum = Decimal("0.00")
        for item in extraction["line_items"]:
            amount = Decimal(item["amount"])
            if amount <= 0:
                continue
            description = item["description"] or extraction["document_summary"] or extraction["document_type"] or "未命名事项"
            debit_items.append(
                {
                    "amount_item_id": f"amt-{counter:03d}",
                    "purpose": description,
                    "amount": f"{amount:.2f}",
                    "direction_hint": "debit",
                    "category_hint": item.get("category_hint", ""),
                    "evidence_ids": [extraction["attachment_id"]],
                }
            )
            total_debit += amount
            attachment_sum += amount
            counter += 1

        total_hints = [Decimal(item["amount"]) for item in extraction["totals"]]
        if total_hints:
            hinted_total = max(total_hints)
            if hinted_total > attachment_sum:
                residual = hinted_total - attachment_sum
                debit_items.append(
                    {
                        "amount_item_id": f"amt-{counter:03d}",
                        "purpose": f"{extraction['document_summary'] or extraction['document_type'] or '待确认'}剩余金额",
                        "amount": f"{residual:.2f}",
                        "direction_hint": "debit",
                        "category_hint": "待确认",
                        "evidence_ids": [extraction["attachment_id"]],
                        "requires_review": True,
                    }
                )
                notes.append(
                    {
                        "attachment_id": extraction["attachment_id"],
                        "type": "residual_amount",
                        "message": f"图片合计 {hinted_total:.2f} 与已拆分明细 {attachment_sum:.2f} 存在差额 {residual:.2f}。",
                    }
                )
                total_debit += residual
                counter += 1

    if not debit_items:
        totals = [Decimal(item["amount"]) for extraction in extractions for item in extraction["totals"]]
        if totals:
            total = max(totals)
            debit_items.append(
                {
                    "amount_item_id": f"amt-{counter:03d}",
                    "purpose": "待确认业务支出",
                    "amount": f"{total:.2f}",
                    "direction_hint": "debit",
                    "category_hint": "",
                    "evidence_ids": attachment_ids[:1],
                }
            )
            total_debit += total
            counter += 1

    if total_debit > 0:
        debit_items.append(
            {
                "amount_item_id": f"amt-{counter:03d}",
                "purpose": "银行付款",
                "amount": f"{total_debit:.2f}",
                "direction_hint": "credit",
                "category_hint": "银行存款",
                "evidence_ids": attachment_ids,
            }
        )
    return debit_items, notes


def _build_posting_candidates(project_root: str | Path, task_meta: dict, amount_items: list[dict]) -> list[dict]:
    candidates = []
    attachment_name_map = {
        str(item.get("attachment_id", "")): str(item.get("file_name", "")).strip()
        for item in task_meta.get("attachments", [])
    }
    for index, item in enumerate(amount_items, start=1):
        direction = item["direction_hint"]
        category_hint = item.get("category_hint", "")
        evidence_names = [
            attachment_name_map.get(str(evidence_id), str(evidence_id))
            for evidence_id in item.get("evidence_ids", [])
            if str(evidence_id).strip()
        ]
        search_results, queries, learned_matches, rule_matches = _search_account_candidates(
            project_root,
            item["purpose"],
            category_hint,
            direction,
            item.get("amount", ""),
            evidence_names,
        )
        ranked = _rank_accounts(search_results, item["purpose"], direction, learned_matches, rule_matches)
        candidates.append(
            {
                "posting_id": f"post-{index:03d}",
                "summary": item["purpose"],
                "amount": item["amount"],
                "direction": direction,
                "requires_review": bool(item.get("requires_review", False)),
                "account_candidates": ranked[:3],
                "evidence_ids": item["evidence_ids"],
                "selection_trace": {
                    "category_hint": category_hint,
                    "queries": queries,
                    "evidence_names": evidence_names,
                    "learned_matches": learned_matches,
                    "rule_matches": rule_matches,
                },
            }
        )
    return candidates


def _search_account_candidates(
    project_root: str | Path,
    purpose: str,
    category_hint: str,
    direction: str,
    amount: str,
    evidence_names: list[str],
) -> tuple[list[dict], list[str], list[dict], list[str]]:
    queries = _prepare_account_queries(purpose, category_hint, direction)
    merged: dict[str, dict] = {}
    for query in queries:
        for item in search_accounts(project_root, query, limit=8):
            if item["code"] not in merged:
                merged[item["code"]] = {**item, "query_hits": [query]}
            else:
                merged[item["code"]].setdefault("query_hits", [])
                if query not in merged[item["code"]]["query_hits"]:
                    merged[item["code"]]["query_hits"].append(query)
    rule_queries = _prepare_rule_hint_queries(purpose, category_hint, direction)
    for query in rule_queries:
        for item in search_accounts(project_root, query, limit=3):
            if item["code"] not in merged:
                merged[item["code"]] = {**item, "query_hits": [], "rule_hits": [query]}
            else:
                merged[item["code"]].setdefault("rule_hits", [])
                if query not in merged[item["code"]]["rule_hits"]:
                    merged[item["code"]]["rule_hits"].append(query)
    learned_matches = search_learned_account_hints(
        project_root,
        purpose,
        direction,
        amount=amount,
        evidence_file_names=evidence_names,
        limit=5,
    )
    for match in learned_matches:
        code = str(match["account_code"])
        if code in merged:
            merged[code].setdefault("learned_hits", [])
            merged[code]["learned_hits"].append(match)
            continue
        merged[code] = {
            "code": code,
            "name": str(match.get("account_path", "")).split("/")[-1],
            "path": str(match.get("account_path", "")),
            "nature": "借" if direction == "debit" else "贷",
            "is_leaf": True,
            "query_hits": [],
            "rule_hits": [],
            "learned_hits": [match],
        }
    return list(merged.values()), queries, learned_matches, rule_queries


def _prepare_account_queries(purpose: str, category_hint: str, direction: str) -> list[str]:
    queries: list[str] = []
    if category_hint:
        queries.append(category_hint)
    if purpose:
        queries.append(purpose)
    purpose_text = f"{purpose} {category_hint}".strip()

    keyword_map = {
        "公厕": ["社区活动", "文教医疗卫生 社区活动支出", "514070404"],
        "厕所": ["社区活动", "文教医疗卫生 社区活动支出", "514070404"],
        "村公厕": ["社区活动", "文教医疗卫生 社区活动支出", "514070404"],
        "马桶": ["村公厕", "514070404"],
        "地漏": ["村公厕", "514070404"],
        "水龙": ["村公厕", "514070404"],
        "皮管": ["村公厕", "514070404"],
        "环境": ["环境整治", "公益支出 环境整治及长效管护 其他", "5140199"],
        "整治": ["环境整治", "公益支出 环境整治及长效管护 其他", "5140199"],
        "环境整治用": ["环境整治", "5140199"],
        "修理配件": ["5140199", "514070404", "公益支出"],
        "修理": ["公益支出 其他"],
        "配件": ["公益支出 其他"],
        "五金": ["公益支出 其他"],
        "材料": ["公益支出 其他"],
        "活动": ["社区活动"],
        "工具": ["公益支出 其他"],
        "电线": ["公益支出 其他"],
    }
    for keyword, expansions in keyword_map.items():
        if keyword in purpose_text:
            queries.extend(expansions)

    if direction == "credit":
        queries.extend(["银行存款 基本户", "银行存款 基本账户", "1020101"])
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = str(query).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _prepare_rule_hint_queries(purpose: str, category_hint: str, direction: str) -> list[str]:
    purpose_text = f"{purpose} {category_hint}".strip()
    hints: list[str] = []
    if any(keyword in purpose_text for keyword in ("村公厕", "公厕", "厕所", "马桶", "地漏", "水龙", "皮管")):
        hints.extend(["514070404", "社区活动"])
    if any(keyword in purpose_text for keyword in ("环境", "整治", "长效管护", "五金", "修理配件")):
        hints.extend(["5140199", "环境整治"])
    if direction == "credit":
        hints.extend(["1020101", "银行存款 基本账户"])
    deduped: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        normalized = str(hint).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _rank_accounts(
    items: list[dict],
    purpose: str,
    direction: str,
    learned_matches: list[dict] | None = None,
    rule_matches: list[str] | None = None,
) -> list[dict]:
    purpose_text = purpose.lower()
    learned_by_code = {
        str(item.get("account_code", "")): item for item in (learned_matches or [])
    }
    rule_match_set = {str(item).strip() for item in (rule_matches or []) if str(item).strip()}
    scored = []
    for item in items:
        score = 0
        score_reasons: list[str] = []
        code = str(item.get("code", ""))
        path = str(item.get("path", "")).lower()
        name = str(item.get("name", "")).lower()
        if item.get("is_leaf"):
            score += 20
            score_reasons.append("末级科目 +20")
        if item.get("nature") == "借" and direction == "debit":
            score += 8
            score_reasons.append("借方方向匹配 +8")
        if item.get("nature") == "贷" and direction == "credit":
            score += 8
            score_reasons.append("贷方方向匹配 +8")
        if purpose_text and purpose_text in path:
            score += 12
            score_reasons.append("摘要命中科目路径 +12")
        if purpose_text and purpose_text in name:
            score += 10
            score_reasons.append("摘要命中科目名称 +10")
        if direction == "credit" and code == "1020101":
            score += 30
            score_reasons.append("贷方优先基本户 +30")
        if "环境整治" in purpose_text and code == "5140199":
            score += 60
            score_reasons.append("环境整治规则命中 5140199 +60")
        if any(keyword in purpose_text for keyword in ("村公厕", "公厕", "厕所")) and code == "514070404":
            score += 60
            score_reasons.append("公厕规则命中 514070404 +60")
        if any(keyword in purpose_text for keyword in ("修理配件", "马桶", "地漏", "水龙", "皮管")) and code == "514070404":
            score += 20
            score_reasons.append("公厕配件关键词强化 +20")
        if "五金配件" in purpose_text and direction == "credit" and code == "1020101":
            score += 20
            score_reasons.append("五金配件付款匹配基本户 +20")
        if "公益支出/环境整治" in str(item.get("path", "")):
            score += 15
            score_reasons.append("环境整治路径偏好 +15")
        if "文教医疗卫生/社区活动支出" in str(item.get("path", "")) and any(
            keyword in purpose_text for keyword in ("村公厕", "公厕", "厕所")
        ):
            score += 20
            score_reasons.append("社区活动支出口径强化 +20")
        if str(item.get("path", "")).endswith("/其他"):
            score += 5
            score_reasons.append("末级其他科目兜底 +5")
        search_sources = {str(source).strip() for source in item.get("search_sources", []) if str(source).strip()}
        if "vector" in search_sources:
            score += 10
            score_reasons.append("向量召回命中 +10")
        if "fts" in search_sources:
            score += 6
            score_reasons.append("全文召回命中 +6")
        if "json_fallback" in search_sources:
            score += 2
            score_reasons.append("结构化兜底召回 +2")
        retrieval_score = float(item.get("retrieval_score", 0.0) or 0.0)
        if retrieval_score > 0:
            bonus = min(12, int(retrieval_score // 10))
            if bonus > 0:
                score += bonus
                score_reasons.append(f"检索融合得分 +{bonus}")
        rule_hits = [hit for hit in item.get("rule_hits", []) if str(hit).strip() in rule_match_set]
        if rule_hits:
            bonus = min(24, 8 * len(rule_hits))
            score += bonus
            score_reasons.append(f"规则提示召回 +{bonus}")
        learned_hit = learned_by_code.get(code)
        if learned_hit:
            learned_score = int(learned_hit.get("score", 0))
            bonus = min(learned_score, 40)
            score += bonus
            score_reasons.append(f"历史已确认样本命中 +{bonus}")
        enriched = {
            **item,
            "score": score,
            "score_reasons": score_reasons,
            "query_hits": item.get("query_hits", []),
            "rule_hits": item.get("rule_hits", []),
            "learned_hits": item.get("learned_hits", []),
        }
        scored.append((score, enriched))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


def _build_preview_lines(postings: list[dict]) -> list[VoucherLine]:
    lines: list[VoucherLine] = []
    for row, posting in enumerate(postings):
        candidate = posting["account_candidates"][0] if posting["account_candidates"] else {}
        amount = Decimal(posting["amount"])
        is_debit = posting["direction"] == "debit"
        lines.append(
            VoucherLine(
                row=row,
                zy=posting["summary"],
                kmdm=str(candidate.get("code", "")),
                kmmc=str(candidate.get("path", "")),
                jie=f"{amount:.2f}" if is_debit else "0.00",
                dai="0.00" if is_debit else f"{amount:.2f}",
            )
        )
    return lines


def _build_blockers(
    preview_lines: list[VoucherLine],
    amount_items: list[dict],
    amount_notes: list[dict],
    voucher_date: str,
) -> list[dict]:
    blockers = []
    if not validate_trial_balance(preview_lines):
        blockers.append(
            {
                "blocker_id": "blk-balance",
                "blocker_type": "trial_balance",
                "message": "借贷金额不平衡，不能导出最终 JSON。",
                "target_id": "voucher",
            }
        )

    for line in preview_lines:
        if not line.kmdm:
            blockers.append(
                {
                    "blocker_id": f"blk-account-{line.row}",
                    "blocker_type": "account_missing",
                    "message": f"第 {line.row + 1} 行未匹配到科目，需要人工确认。",
                "target_id": f"line-{line.row}",
            }
        )

    if not str(voucher_date or "").strip():
        blockers.append(
            {
                "blocker_id": "blk-voucher-date",
                "blocker_type": "voucher_date_missing",
                "message": "凭证日期缺失，需要人工确认后才能导出。",
                "target_id": "voucher",
            }
        )

    for note in amount_notes:
        if note["type"] == "packet_review_note":
            continue
        blockers.append(
            {
                "blocker_id": f"blk-{note['attachment_id']}",
                "blocker_type": note["type"],
                "message": note["message"],
                "target_id": note["attachment_id"],
            }
        )

    debit_count = sum(1 for item in amount_items if item["direction_hint"] == "debit")
    if debit_count == 0:
        blockers.append(
            {
                "blocker_id": "blk-no-debit",
                "blocker_type": "amount_missing",
                "message": "未抽取到可入账的借方金额单元。",
                "target_id": "voucher",
            }
        )
    return blockers


def _build_nodes(blockers: list[dict], extractions: list[dict], amount_notes: list[dict]) -> list[dict]:
    extraction_state = "success" if extractions else "warning"
    split_state = "blocked" if amount_notes else "success"
    validation_state = "blocked" if blockers else "success"
    return [
        {
            "id": "ingest_attachments",
            "label": "接收附件",
            "status": "success",
            "summary": f"已接收 {len(extractions)} 张附件并进入真实抽取流程。",
        },
        {
            "id": "extract_facts_multimodal",
            "label": "多模态事实抽取",
            "status": extraction_state,
            "summary": "通过 ModelScope OpenAI 兼容接口逐张图片抽取 JSON 事实。",
        },
        {
            "id": "split_amount_items",
            "label": "金额单元拆分",
            "status": split_state,
            "summary": "按抽取出的 line_items 构建借方金额单元，并自动补一条贷方银行付款。"
            if not amount_notes
            else "检测到合计与明细差额，已生成待确认剩余金额并阻断放行。",
        },
        {
            "id": "retrieve_account_candidates",
            "label": "候选科目召回",
            "status": "success",
            "summary": "基于 LanceDB 检索并按末级科目、方向与文本命中排序。",
        },
        {
            "id": "validate_voucher",
            "label": "凭证校验",
            "status": validation_state,
            "summary": "校验借贷平衡与科目完整性，若缺科目则进入人工确认。",
        },
    ]


def _pick_voucher_date(extractions: list[dict], packet_synthesis: dict | None = None) -> str | None:
    exact_dates: list[str] = []
    fuzzy_dates: list[str] = []
    if packet_synthesis and packet_synthesis.get("voucher_date_hint"):
        parsed = _normalize_to_month_end(packet_synthesis["voucher_date_hint"])
        if parsed:
            if _is_exact_date_hint(packet_synthesis["voucher_date_hint"]):
                exact_dates.append(parsed)
            else:
                fuzzy_dates.append(parsed)
    for item in extractions:
        if item["voucher_date_hint"]:
            parsed = _normalize_to_month_end(item["voucher_date_hint"])
            if parsed:
                if _is_exact_date_hint(item["voucher_date_hint"]):
                    exact_dates.append(parsed)
                else:
                    fuzzy_dates.append(parsed)
    if exact_dates:
        return sorted(exact_dates)[-1]
    if not fuzzy_dates:
        return None
    return sorted(fuzzy_dates)[-1]


def _collect_voucher_date_hints(extractions: list[dict], packet_synthesis: dict | None = None) -> list[dict]:
    hints: list[dict] = []
    if packet_synthesis and packet_synthesis.get("voucher_date_hint"):
        raw = str(packet_synthesis["voucher_date_hint"])
        hints.append(
            {
                "source": "packet_synthesis",
                "raw": raw,
                "normalized": _normalize_to_month_end(raw) or "",
                "is_exact": _is_exact_date_hint(raw),
            }
        )
    for item in extractions:
        raw = str(item.get("voucher_date_hint", "")).strip()
        if not raw:
            continue
        hints.append(
            {
                "source": item.get("file_name", ""),
                "raw": raw,
                "normalized": _normalize_to_month_end(raw) or "",
                "is_exact": _is_exact_date_hint(raw),
            }
        )
    return hints


def _is_exact_date_hint(value: str) -> bool:
    import re

    text = str(value).strip()
    return bool(re.search(r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}", text))


def _normalize_to_month_end(value: str) -> str | None:
    import calendar
    import re
    from datetime import date

    text = str(value).strip()
    if not text:
        return None
    if any(token in text for token in ("至", "到", "~")) and not re.search(r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}", text):
        return None

    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, last_day).isoformat()

    match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if match:
        today_year = 2026
        month = int(match.group(1))
        last_day = calendar.monthrange(today_year, month)[1]
        return date(today_year, month, last_day).isoformat()
    return None


def apply_review_actions(task_detail: dict, updates: list[ReviewLineUpdate], voucher_date: str | None = None) -> dict:
    workflow = task_detail["workflow"]
    preview_lines = workflow.get("preview_lines", [])
    update_map = {item.row: item for item in updates}
    review_actions = []

    for line in preview_lines:
        row = int(line["row"])
        if row not in update_map:
            continue
        update = update_map[row]
        line["zy"] = update.zy
        line["kmdm"] = update.kmdm
        line["kmmc"] = update.kmmc
        review_actions.append(
            {
                "target_id": f"line-{row}",
                "action": "manual_edit",
                "resolved": bool(update.kmdm),
            }
        )

    if voucher_date is not None:
        workflow["voucher_date"] = str(voucher_date).strip()
        review_actions.append(
            {
                "target_id": "voucher-date",
                "action": "manual_edit",
                "resolved": bool(workflow["voucher_date"]),
            }
        )

    amount_notes = workflow.get("debug", {}).get("amount_notes", [])
    posting_candidates = workflow.get("posting_candidates", [])
    blockers = _rebuild_blockers_from_lines(preview_lines, posting_candidates, amount_notes, workflow.get("voucher_date", ""))
    workflow["blockers"] = blockers
    workflow["review_actions"] = review_actions
    workflow["status"] = "ready_for_export" if not blockers else "blocked"
    for node in workflow.get("nodes", []):
        if node["id"] == "validate_voucher":
            node["status"] = "success" if not blockers else "blocked"
            node["summary"] = "人工确认后校验通过，可导出 JSON。" if not blockers else "人工确认后仍有阻断项，暂不可导出。"
    return workflow


def export_voucher_payload(task_detail: dict) -> dict:
    workflow = task_detail["workflow"]
    if workflow.get("blockers"):
        raise ValueError("Voucher still has blockers.")
    lines = [VoucherLine(**line) for line in workflow.get("preview_lines", [])]
    payload = build_voucher_payload(
        get_settings(),
        workflow.get("voucher_date", ""),
        int(task_detail["task"].get("attachment_count", 0)),
        lines,
    )
    return payload


def _rebuild_blockers_from_lines(
    preview_lines: list[dict],
    posting_candidates: list[dict],
    amount_notes: list[dict],
    voucher_date: str,
) -> list[dict]:
    blockers: list[dict] = []
    lines = [VoucherLine(**line) for line in preview_lines]
    if not validate_trial_balance(lines):
        blockers.append(
            {
                "blocker_id": "blk-balance",
                "blocker_type": "trial_balance",
                "message": "借贷金额不平衡，不能导出最终 JSON。",
                "target_id": "voucher",
            }
        )

    for line in preview_lines:
        if not line.get("kmdm"):
            blockers.append(
                {
                    "blocker_id": f"blk-account-{line['row']}",
                    "blocker_type": "account_missing",
                    "message": f"第 {int(line['row']) + 1} 行未匹配到科目，需要人工确认。",
                "target_id": f"line-{line['row']}",
            }
        )

    if not str(voucher_date or "").strip():
        blockers.append(
            {
                "blocker_id": "blk-voucher-date",
                "blocker_type": "voucher_date_missing",
                "message": "凭证日期缺失，需要人工确认后才能导出。",
                "target_id": "voucher",
            }
        )

    row_requires_review = {
        index: bool(item.get("requires_review", False)) for index, item in enumerate(posting_candidates)
    }
    for line in preview_lines:
        row = int(line["row"])
        if row_requires_review.get(row) and not line.get("kmdm"):
            blockers.append(
                {
                    "blocker_id": f"blk-residual-{row}",
                    "blocker_type": "residual_amount",
                    "message": "该行来自明细与合计差额补齐，需人工确认科目后才能放行。",
                    "target_id": f"line-{row}",
                }
            )

    unresolved_residual = any(
        row_requires_review.get(int(line["row"])) and not line.get("kmdm") for line in preview_lines
    )
    if unresolved_residual:
        for note in amount_notes:
            blockers.append(
                {
                    "blocker_id": f"blk-{note['attachment_id']}",
                    "blocker_type": note["type"],
                    "message": note["message"],
                    "target_id": note["attachment_id"],
                }
            )
    return blockers
