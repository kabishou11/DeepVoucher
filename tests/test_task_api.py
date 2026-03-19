import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def _load_workflow_fixture(name: str) -> dict:
    path = Path("tests/fixtures") / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_create_and_fetch_task_detail() -> None:
    fake_payload = {
        "status": "ready_for_review",
        "mode": "modelscope_live",
        "voucher_date": "2026-01-31",
        "facts": [{"fact_id": "fact-001", "fact_type": "amount"}],
        "extractions": [{"attachment_id": "att-001", "document_summary": "测试摘要", "line_items": []}],
        "amount_items": [{"amount_item_id": "amt-001", "amount": "100.00"}],
        "posting_candidates": [{"posting_id": "post-001"}],
        "preview_lines": [
            {
                "row": 0,
                "zy": "测试摘要",
                "kmdm": "1020101",
                "kmmc": "银行存款/基本账户/基本户",
                "jie": "100.00",
                "dai": "0.00",
                "fzkm": "",
                "slhs": "-",
                "number": "",
            }
        ],
        "blockers": [],
        "review_actions": [],
        "nodes": [{"id": "extract_facts_multimodal", "label": "多模态事实抽取", "status": "success", "summary": "ok"}],
        "debug": {"llm_model": "Qwen/Qwen3.5-35B-A3B"},
    }
    with patch("apps.api.main.run_voucher_pipeline", return_value=fake_payload):
        response = client.post(
            "/api/tasks",
            files=[
                ("files", ("sample-1.jpg", BytesIO(b"fake-image-1"), "image/jpeg")),
                ("files", ("sample-2.jpg", BytesIO(b"fake-image-2"), "image/jpeg")),
            ],
        )
    assert response.status_code == 200
    payload = response.json()
    task_id = payload["task"]["task_id"]
    assert payload["workflow"]["mode"] == "modelscope_live"
    assert len(payload["workflow"]["preview_lines"]) == 1

    detail_response = client.get(f"/api/tasks/{task_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["task"]["task_id"] == task_id
    assert detail["workflow"]["nodes"]

    attachment_id = detail["task"]["attachments"][0]["attachment_id"]
    attachment_response = client.get(f"/api/tasks/{task_id}/attachments/{attachment_id}")
    assert attachment_response.status_code == 200
    assert attachment_response.headers["content-type"].startswith("image/")


def test_list_tasks_endpoint() -> None:
    response = client.get("/api/tasks")
    assert response.status_code == 200
    assert "items" in response.json()


def test_learning_summary_endpoint() -> None:
    with patch("apps.api.main.learning_summary", return_value={"entry_count": 3, "account_count": 2}):
        response = client.get("/api/learning/summary")
    assert response.status_code == 200
    assert response.json()["entry_count"] == 3


def test_readiness_endpoint() -> None:
    fake_report = {
        "overall_status": "ready",
        "blockers": [],
        "checks": [{"key": "env_file", "ok": True}],
    }
    with patch("apps.api.main.build_readiness_report", return_value=fake_report):
        response = client.get("/api/readiness")
    assert response.status_code == 200
    assert response.json()["overall_status"] == "ready"


def test_learning_records_endpoint() -> None:
    with patch(
        "apps.api.main.list_learning_entries",
        return_value=[
            {
                "task_id": "task-001",
                "summary": "环境整治用五金修理配件",
                "account_code": "5140199",
                "account_path": "公益支出/环境整治及长效管护/其他",
                "direction": "debit",
                "amount": "2520.00",
                "exported_at": "2026-03-19T18:00:00",
            }
        ],
    ):
        response = client.get("/api/learning/records?limit=5")
    assert response.status_code == 200
    assert response.json()["items"][0]["account_code"] == "5140199"


def test_review_and_export_endpoints() -> None:
    fake_payload = {
        "status": "blocked",
        "mode": "modelscope_live",
        "voucher_date": "2026-01-31",
        "facts": [],
        "extractions": [],
        "amount_items": [],
        "posting_candidates": [
            {"posting_id": "post-001", "requires_review": True, "account_candidates": []},
            {"posting_id": "post-002", "requires_review": False, "account_candidates": []},
        ],
        "preview_lines": [
            {
                "row": 0,
                "zy": "测试摘要A",
                "kmdm": "",
                "kmmc": "",
                "jie": "100.00",
                "dai": "0.00",
                "fzkm": "",
                "slhs": "-",
                "number": "",
            },
            {
                "row": 1,
                "zy": "测试摘要B",
                "kmdm": "1020101",
                "kmmc": "银行存款/基本账户/基本户",
                "jie": "0.00",
                "dai": "100.00",
                "fzkm": "",
                "slhs": "-",
                "number": "",
            },
        ],
        "blockers": [{"blocker_id": "blk-1", "blocker_type": "account_missing", "message": "need review", "target_id": "line-0"}],
        "review_actions": [],
        "nodes": [{"id": "validate_voucher", "label": "凭证校验", "status": "blocked", "summary": "blocked"}],
        "debug": {"amount_notes": []},
    }
    with patch("apps.api.main.run_voucher_pipeline", return_value=fake_payload):
        create_response = client.post(
            "/api/tasks",
            files=[("files", ("sample-1.jpg", BytesIO(b"fake-image-1"), "image/jpeg"))],
        )

    task_id = create_response.json()["task"]["task_id"]
    review_response = client.post(
        f"/api/tasks/{task_id}/review",
        json={
            "lines": [
                {
                    "row": 0,
                    "zy": "测试摘要A",
                    "kmdm": "5140199",
                    "kmmc": "公益支出/环境整治及长效管护/其他",
                },
                {
                    "row": 1,
                    "zy": "测试摘要B",
                    "kmdm": "1020101",
                    "kmmc": "银行存款/基本账户/基本户",
                },
            ],
            "voucher_date": "2026-01-31",
        },
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert reviewed["workflow"]["blockers"] == []

    with patch("apps.api.main.append_confirmed_export", return_value=[{"row": 0}, {"row": 1}]):
        export_response = client.post(f"/api/tasks/{task_id}/export")
    assert export_response.status_code == 200
    export_body = export_response.json()
    exported = export_body["payload"]
    assert export_body["learning"]["captured"] == 2
    assert exported["body"]["dt"] == "2026-01-31"
    assert len(exported["body"]["pzks"]) == 2


def test_review_requires_voucher_date_before_export() -> None:
    fake_payload = {
        "status": "blocked",
        "mode": "modelscope_live",
        "voucher_date": "",
        "facts": [],
        "extractions": [],
        "amount_items": [],
        "posting_candidates": [
            {"posting_id": "post-001", "requires_review": False, "account_candidates": []},
            {"posting_id": "post-002", "requires_review": False, "account_candidates": []},
        ],
        "preview_lines": [
            {
                "row": 0,
                "zy": "测试摘要A",
                "kmdm": "5140199",
                "kmmc": "公益支出/环境整治及长效管护/其他",
                "jie": "100.00",
                "dai": "0.00",
                "fzkm": "",
                "slhs": "-",
                "number": "",
            },
            {
                "row": 1,
                "zy": "测试摘要B",
                "kmdm": "1020101",
                "kmmc": "银行存款/基本账户/基本户",
                "jie": "0.00",
                "dai": "100.00",
                "fzkm": "",
                "slhs": "-",
                "number": "",
            },
        ],
        "blockers": [{"blocker_id": "blk-voucher-date", "blocker_type": "voucher_date_missing", "message": "need date", "target_id": "voucher"}],
        "review_actions": [],
        "nodes": [{"id": "validate_voucher", "label": "凭证校验", "status": "blocked", "summary": "blocked"}],
        "debug": {"amount_notes": []},
    }
    with patch("apps.api.main.run_voucher_pipeline", return_value=fake_payload):
        create_response = client.post(
            "/api/tasks",
            files=[("files", ("sample-1.jpg", BytesIO(b"fake-image-1"), "image/jpeg"))],
        )

    task_id = create_response.json()["task"]["task_id"]
    review_response = client.post(
        f"/api/tasks/{task_id}/review",
        json={
            "lines": [
                {
                    "row": 0,
                    "zy": "测试摘要A",
                    "kmdm": "5140199",
                    "kmmc": "公益支出/环境整治及长效管护/其他",
                },
                {
                    "row": 1,
                    "zy": "测试摘要B",
                    "kmdm": "1020101",
                    "kmmc": "银行存款/基本账户/基本户",
                },
            ]
        },
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert reviewed["workflow"]["blockers"][0]["blocker_type"] == "voucher_date_missing"

    review_response = client.post(
        f"/api/tasks/{task_id}/review",
        json={
            "lines": [
                {
                    "row": 0,
                    "zy": "测试摘要A",
                    "kmdm": "5140199",
                    "kmmc": "公益支出/环境整治及长效管护/其他",
                },
                {
                    "row": 1,
                    "zy": "测试摘要B",
                    "kmdm": "1020101",
                    "kmmc": "银行存款/基本账户/基本户",
                },
            ],
            "voucher_date": "2026-01-31",
        },
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert reviewed["workflow"]["blockers"] == []


def test_review_blocks_export_with_missing_voucher_date_from_fixture() -> None:
    fake_payload = _load_workflow_fixture("blocker_voucher_date.json")
    with patch("apps.api.main.run_voucher_pipeline", return_value=fake_payload):
        create_response = client.post(
            "/api/tasks",
            files=[("files", ("sample-1.jpg", BytesIO(b"fake-image-1"), "image/jpeg"))],
        )

    task_id = create_response.json()["task"]["task_id"]
    review_response = client.post(
        f"/api/tasks/{task_id}/review",
        json={
            "lines": [
                {
                    "row": 0,
                    "zy": "测试摘要A",
                    "kmdm": "",
                    "kmmc": "",
                },
                {
                    "row": 1,
                    "zy": "测试摘要B",
                    "kmdm": "1020101",
                    "kmmc": "银行存款/基本账户/基本户",
                },
            ],
            "voucher_date": "",
        },
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert any(blocker["blocker_type"] == "voucher_date_missing" for blocker in reviewed["workflow"]["blockers"])

    export_response = client.post(f"/api/tasks/{task_id}/export")
    assert export_response.status_code == 409
    assert export_response.json()["detail"] == "Voucher still has blockers."


def test_residual_blocker_still_blocks_export_if_unresolved() -> None:
    fake_payload = _load_workflow_fixture("blocker_residual.json")
    with patch("apps.api.main.run_voucher_pipeline", return_value=fake_payload):
        create_response = client.post(
            "/api/tasks",
            files=[("files", ("sample-1.jpg", BytesIO(b"fake-image-1"), "image/jpeg"))],
        )

    task_id = create_response.json()["task"]["task_id"]
    review_response = client.post(
        f"/api/tasks/{task_id}/review",
        json={
            "lines": [
                {
                    "row": 0,
                    "zy": "残差借方",
                    "kmdm": "",
                    "kmmc": "",
                },
                {
                    "row": 1,
                    "zy": "贷方",
                    "kmdm": "1020101",
                    "kmmc": "银行存款/基本账户/基本户",
                },
            ],
            "voucher_date": "2026-01-31",
        },
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert any(blocker["blocker_type"] == "residual_amount" for blocker in reviewed["workflow"]["blockers"])

    export_response = client.post(f"/api/tasks/{task_id}/export")
    assert export_response.status_code == 409
    assert export_response.json()["detail"] == "Voucher still has blockers."
