"""Bug report endpoints - users submit, admins manage."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import BugReport, User

router = APIRouter(prefix="/api/bug-reports", tags=["bug-reports"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "bug_report_attachments"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _ensure_upload_dir():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---- User endpoints ----


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_bug_report(
    title: str = Form(...),
    description: str = Form(...),
    severity: str = Form("medium"),
    attachment: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    if severity not in ("low", "medium", "high", "critical"):
        raise HTTPException(status_code=422, detail="Severity must be low, medium, high, or critical")

    attachment_filename = None
    attachment_path = None

    if attachment and attachment.filename:
        contents = await attachment.read()
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="Attachment must be under 10 MB")
        _ensure_upload_dir()
        ext = Path(attachment.filename).suffix
        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest = UPLOAD_DIR / stored_name
        dest.write_bytes(contents)
        attachment_filename = attachment.filename
        attachment_path = stored_name

    report = BugReport(
        user_id=user.id,
        title=title,
        description=description,
        severity=severity,
        attachment_filename=attachment_filename,
        attachment_path=attachment_path,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return _serialize(report)


@router.get("/mine")
async def list_my_reports(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(BugReport).where(BugReport.user_id == user.id).order_by(BugReport.created_at.desc())
    )
    return [_serialize(r) for r in result.scalars().all()]


# ---- Admin endpoints ----


@router.get("/")
async def list_all_reports(
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(BugReport).order_by(BugReport.created_at.desc())
    if status_filter:
        q = q.where(BugReport.status == status_filter)
    result = await db.execute(q)
    return [_serialize(r) for r in result.scalars().all()]


@router.get("/stats")
async def report_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    total = (await db.execute(select(func.count(BugReport.id)))).scalar() or 0
    open_count = (await db.execute(select(func.count(BugReport.id)).where(BugReport.status == "open"))).scalar() or 0
    in_progress = (
        await db.execute(select(func.count(BugReport.id)).where(BugReport.status == "in_progress"))
    ).scalar() or 0
    resolved = (await db.execute(select(func.count(BugReport.id)).where(BugReport.status == "resolved"))).scalar() or 0
    return {"total": total, "open": open_count, "in_progress": in_progress, "resolved": resolved}


@router.patch("/{report_id}")
async def update_report(
    report_id: str,
    status_val: str | None = Form(None, alias="status"),
    admin_notes: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    report = await db.get(BugReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Bug report not found")
    if status_val:
        if status_val not in ("open", "in_progress", "resolved", "closed", "wont_fix"):
            raise HTTPException(status_code=422, detail="Invalid status")
        report.status = status_val
    if admin_notes is not None:
        report.admin_notes = admin_notes
    await db.commit()
    await db.refresh(report)
    return _serialize(report)


@router.get("/{report_id}/attachment")
async def download_attachment(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    report = await db.get(BugReport, report_id)
    if not report or not report.attachment_path:
        raise HTTPException(status_code=404, detail="No attachment found")
    filepath = UPLOAD_DIR / report.attachment_path
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Attachment file missing")
    return FileResponse(filepath, filename=report.attachment_filename)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    report = await db.get(BugReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Bug report not found")
    if report.attachment_path:
        filepath = UPLOAD_DIR / report.attachment_path
        if filepath.exists():
            filepath.unlink()
    await db.delete(report)
    await db.commit()


def _serialize(r: BugReport) -> dict:
    return {
        "id": str(r.id),
        "user_id": str(r.user_id),
        "username": r.user.username if r.user else None,
        "email": r.user.email if r.user else None,
        "title": r.title,
        "description": r.description,
        "severity": r.severity,
        "status": r.status,
        "admin_notes": r.admin_notes,
        "has_attachment": bool(r.attachment_path),
        "attachment_filename": r.attachment_filename,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
