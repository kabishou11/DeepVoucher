import json
from pathlib import Path

from core.exporters.compare import compare_voucher_payload


def test_compare_voucher_payload_fixture_self_match() -> None:
    fixture_path = Path("tests/fixtures/current_sample_expected.json")
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert compare_voucher_payload(expected, expected) == []


def test_compare_voucher_payload_detects_multi_line_discrepancy() -> None:
    base_path = Path("tests/fixtures/current_sample_expected.json")
    variant_path = Path("tests/fixtures/current_sample_expected_variant.json")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    variant = json.loads(variant_path.read_text(encoding="utf-8"))
    diffs = compare_voucher_payload(base, variant)
    assert diffs
    assert any("jie" in diff for diff in diffs)
