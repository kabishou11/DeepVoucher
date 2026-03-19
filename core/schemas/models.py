from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Task(BaseModel):
    task_id: str
    status: Literal["pending", "running", "blocked", "completed", "failed"] = "pending"
    attachment_count: int = 0
    current_node: str | None = None
    blocker_count: int = 0


class Attachment(BaseModel):
    attachment_id: str
    file_name: str
    file_path: str
    mime_type: str | None = None
    quality_status: Literal["unknown", "ok", "blurred", "duplicate"] = "unknown"


class ExtractedFact(BaseModel):
    fact_type: str
    fact_value: str
    normalized_value: str | None = None
    source_attachment_id: str
    source_span_desc: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class EvidenceGroup(BaseModel):
    evidence_group_id: str
    fact_ids: list[str] = Field(default_factory=list)
    summary: str


class BusinessEventDraft(BaseModel):
    event_id: str
    voucher_date: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    title: str | None = None
    total_amount: Decimal | None = None


class AmountItem(BaseModel):
    amount_item_id: str
    amount: Decimal
    purpose: str
    evidence_ids: list[str] = Field(default_factory=list)
    direction_hint: Literal["debit", "credit", "unknown"] = "unknown"


class AccountCandidate(BaseModel):
    code: str
    name: str
    path: str
    is_leaf: bool
    score: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class PostingCandidate(BaseModel):
    posting_id: str
    summary: str
    amount: Decimal
    direction: Literal["debit", "credit"]
    account_candidates: list[AccountCandidate] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class VoucherLine(BaseModel):
    row: int
    zy: str
    kmdm: str
    kmmc: str
    fzkm: str = ""
    slhs: str = "-"
    number: str = ""
    jie: str = "0.00"
    dai: str = "0.00"


class ValidationResult(BaseModel):
    rule_id: str
    rule_name: str
    target_id: str
    passed: bool
    message: str


class Blocker(BaseModel):
    blocker_id: str
    blocker_type: str
    message: str
    target_id: str


class ReviewResolution(BaseModel):
    target_id: str
    action: str
    resolved: bool
    reviewer: str | None = None


class VoucherDraft(BaseModel):
    voucher_date: str
    attachment_count: int
    lines: list[VoucherLine]
    blockers: list[Blocker] = Field(default_factory=list)


class VoucherExportPayload(BaseModel):
    fdzs: str = "0"
    dt: str
    pzks: list[VoucherLine]
    id: int | None = None


class ReviewLineUpdate(BaseModel):
    row: int
    zy: str
    kmdm: str
    kmmc: str


class ReviewRequest(BaseModel):
    lines: list[ReviewLineUpdate]
    voucher_date: str | None = None
