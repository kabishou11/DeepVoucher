from core.rules.accounting import (
    account_code_level,
    account_path,
    build_children_map,
    is_leaf_account,
    normalize_account_code,
    parent_account_code,
)
from core.schemas.models import VoucherLine
from core.rules.accounting import validate_trial_balance


def test_account_code_hierarchy_helpers() -> None:
    assert normalize_account_code("1020101.0") == "1020101"
    assert account_code_level("514070404") == 9
    assert parent_account_code("514070404") == "5140704"
    assert parent_account_code("5140704") == "51407"
    assert parent_account_code("51407") == "514"
    assert parent_account_code("514") is None


def test_account_path_and_leaf_detection() -> None:
    codes = ["102", "10201", "1020101", "1020102"]
    names_by_code = {
        "102": "银行存款",
        "10201": "基本账户",
        "1020101": "基本户",
        "1020102": "村务卡",
    }
    children_map = build_children_map(codes)
    assert account_path("1020101", names_by_code) == "银行存款/基本账户/基本户"
    assert is_leaf_account("1020101", children_map) is True
    assert is_leaf_account("102", children_map) is False


def test_validate_trial_balance() -> None:
    lines = [
        VoucherLine(row=0, zy="a", kmdm="1", kmmc="x", jie="235.00", dai="0.00"),
        VoucherLine(row=1, zy="b", kmdm="2", kmmc="y", jie="2520.00", dai="0.00"),
        VoucherLine(row=2, zy="c", kmdm="3", kmmc="z", jie="0.00", dai="2755.00"),
    ]
    assert validate_trial_balance(lines) is True
