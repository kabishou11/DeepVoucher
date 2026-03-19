from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import app
from core.exporters.compare import compare_voucher_payload


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root / "tests" / "fixtures" / "current_sample_expected.json").read_text(encoding="utf-8"))

    files = []
    for path in sorted((root / "ai验证" / "附件").iterdir()):
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            files.append(("files", (path.name, path.read_bytes(), "image/jpeg")))

    client = TestClient(app)
    created = client.post("/api/tasks", files=files)
    created.raise_for_status()
    task_id = created.json()["task"]["task_id"]

    exported = client.post(f"/api/tasks/{task_id}/export")
    print("export status:", exported.status_code)
    data = exported.json()
    if exported.status_code != 200:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    payload = data["payload"]
    diffs = compare_voucher_payload(payload, expected)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if diffs:
      print("DIFFS:")
      for diff in diffs:
          print("-", diff)
      raise SystemExit(1)
    print("Regression passed.")
