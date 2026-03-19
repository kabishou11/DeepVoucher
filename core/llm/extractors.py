from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.llm.modelscope import ModelScopeClient, extract_json_payload
from core.llm.prompts import EXTRACTION_PROMPT, SALES_LIST_SPLIT_PROMPT, VOUCHER_PACKET_PROMPT


class AttachmentFactExtractor:
    def __init__(self) -> None:
        self.client = ModelScopeClient()

    def extract_from_attachment(self, attachment: dict[str, Any]) -> dict[str, Any]:
        if not self.client.settings.modelscope_api_key:
            raise RuntimeError("MODELSCOPE_API_KEY is not configured.")
        messages = self.client.image_message(EXTRACTION_PROMPT, attachment["file_path"])
        response_text = self.client.chat_completion(messages)
        payload = extract_json_payload(response_text)
        return normalize_attachment_payload(attachment, payload)


class VoucherPacketSynthesizer:
    def __init__(self) -> None:
        self.client = ModelScopeClient()

    def synthesize(self, attachments: list[dict[str, Any]], extractions: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.client.settings.modelscope_api_key:
            raise RuntimeError("MODELSCOPE_API_KEY is not configured.")
        image_paths = [attachment["file_path"] for attachment in attachments]
        extraction_digest = {
            "attachments": [
                {
                    "file_name": item["file_name"],
                    "document_type": item["document_type"],
                    "document_summary": item["document_summary"],
                    "voucher_date_hint": item["voucher_date_hint"],
                    "line_items": item["line_items"][:10],
                    "totals": item["totals"],
                }
                for item in extractions
            ]
        }
        prompt = f"{VOUCHER_PACKET_PROMPT}\n\n已知的单图抽取结果如下：\n{extraction_digest}"
        messages = self.client.multi_image_message(prompt, image_paths)
        response_text = self.client.chat_completion(messages)
        payload = extract_json_payload(response_text)
        return normalize_voucher_packet_payload(payload)


class SalesListSplitter:
    def __init__(self) -> None:
        self.client = ModelScopeClient()

    def split(self, attachment: dict[str, Any]) -> dict[str, Any]:
        if not self.client.settings.modelscope_api_key:
            raise RuntimeError("MODELSCOPE_API_KEY is not configured.")
        messages = self.client.image_message(SALES_LIST_SPLIT_PROMPT, attachment["file_path"])
        response_text = self.client.chat_completion(messages)
        payload = extract_json_payload(response_text)
        return normalize_sales_list_split_payload(payload)


def normalize_attachment_payload(attachment: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    line_items = []
    for item in payload.get("line_items", []) or []:
        amount = _normalize_amount(item.get("amount", ""))
        if amount is None:
            continue
        line_items.append(
            {
                "description": str(item.get("description", "")).strip(),
                "amount": amount,
                "category_hint": str(item.get("category_hint", "")).strip(),
                "direction_hint": _normalize_direction(item.get("direction_hint")),
            }
        )

    totals = []
    for item in payload.get("totals", []) or []:
        amount = _normalize_amount(item.get("amount", ""))
        if amount is None:
            continue
        totals.append({"label": str(item.get("label", "")).strip(), "amount": amount})

    return {
        "attachment_id": attachment["attachment_id"],
        "file_name": attachment["file_name"],
        "document_type": str(payload.get("document_type", "")).strip(),
        "document_summary": str(payload.get("document_summary", "")).strip(),
        "voucher_date_hint": str(payload.get("voucher_date_hint", "")).strip(),
        "counterparties": [str(item).strip() for item in payload.get("counterparties", []) if str(item).strip()],
        "payment_accounts": [str(item).strip() for item in payload.get("payment_accounts", []) if str(item).strip()],
        "keywords": [str(item).strip() for item in payload.get("keywords", []) if str(item).strip()],
        "line_items": line_items,
        "totals": totals,
        "raw_text_fragments": [
            str(item).strip() for item in payload.get("raw_text_fragments", []) if str(item).strip()
        ],
        "confidence": float(payload.get("confidence", 0.0) or 0.0),
    }


def normalize_voucher_packet_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def normalize_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups = []
        for item in items or []:
            amount = _normalize_amount(item.get("amount", ""))
            if amount is None:
                continue
            groups.append(
                {
                    "summary": str(item.get("summary", "")).strip(),
                    "amount": amount,
                    "account_hint": str(item.get("account_hint", "")).strip(),
                    "evidence_file_names": [
                        str(name).strip() for name in item.get("evidence_file_names", []) if str(name).strip()
                    ],
                    "reason": str(item.get("reason", "")).strip(),
                }
            )
        return groups

    return {
        "voucher_date_hint": str(payload.get("voucher_date_hint", "")).strip(),
        "fdzs_hint": int(payload.get("fdzs_hint", 0) or 0),
        "debit_groups": normalize_groups(payload.get("debit_groups", [])),
        "credit_groups": normalize_groups(payload.get("credit_groups", [])),
        "review_notes": [str(item).strip() for item in payload.get("review_notes", []) if str(item).strip()],
        "confidence": float(payload.get("confidence", 0.0) or 0.0),
    }


def normalize_sales_list_split_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for item in items or []:
            amount = _normalize_amount(item.get("amount", ""))
            if amount is None:
                continue
            normalized.append(
                {
                    "name": str(item.get("name", "")).strip(),
                    "amount": amount,
                    "reason": str(item.get("reason", "")).strip(),
                }
            )
        return normalized

    public_items = normalize_items(payload.get("public_toilet_items", []))
    environment_items = normalize_items(payload.get("environment_items", []))
    public_total = _normalize_amount(payload.get("public_toilet_total", ""))
    environment_total = _normalize_amount(payload.get("environment_total", ""))
    return {
        "public_toilet_items": public_items,
        "public_toilet_total": public_total or "0.00",
        "environment_items": environment_items,
        "environment_total": environment_total or "0.00",
        "confidence": float(payload.get("confidence", 0.0) or 0.0),
        "notes": [str(item).strip() for item in payload.get("notes", []) if str(item).strip()],
    }


def _normalize_amount(value: Any) -> str | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return f"{Decimal(text):.2f}"
    except (InvalidOperation, ValueError):
        return None


def _normalize_direction(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"debit", "credit"}:
        return text
    return "unknown"
