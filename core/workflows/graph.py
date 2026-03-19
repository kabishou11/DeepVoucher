from __future__ import annotations


def build_workflow_overview() -> dict[str, list[dict[str, str]]]:
    nodes = [
        {"id": "create_task", "label": "创建任务", "kind": "system"},
        {"id": "ingest_attachments", "label": "接收附件", "kind": "system"},
        {"id": "preprocess_images", "label": "图片预处理", "kind": "system"},
        {"id": "extract_facts_multimodal", "label": "多模态事实抽取", "kind": "model"},
        {"id": "normalize_facts", "label": "事实标准化", "kind": "system"},
        {"id": "merge_evidence", "label": "证据归并", "kind": "system"},
        {"id": "split_amount_items", "label": "金额单元拆分", "kind": "rule"},
        {"id": "retrieve_account_candidates", "label": "候选科目召回", "kind": "knowledge"},
        {"id": "rank_leaf_accounts", "label": "末级科目过滤", "kind": "rule"},
        {"id": "validate_voucher", "label": "凭证校验", "kind": "rule"},
        {"id": "human_review", "label": "人工确认", "kind": "review"},
        {"id": "export_json", "label": "导出 JSON", "kind": "system"},
    ]
    edges = [
        {"from": "create_task", "to": "ingest_attachments"},
        {"from": "ingest_attachments", "to": "preprocess_images"},
        {"from": "preprocess_images", "to": "extract_facts_multimodal"},
        {"from": "extract_facts_multimodal", "to": "normalize_facts"},
        {"from": "normalize_facts", "to": "merge_evidence"},
        {"from": "merge_evidence", "to": "split_amount_items"},
        {"from": "split_amount_items", "to": "retrieve_account_candidates"},
        {"from": "retrieve_account_candidates", "to": "rank_leaf_accounts"},
        {"from": "rank_leaf_accounts", "to": "validate_voucher"},
        {"from": "validate_voucher", "to": "human_review"},
        {"from": "human_review", "to": "export_json"},
    ]
    return {"nodes": nodes, "edges": edges}
