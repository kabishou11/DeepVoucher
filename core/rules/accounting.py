from decimal import Decimal
from typing import Iterable

from core.schemas.models import VoucherLine


ACCOUNT_CODE_LEVELS = (3, 5, 7, 9)


def normalize_account_code(code: str | int | float) -> str:
    text = str(code).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def account_code_level(code: str | int | float) -> int:
    normalized = normalize_account_code(code)
    return len(normalized)


def parent_account_code(code: str | int | float) -> str | None:
    normalized = normalize_account_code(code)
    length = len(normalized)
    if length not in ACCOUNT_CODE_LEVELS or length == ACCOUNT_CODE_LEVELS[0]:
        return None
    target_length = ACCOUNT_CODE_LEVELS[ACCOUNT_CODE_LEVELS.index(length) - 1]
    return normalized[:target_length]


def account_path(code: str | int | float, names_by_code: dict[str, str]) -> str:
    normalized = normalize_account_code(code)
    parts: list[str] = []
    cursor: str | None = normalized
    while cursor:
        name = names_by_code.get(cursor)
        if name:
            parts.append(name)
        cursor = parent_account_code(cursor)
    return "/".join(reversed(parts))


def build_children_map(codes: Iterable[str]) -> dict[str, list[str]]:
    normalized_codes = [normalize_account_code(code) for code in codes]
    children: dict[str, list[str]] = {code: [] for code in normalized_codes}
    for code in normalized_codes:
        parent = parent_account_code(code)
        if parent and parent in children:
            children[parent].append(code)
    for code in children:
        children[code].sort()
    return children


def is_leaf_account(code: str | int | float, children_map: dict[str, list[str]] | None = None) -> bool:
    normalized = normalize_account_code(code)
    if children_map is None:
        return account_code_level(normalized) == ACCOUNT_CODE_LEVELS[-1]
    return len(children_map.get(normalized, [])) == 0


def validate_trial_balance(lines: list[VoucherLine]) -> bool:
    debit_total = sum((Decimal(line.jie) for line in lines), Decimal("0.00"))
    credit_total = sum((Decimal(line.dai) for line in lines), Decimal("0.00"))
    return debit_total == credit_total
