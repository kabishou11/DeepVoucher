from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


class TaskStore:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self.runs_dir = self.project_root / "data" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def list_tasks(self) -> list[dict]:
        tasks: list[dict] = []
        for task_dir in self.runs_dir.iterdir():
            if not task_dir.is_dir():
                continue
            meta_path = task_dir / "task.json"
            if meta_path.exists():
                tasks.append(json.loads(meta_path.read_text(encoding="utf-8")))
        tasks.sort(key=lambda item: item["created_at"], reverse=True)
        return tasks

    def create_task(self, files: list[UploadFile]) -> dict:
        task_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
        task_dir = self.runs_dir / task_id
        attachments_dir = task_dir / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)

        attachments: list[dict] = []
        for index, upload in enumerate(files, start=1):
            file_name = upload.filename or f"upload-{index}.bin"
            destination = attachments_dir / file_name
            with destination.open("wb") as target:
                shutil.copyfileobj(upload.file, target)
            attachments.append(
                {
                    "attachment_id": f"att-{index:03d}",
                    "file_name": file_name,
                    "file_path": str(destination),
                    "size": destination.stat().st_size,
                    "mime_type": upload.content_type,
                }
            )

        meta = {
            "task_id": task_id,
            "status": "ready",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "attachment_count": len(attachments),
            "attachments": attachments,
        }
        self._write_json(task_dir / "task.json", meta)
        return meta

    def save_workflow_result(self, task_id: str, payload: dict) -> None:
        task_dir = self.runs_dir / task_id
        task_json = task_dir / "task.json"
        if task_json.exists():
            meta = json.loads(task_json.read_text(encoding="utf-8"))
            meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
            meta["status"] = payload.get("status", meta.get("status", "ready"))
            self._write_json(task_json, meta)
        self._write_json(task_dir / "workflow.json", payload)

    def save_export_payload(self, task_id: str, payload: dict) -> None:
        task_dir = self.runs_dir / task_id
        self._write_json(task_dir / "export.json", payload)

    def get_task_detail(self, task_id: str) -> dict:
        task_dir = self.runs_dir / task_id
        task_path = task_dir / "task.json"
        workflow_path = task_dir / "workflow.json"
        if not task_path.exists():
            raise FileNotFoundError(task_id)

        detail = {
            "task": json.loads(task_path.read_text(encoding="utf-8")),
            "workflow": {},
        }
        if workflow_path.exists():
            detail["workflow"] = json.loads(workflow_path.read_text(encoding="utf-8"))
        return detail

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_task_store(project_root: str | Path) -> TaskStore:
    return TaskStore(project_root)
