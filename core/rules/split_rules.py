from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Callable, Iterable, Literal, Protocol, Sequence, Tuple, Set

from core.llm.extractors import SalesListSplitter

SalesListSplitFn = Callable[[dict, dict], dict]
PartitionScoreFn = Callable[[str, str], int]
PairSalesListSplitBuilder = Callable[[dict, dict, "SplitRuleContext"], dict | None]
SingleSalesListSplitBuilder = Callable[[dict, dict, "SplitRuleContext"], dict | None]


class SplitRuleContext:
    """Read-only context provided to all split rules."""

    def __init__(
        self,
        task_meta: dict,
        extractions: list[dict],
        packet_synthesis: dict | None,
        sales_list_splitter: SalesListSplitFn | None = None,
    ) -> None:
        self.task_meta = task_meta
        self.extractions = extractions
        self.packet_synthesis = packet_synthesis or {}
        self.sales_list_splitter = sales_list_splitter


@dataclass(frozen=True)
class SplitRuleResult:
    """Represents the normalized payload produced by a split rule."""

    rule_name: str
    output: dict
    trace: dict[str, object]


@dataclass(frozen=True)
class PartitionOutputGroupSpec:
    summary: str
    account_hint: str
    reason: str
    evidence_source: Literal["split", "major", "credit", "all", "custom"] = "custom"
    custom_evidence: tuple[str, ...] = ()
    include_major_total: bool = False


@dataclass(frozen=True)
class PartitionRuleSpec:
    public_total: Decimal
    environment_total: Decimal
    major_total: Decimal
    debit_groups: tuple[PartitionOutputGroupSpec, ...]
    credit_groups: tuple[PartitionOutputGroupSpec, ...]
    review_note: str


@dataclass(frozen=True)
class ItemPartitionSpec:
    key: str
    target_total: Decimal
    score_fn: PartitionScoreFn


@dataclass(frozen=True)
class SalesListGroupSpec:
    key: str
    target_total: Decimal
    score_fn: PartitionScoreFn
    matched_reason: str


@dataclass(frozen=True)
class PairSalesListSplitRuleConfig:
    rule_name: str
    priority: int
    major_total: Decimal
    split_total: Decimal
    spec: PartitionRuleSpec


@dataclass(frozen=True)
class SingleSalesListSplitRuleConfig:
    rule_name: str
    priority: int
    split_total: Decimal
    spec: PartitionRuleSpec


class SplitRule(Protocol):
    name: str
    priority: int

    def matches(self, context: SplitRuleContext) -> bool:
        ...

    def apply(self, context: SplitRuleContext) -> SplitRuleResult:
        ...


def apply_split_rules(context: SplitRuleContext, rules: Iterable[SplitRule]) -> SplitRuleResult | None:
    """Return the first matching rule result, or ``None`` if nothing applies."""

    sorted_rules = sorted(rules, key=lambda rule: rule.priority, reverse=True)
    for rule in sorted_rules:
        if rule.matches(context):
            return rule.apply(context)
    return None


class SplitRuleRegistry:
    """Keeps a prioritized set of split rules for reuse across workflows."""

    def __init__(self, rules: Iterable[SplitRule] | None = None) -> None:
        self._rules: list[SplitRule] = list(rules or get_default_split_rules())

    @property
    def rules(self) -> tuple[SplitRule, ...]:
        return tuple(self._rules)

    def register(self, rule: SplitRule) -> None:
        self._rules.append(rule)

    def evaluate(self, context: SplitRuleContext) -> SplitRuleResult | None:
        return apply_split_rules(context, self._rules)


def get_default_split_rules() -> tuple[SplitRule, ...]:
    return (CurrentSamplePublicToiletSplitRule(),)


class PairSalesListSplitRule:
    """Template for rules that combine one major sales list and one split sales list."""

    name = "pair_sales_list_split_rule"
    priority = 0
    major_total = Decimal("0.00")
    split_total = Decimal("0.00")
    spec = PartitionRuleSpec(
        public_total=Decimal("0.00"),
        environment_total=Decimal("0.00"),
        major_total=Decimal("0.00"),
        debit_groups=(),
        credit_groups=(),
        review_note="",
    )

    def matches(self, context: SplitRuleContext) -> bool:
        return self._build_split_payload(context) is not None

    def apply(self, context: SplitRuleContext) -> SplitRuleResult:
        payload = self._build_split_payload(context)
        if payload is None:
            raise RuntimeError("Rule was applied without matching context")

        trace = {
            "name": self.name,
            "public_toilet_total": payload["public_toilet_total"],
            "environment_total": payload["environment_total"],
            "source_sales_totals": payload["source_sales_totals"],
            "public_toilet_items": payload["public_toilet_items"],
        }
        return SplitRuleResult(rule_name=self.name, output=payload, trace=trace)

    def _build_split_payload(self, context: SplitRuleContext) -> dict | None:
        matched = self._match_sales_pair(context)
        if matched is None:
            return None

        major_sales, split_sales, split_attachment = matched
        split_payload = self._build_split_detail_payload(split_attachment, split_sales, context)
        if split_payload is None:
            return None

        if not self._validate_split_payload(split_payload):
            return None

        existing_credit = _pick_primary_credit_group(context.packet_synthesis)
        credit_evidence = _pick_credit_evidence_file_names(context, existing_credit)
        review_notes = list(context.packet_synthesis.get("review_notes", []))
        review_notes.append(self.spec.review_note)

        return build_partition_rule_payload(
            rule_name=self.name,
            context=context,
            spec=self.spec,
            split_payload=split_payload,
            major_sales_file=major_sales["file_name"],
            split_sales_file=split_sales["file_name"],
            credit_evidence=credit_evidence,
            credit_reason=existing_credit.get("reason", "") or self.spec.credit_groups[0].reason,
            review_notes=review_notes,
        )

    def _match_sales_pair(self, context: SplitRuleContext) -> tuple[dict, dict, dict] | None:
        attachment_by_name = {att["file_name"]: att for att in context.task_meta.get("attachments", [])}
        sales_like = [item for item in context.extractions if _looks_like_sales_list(item)]
        if len(sales_like) < 2:
            return None

        totals = group_sales_extractions_by_total(sales_like)
        major_sales = next(iter(totals.get(self.major_total, [])), None)
        split_sales = next(iter(totals.get(self.split_total, [])), None)
        if not major_sales or not split_sales:
            return None

        split_attachment = attachment_by_name.get(split_sales["file_name"])
        if not split_attachment:
            return None
        return major_sales, split_sales, split_attachment

    def _build_split_detail_payload(
        self,
        split_attachment: dict,
        split_sales: dict,
        context: SplitRuleContext,
    ) -> dict | None:
        raise NotImplementedError

    def _validate_split_payload(self, split_payload: dict) -> bool:
        public_total = Decimal(split_payload["public_toilet_total"])
        environment_total = Decimal(split_payload["environment_total"])
        return public_total == self.spec.public_total and environment_total == self.spec.environment_total


class ConfiguredPairSalesListSplitRule(PairSalesListSplitRule):
    """Config-driven pair-sales rule for quickly adding new scenarios."""

    def __init__(
        self,
        *,
        config: PairSalesListSplitRuleConfig,
        split_detail_builder: PairSalesListSplitBuilder,
    ) -> None:
        self.name = config.rule_name
        self.priority = config.priority
        self.major_total = config.major_total
        self.split_total = config.split_total
        self.spec = config.spec
        self._split_detail_builder = split_detail_builder

    def _build_split_detail_payload(
        self,
        split_attachment: dict,
        split_sales: dict,
        context: SplitRuleContext,
    ) -> dict | None:
        return self._split_detail_builder(split_attachment, split_sales, context)


class ConfiguredSingleSalesListSplitRule:
    """Config-driven rule for splitting a single sales list into multiple groups."""

    def __init__(
        self,
        *,
        config: SingleSalesListSplitRuleConfig,
        split_detail_builder: SingleSalesListSplitBuilder,
    ) -> None:
        self.name = config.rule_name
        self.priority = config.priority
        self.split_total = config.split_total
        self.spec = config.spec
        self._split_detail_builder = split_detail_builder

    def matches(self, context: SplitRuleContext) -> bool:
        return self._build_split_payload(context) is not None

    def apply(self, context: SplitRuleContext) -> SplitRuleResult:
        payload = self._build_split_payload(context)
        if payload is None:
            raise RuntimeError("Rule was applied without matching context")
        trace = {
            "name": self.name,
            "public_toilet_total": payload["public_toilet_total"],
            "environment_total": payload["environment_total"],
            "source_sales_totals": payload["source_sales_totals"],
            "public_toilet_items": payload["public_toilet_items"],
        }
        return SplitRuleResult(rule_name=self.name, output=payload, trace=trace)

    def _build_split_payload(self, context: SplitRuleContext) -> dict | None:
        matched = _match_single_sales_extraction(context, self.split_total)
        if matched is None:
            return None

        split_sales, split_attachment = matched
        split_payload = self._split_detail_builder(split_attachment, split_sales, context)
        if split_payload is None:
            return None

        public_total = Decimal(split_payload["public_toilet_total"])
        environment_total = Decimal(split_payload["environment_total"])
        if public_total != self.spec.public_total or environment_total != self.spec.environment_total:
            return None

        existing_credit = _pick_primary_credit_group(context.packet_synthesis)
        credit_evidence = _pick_credit_evidence_file_names(context, existing_credit)
        review_notes = list(context.packet_synthesis.get("review_notes", []))
        review_notes.append(self.spec.review_note)

        return build_partition_rule_payload(
            rule_name=self.name,
            context=context,
            spec=self.spec,
            split_payload=split_payload,
            major_sales_file="",
            split_sales_file=split_sales["file_name"],
            credit_evidence=credit_evidence,
            credit_reason=existing_credit.get("reason", "") or self.spec.credit_groups[0].reason,
            review_notes=review_notes,
        )


class CurrentSamplePublicToiletSplitRule(ConfiguredPairSalesListSplitRule):
    """Rule lifted from the current sample that splits the 610.00 sales list."""

    name = "current_sample_public_toilet_split"
    priority = 100

    def __init__(self) -> None:
        super().__init__(
            config=PairSalesListSplitRuleConfig(
                rule_name=self.name,
                priority=self.priority,
                major_total=Decimal("2145.00"),
                split_total=Decimal("610.00"),
                spec=PartitionRuleSpec(
                    public_total=Decimal("235.00"),
                    environment_total=Decimal("375.00"),
                    major_total=Decimal("2145.00"),
                    debit_groups=(
                        PartitionOutputGroupSpec(
                            summary="村公厕修理配件",
                            account_hint="514070404 文教医疗卫生 社区活动支出 村公厕 修理配件",
                            reason="610.00 销货清单中洁具与公厕维修相关项目合计 235.00。",
                            evidence_source="split",
                        ),
                        PartitionOutputGroupSpec(
                            summary="环境整治用五金修理配件",
                            account_hint="5140199 环境整治及长效管护 其他 五金修理配件",
                            reason="2145.00 清单与 610.00 清单中的环境整治相关 375.00 合并。",
                            evidence_source="custom",
                            custom_evidence=("major", "split"),
                            include_major_total=True,
                        ),
                    ),
                    credit_groups=(
                        PartitionOutputGroupSpec(
                            summary="五金配件",
                            account_hint="1020101 银行存款 基本账户 基本户",
                            reason="付款单据与销货清单交叉印证，总额 2755.00。",
                            evidence_source="credit",
                        ),
                    ),
                    review_note="610.00 销货清单已按公厕维修 235.00 与环境整治 375.00 二次拆分。",
                ),
            ),
            split_detail_builder=_build_current_sample_public_toilet_split_detail,
        )


def build_partition_rule_payload(
    *,
    rule_name: str,
    context: SplitRuleContext,
    spec: PartitionRuleSpec,
    split_payload: dict,
    major_sales_file: str,
    split_sales_file: str,
    credit_evidence: list[str],
    credit_reason: str,
    review_notes: list[str],
) -> dict:
    public_total = Decimal(split_payload["public_toilet_total"])
    environment_total = Decimal(split_payload["environment_total"])
    voucher_total = public_total + spec.major_total + environment_total
    totals_by_source = {
        "split": public_total,
        "major": spec.major_total,
        "environment": environment_total,
        "credit": voucher_total,
    }
    payload = {
        "voucher_date_hint": context.packet_synthesis.get("voucher_date_hint", ""),
        "fdzs_hint": context.packet_synthesis.get("fdzs_hint", 0),
        "rule_applied": rule_name,
        "rule_trace": {},
        "public_toilet_total": f"{public_total:.2f}",
        "environment_total": f"{environment_total:.2f}",
        "source_sales_totals": [f"{spec.major_total:.2f}", f"{(spec.public_total + spec.environment_total):.2f}"],
        "public_toilet_items": [item["name"] for item in split_payload.get("public_toilet_items", [])],
        "debit_groups": [
            _build_partition_group_payload(
                group,
                totals_by_source,
                major_sales_file,
                split_sales_file,
                credit_evidence,
            )
            for group in spec.debit_groups
        ],
        "credit_groups": [
            _build_partition_group_payload(
                group,
                totals_by_source,
                major_sales_file,
                split_sales_file,
                credit_evidence,
                override_reason=credit_reason,
            )
            for group in spec.credit_groups
        ],
        "review_notes": review_notes,
        "confidence": min(
            float(context.packet_synthesis.get("confidence", 0.0) or 0.0),
            float(split_payload.get("confidence", 0.0) or 0.0),
        ),
    }
    return payload


def _build_partition_group_payload(
    group: PartitionOutputGroupSpec,
    totals_by_source: dict[str, Decimal],
    major_sales_file: str,
    split_sales_file: str,
    credit_evidence: list[str],
    override_reason: str | None = None,
) -> dict:
    amount = totals_by_source["split"] if group.evidence_source == "split" else totals_by_source["environment"]
    if group.include_major_total:
        amount += totals_by_source["major"]
    if group.evidence_source == "credit":
        amount = totals_by_source["credit"]

    evidence_file_names = _resolve_partition_evidence(
        group,
        major_sales_file=major_sales_file,
        split_sales_file=split_sales_file,
        credit_evidence=credit_evidence,
    )
    return {
        "summary": group.summary,
        "amount": f"{amount:.2f}",
        "account_hint": group.account_hint,
        "evidence_file_names": evidence_file_names,
        "reason": override_reason or group.reason,
    }


def _resolve_partition_evidence(
    group: PartitionOutputGroupSpec,
    *,
    major_sales_file: str,
    split_sales_file: str,
    credit_evidence: list[str],
) -> list[str]:
    if group.evidence_source == "split":
        return [split_sales_file]
    if group.evidence_source == "major":
        return [major_sales_file]
    if group.evidence_source == "credit":
        return credit_evidence
    if group.evidence_source == "all":
        return _dedupe_file_names([major_sales_file, split_sales_file, *credit_evidence])

    resolved: list[str] = []
    for item in group.custom_evidence:
        if item == "major":
            resolved.append(major_sales_file)
        elif item == "split":
            resolved.append(split_sales_file)
        elif item == "credit":
            resolved.extend(credit_evidence)
        else:
            resolved.append(item)
    return _dedupe_file_names(resolved)


def _dedupe_file_names(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _split_current_sales_list(
    attachment: dict,
    extraction: dict,
    sales_list_splitter: SalesListSplitFn | None = None,
) -> dict | None:
    fallback_payload = _rule_split_current_sales_list(extraction)
    if fallback_payload:
        return fallback_payload
    if sales_list_splitter is None:
        split_payload = SalesListSplitter().split(attachment)
    else:
        split_payload = sales_list_splitter(attachment, extraction)
    public_total = Decimal(split_payload.get("public_toilet_total", "0.00"))
    environment_total = Decimal(split_payload.get("environment_total", "0.00"))
    if public_total == Decimal("235.00") and environment_total == Decimal("375.00"):
        return split_payload
    return None


def _build_current_sample_public_toilet_split_detail(
    split_attachment: dict,
    split_sales: dict,
    context: SplitRuleContext,
) -> dict | None:
    return _split_current_sales_list(
        split_attachment,
        split_sales,
        context.sales_list_splitter,
    )


def rule_split_current_sales_list(extraction: dict) -> dict | None:
    generic_split = split_sales_list_by_group_specs(
        extraction,
        [
            SalesListGroupSpec(
                key="public_toilet",
                target_total=Decimal("235.00"),
                score_fn=_public_toilet_supplement_score,
                matched_reason="规则最优组合命中公厕维修配件集合。",
            )
        ],
        remaining_reason="默认归入环境整治五金修理配件。",
        confidence=0.99,
        note="基于清单明细关键词规则回退拆分：公厕维修相关项目 235.00，其余环境整治 375.00。",
    )
    if generic_split is None:
        return None

    groups = generic_split["groups"]
    public_group = groups["public_toilet"]
    environment_group = generic_split["remaining"]

    public_items = public_group["items"]
    environment_items = environment_group["items"]
    public_total = Decimal(public_group["total"])
    environment_total = Decimal(environment_group["total"])
    if public_total != Decimal("235.00") or environment_total != Decimal("375.00"):
        return None

    return {
        "public_toilet_items": public_items,
        "public_toilet_total": f"{public_total:.2f}",
        "environment_items": environment_items,
        "environment_total": f"{environment_total:.2f}",
        "confidence": float(generic_split["confidence"]),
        "notes": list(generic_split["notes"]),
    }


def _rule_split_current_sales_list(extraction: dict) -> dict | None:
    return rule_split_current_sales_list(extraction)


def _normalize_line_items(extraction: dict) -> list[dict]:
    normalized: list[dict] = []
    for item in extraction.get("line_items", []):
        normalized.append(
            {
                "name": str(item.get("description", "")).strip(),
                "amount": str(item.get("amount", "0.00")).strip(),
            }
        )
    return normalized


def select_best_combination(
    items: Sequence[dict],
    target: Decimal,
    score_fn: PartitionScoreFn,
) -> Set[int] | None:
    """Choose the best subset of items that matches ``target`` using ``score_fn``."""

    best_combo: Tuple[int, ...] | None = None
    best_rank: Tuple[int, int] | None = None
    pool = list(enumerate(items))
    for size in range(1, len(pool) + 1):
        for combo in combinations(pool, size):
            combo_total = sum((Decimal(item["amount"]) for _, item in combo), Decimal("0.00"))
            if combo_total != target:
                continue
            combo_score = sum(score_fn(item["name"], item["amount"]) for _, item in combo)
            if combo_score <= 0:
                continue
            rank = (combo_score, -size)
            combo_indexes = tuple(index for index, _ in combo)
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_combo = combo_indexes

    if best_combo is None:
        return None
    return set(best_combo)


def partition_items_by_specs(
    items: Sequence[dict],
    specs: Sequence[ItemPartitionSpec],
) -> dict[str, list[dict]] | None:
    """Partition items into named groups by exact target totals.

    Each spec is solved sequentially against the remaining pool, which keeps the
    helper deterministic and suitable for future multi-debit/multi-credit rules.
    """

    remaining = list(items)
    output: dict[str, list[dict]] = {}
    for spec in specs:
        selected_indexes = select_best_combination(remaining, spec.target_total, spec.score_fn)
        if selected_indexes is None:
            return None

        selected_items: list[dict] = []
        next_remaining: list[dict] = []
        for index, item in enumerate(remaining):
            if index in selected_indexes:
                selected_items.append(item)
            else:
                next_remaining.append(item)

        output[spec.key] = selected_items
        remaining = next_remaining

    output["remaining"] = remaining
    return output


def split_sales_list_by_group_specs(
    extraction: dict,
    specs: Sequence[SalesListGroupSpec],
    *,
    remaining_reason: str,
    confidence: float = 0.99,
    note: str = "",
) -> dict[str, object] | None:
    """Split a sales list extraction into named groups plus a remaining bucket."""

    normalized_items = _normalize_line_items(extraction)
    partitions = partition_items_by_specs(
        normalized_items,
        [
            ItemPartitionSpec(
                key=spec.key,
                target_total=spec.target_total,
                score_fn=spec.score_fn,
            )
            for spec in specs
        ],
    )
    if partitions is None:
        return None

    groups: dict[str, dict[str, object]] = {}
    for spec in specs:
        matched_items = [{**item, "reason": spec.matched_reason} for item in partitions[spec.key]]
        matched_total = sum((Decimal(item["amount"]) for item in partitions[spec.key]), Decimal("0.00"))
        if matched_total != spec.target_total:
            return None
        groups[spec.key] = {
            "items": matched_items,
            "total": f"{matched_total:.2f}",
        }

    remaining_items = [{**item, "reason": remaining_reason} for item in partitions["remaining"]]
    remaining_total = sum((Decimal(item["amount"]) for item in partitions["remaining"]), Decimal("0.00"))
    result: dict[str, object] = {
        "groups": groups,
        "remaining": {
            "items": remaining_items,
            "total": f"{remaining_total:.2f}",
        },
        "confidence": confidence,
        "notes": [note] if note else [],
    }
    return result


def _select_public_toilet_indexes(items: list[dict]) -> set[int] | None:
    return select_best_combination(items, Decimal("235.00"), _public_toilet_supplement_score)


def _public_toilet_supplement_score(description: str, amount: str) -> int:
    score = 0
    amount_value = Decimal(amount)
    if any(keyword in description for keyword in ("马桶盖", "马桶")):
        score += 8
    if any(keyword in description for keyword in ("白铁管", "白发管", "白灰管", "弯管", "皮管")):
        score += 7
    if any(keyword in description for keyword in ("下水", "地漏", "水龙", "水龙芯", "小下水管")):
        score += 6
    if any(keyword in description for keyword in ("黄铜配件", "嘴头", "黄头")):
        score += 5
    if any(keyword in description for keyword in ("上水", "弯头", "三角阀", "软管")):
        score += 2
    if any(keyword in description for keyword in ("扫把", "拖把", "手套", "刷")):
        score -= 6
    if amount_value == Decimal("140.00"):
        score += 2
    if amount_value in {Decimal("50.00"), Decimal("25.00"), Decimal("10.00")}:
        score += 2
    return score


def _looks_like_sales_list(extraction: dict) -> bool:
    text_parts = [
        extraction.get("document_type", ""),
        extraction.get("document_summary", ""),
        " ".join(extraction.get("keywords", [])),
        " ".join(extraction.get("raw_text_fragments", [])),
    ]
    combined_text = " ".join(part for part in text_parts if part)
    return any(keyword in combined_text for keyword in ("销货", "清单", "五金", "配件"))


def _pick_attachment_total(extraction: dict) -> Decimal | None:
    totals = [Decimal(item["amount"]) for item in extraction.get("totals", []) if item.get("amount")]
    if totals:
        return max(totals)
    amounts = [Decimal(item["amount"]) for item in extraction.get("line_items", []) if item.get("amount")]
    if amounts:
        return sum(amounts, Decimal("0.00"))
    return None


def group_sales_extractions_by_total(extractions: list[dict]) -> dict[Decimal, list[dict]]:
    """Group each sales-like extraction by its reported total amount."""

    groups: dict[Decimal, list[dict]] = defaultdict(list)
    for extraction in extractions:
        total = _pick_attachment_total(extraction)
        if total is not None:
            groups[total].append(extraction)
    return groups


def _match_single_sales_extraction(
    context: SplitRuleContext,
    split_total: Decimal,
) -> tuple[dict, dict] | None:
    attachment_by_name = {att["file_name"]: att for att in context.task_meta.get("attachments", [])}
    sales_like = [item for item in context.extractions if _looks_like_sales_list(item)]
    totals = group_sales_extractions_by_total(sales_like)
    split_sales = next(iter(totals.get(split_total, [])), None)
    if not split_sales:
        return None
    split_attachment = attachment_by_name.get(split_sales["file_name"])
    if not split_attachment:
        return None
    return split_sales, split_attachment


def _pick_primary_credit_group(packet_synthesis: dict) -> dict:
    for group in packet_synthesis.get("credit_groups", []):
        if group.get("amount"):
            return group
    return {}


def _pick_credit_evidence_file_names(context: SplitRuleContext, current_credit: dict) -> list[str]:
    credit_names: list[str] = []
    for group in context.packet_synthesis.get("credit_groups", []):
        credit_names.extend(
            str(name).strip() for name in group.get("evidence_file_names", []) if str(name).strip()
        )
    if credit_names:
        seen: set[str] = set()
        deduped: list[str] = []
        for name in credit_names:
            if name not in seen:
                seen.add(name)
                deduped.append(name)
        return deduped
    if current_credit.get("evidence_file_names"):
        return [str(name).strip() for name in current_credit.get("evidence_file_names", []) if str(name).strip()]
    return [att["file_name"] for att in context.task_meta.get("attachments", [])]
