from __future__ import annotations

from typing import Any


def compare_voucher_payload(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    actual_body = actual.get("body", actual)
    expected_body = expected.get("body", expected)

    for field in ("fdzs", "dt"):
        if str(actual_body.get(field)) != str(expected_body.get(field)):
            diffs.append(f"{field}: expected {expected_body.get(field)!r}, got {actual_body.get(field)!r}")

    actual_lines = actual_body.get("pzks", [])
    expected_lines = expected_body.get("pzks", [])
    if len(actual_lines) != len(expected_lines):
        diffs.append(f"pzks length: expected {len(expected_lines)}, got {len(actual_lines)}")
        return diffs

    for index, (actual_line, expected_line) in enumerate(zip(actual_lines, expected_lines, strict=True)):
        for field in ("zy", "kmdm", "kmmc", "jie", "dai"):
            if str(actual_line.get(field)) != str(expected_line.get(field)):
                diffs.append(
                    f"line {index} field {field}: expected {expected_line.get(field)!r}, got {actual_line.get(field)!r}"
                )
    return diffs
