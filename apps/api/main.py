from pathlib import Path

from fastapi.responses import FileResponse
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from core.config.settings import get_settings
from core.exporters.voucher_json import build_empty_payload
from core.learning.memory import append_confirmed_export, learning_summary, list_learning_entries
from core.knowledge.indexer import bootstrap_knowledge, knowledge_summary, search_accounts
from core.ops import build_readiness_report
from core.schemas.models import ReviewRequest
from core.storage.task_store import get_task_store
from core.workflows.graph import build_workflow_overview
from core.workflows.voucher_pipeline import apply_review_actions, export_voucher_payload, run_voucher_pipeline


settings = get_settings()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
task_store = get_task_store(PROJECT_ROOT)

app = FastAPI(
    title="Voucher Auto Entry API",
    version="0.1.0",
    description="Local API for the AI-assisted voucher entry workflow.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
async def config() -> dict[str, str]:
    return {
        "model": settings.modelscope_chat_model,
        "embedding_model_path": settings.embedding_model_path,
        "lancedb_uri": settings.lancedb_uri,
    }


@app.get("/api/workflow")
async def workflow() -> dict[str, list[dict[str, str]]]:
    return build_workflow_overview()


@app.get("/api/knowledge/summary")
async def knowledge_state() -> dict:
    return knowledge_summary(PROJECT_ROOT)


@app.get("/api/readiness")
async def readiness_state() -> dict:
    return build_readiness_report(PROJECT_ROOT)


@app.get("/api/learning/summary")
async def learning_state() -> dict:
    return learning_summary(PROJECT_ROOT)


@app.get("/api/learning/records")
async def learning_records(limit: int = 20) -> dict:
    return {"items": list_learning_entries(PROJECT_ROOT, limit=limit)}


@app.get("/api/knowledge/search")
async def knowledge_search(q: str, limit: int = 10) -> dict:
    return {"items": search_accounts(PROJECT_ROOT, q, limit=limit)}


@app.post("/api/knowledge/bootstrap")
async def knowledge_bootstrap() -> dict:
    return bootstrap_knowledge(PROJECT_ROOT)


@app.get("/api/tasks")
async def list_tasks() -> dict:
    return {"items": task_store.list_tasks()}


@app.post("/api/tasks")
async def create_task(files: list[UploadFile] = File(...)) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")
    task = task_store.create_task(files)
    workflow = run_voucher_pipeline(PROJECT_ROOT, task)
    task_store.save_workflow_result(task["task_id"], workflow)
    return {"task": task, "workflow": workflow}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    try:
        return task_store.get_task_detail(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}") from exc


@app.get("/api/tasks/{task_id}/attachments/{attachment_id}")
async def get_task_attachment(task_id: str, attachment_id: str) -> FileResponse:
    try:
        detail = task_store.get_task_detail(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}") from exc

    attachment = next(
        (item for item in detail["task"].get("attachments", []) if item.get("attachment_id") == attachment_id),
        None,
    )
    if not attachment:
        raise HTTPException(status_code=404, detail=f"Attachment not found: {attachment_id}")

    file_path = Path(str(attachment["file_path"]))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Attachment file does not exist on disk.")

    return FileResponse(
        path=file_path,
        media_type=attachment.get("mime_type") or "application/octet-stream",
        filename=attachment.get("file_name") or file_path.name,
    )


@app.post("/api/tasks/{task_id}/review")
async def review_task(task_id: str, request: ReviewRequest) -> dict:
    try:
        detail = task_store.get_task_detail(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}") from exc

    workflow = apply_review_actions(detail, request.lines, request.voucher_date)
    task_store.save_workflow_result(task_id, workflow)
    return {"task": detail["task"], "workflow": workflow}


@app.post("/api/tasks/{task_id}/export")
async def export_task(task_id: str) -> dict:
    try:
        detail = task_store.get_task_detail(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}") from exc

    try:
        payload = export_voucher_payload(detail)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    task_store.save_export_payload(task_id, payload)
    learned_entries = append_confirmed_export(detail, payload, PROJECT_ROOT)
    return {"task_id": task_id, "payload": payload, "learning": {"captured": len(learned_entries)}}


@app.get("/api/voucher/template")
async def voucher_template() -> dict:
    return build_empty_payload(settings)
