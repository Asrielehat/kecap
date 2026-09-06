"""Bounded uploads with durable recovery records and source previews."""
import asyncio
import json
import logging
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db, async_session
from app.core.config import get_settings
from app.core.work import run_blocking
from app.models.db_models import Course, Document, Chunk, gen_uuid
from app.models.schemas import DocumentUploadResponse
from app.rag.document_processor import parse_document, smart_chunk
from app.rag.vector_store import upsert_chunks, delete_document_vectors

settings = get_settings()
router = APIRouter(prefix="/api/documents", tags=["文档管理"])
log = logging.getLogger(__name__)
upload_slots = asyncio.Semaphore(2)


def job_path(job_id):
    try:
        job_id = str(UUID(job_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "无效的上传任务 ID")
    root = Path(settings.upload_dir).resolve() / ".jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{job_id}.json"


def write_job(job, **updates):
    job.update(updates)
    path = job_path(job["id"])
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def validate_filename(filename):
    if not filename or any(c in filename for c in ('/', '\\', ':', '\x00')) or filename in ('.', '..'):
        raise HTTPException(400, "文件名不能包含路径")
    ext = Path(filename).suffix.lower().lstrip('.')
    if ext not in settings.allowed_extensions:
        raise HTTPException(400, "支持 PDF、PPTX、DOCX、MD、TXT；旧版 Office 文件请先另存为新版格式")
    return ext


def save_upload(source, target, limit):
    size = 0
    with target.open("xb") as output:
        while block := source.read(1024 * 1024):
            size += len(block)
            if size > limit:
                raise HTTPException(413, f"文件超过 {settings.max_upload_size_mb} MB 上限")
            output.write(block)
    if not size:
        raise HTTPException(400, "文件为空")
    return size


def prepare_upload(file, target, course_id, job):
    size = save_upload(file.file, target, settings.max_upload_size_mb * 1024 * 1024)
    write_job(job, status="parsing", progress=10)
    chunks = smart_chunk(parse_document(str(target)))
    if not chunks:
        raise HTTPException(400, "未提取到文字；扫描版 PDF 请先进行 OCR")
    write_job(job, status="indexing", progress=20)
    upsert_chunks(chunks, course_id, job["id"], progress=lambda value: write_job(job, progress=20 + int(value * 70)))
    return size, chunks


def compensate(job):
    delete_document_vectors(job["id"])
    target = Path(job["path"]).resolve()
    if target.is_relative_to(Path(settings.upload_dir).resolve()):
        target.unlink(missing_ok=True)
    write_job(job, status="failed", progress=0)


async def recover_uploads():
    root = Path(settings.upload_dir) / ".jobs"
    if not root.exists():
        return
    for path in root.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["status"] in ("success", "failed"):
                continue
            async with async_session() as db:
                committed = await db.get(Document, job["id"])
            if committed:
                write_job(job, status="success", progress=100)
            else:
                await run_blocking(compensate, job)
        except Exception:
            log.exception("上传恢复失败，将在下次启动重试")


@router.get("/jobs/{job_id}")
async def upload_status(job_id: str):
    path = job_path(job_id)
    if not path.exists():
        return {"status": "uploading", "progress": 0}
    job = json.loads(path.read_text(encoding="utf-8"))
    return {key: job.get(key) for key in ("status", "progress", "error")}


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...), course_id: str = Form(...),
                          upload_id: str | None = Form(None), db: AsyncSession = Depends(get_db)):
    ext = validate_filename(file.filename)
    if not await db.get(Course, course_id):
        raise HTTPException(404, "课程不存在")
    doc_id = gen_uuid()
    if upload_id:
        job_path(upload_id)
        doc_id = str(UUID(upload_id))
    if job_path(doc_id).exists():
        raise HTTPException(409, "上传任务已存在，请使用新任务 ID 重试")
    target = Path(settings.upload_dir).resolve() / f"{doc_id}.{ext}"
    job = {"id": doc_id, "path": str(target), "status": "uploading", "progress": 0}
    write_job(job)
    async with upload_slots:
        worker = asyncio.create_task(run_blocking(prepare_upload, file, target, course_id, job))
        try:
            size, chunks = await asyncio.shield(worker)
            db.add(Document(id=doc_id, course_id=course_id, filename=file.filename, file_type=ext,
                            file_size=size, chunk_count=len(chunks), storage_path=str(target)))
            for chunk in chunks:
                db.add(Chunk(id=chunk["id"], document_id=doc_id, qdrant_point_id=chunk["qdrant_point_id"],
                             content=chunk["content"], chunk_index=chunk["chunk_index"],
                             page_number=chunk.get("page_number"),
                             metadata_={"filename": file.filename, "course_id": course_id,
                                        "page_end": chunk.get("page_end")}))
            write_job(job, status="saving", progress=95)
            await db.commit()
        except BaseException as error:
            try:
                await worker
            except BaseException:
                pass
            await db.rollback()
            write_job(job, status="cleanup_pending", error="上传失败，请重试")
            try:
                await run_blocking(compensate, job)
            except Exception:
                log.exception("清理延期至下次启动")
            if isinstance(error, (HTTPException, asyncio.CancelledError)):
                raise
            log.exception("上传失败")
            raise HTTPException(500, "文档处理失败，请检查文件和服务配置后重试") from error
        finally:
            await file.close()
    write_job(job, status="success", progress=100)
    return DocumentUploadResponse(document_id=doc_id, filename=file.filename, chunk_count=len(chunks), status="success")


@router.get("/chunks/{chunk_id}")
async def source_chunk(chunk_id: str, db: AsyncSession = Depends(get_db)):
    chunk = await db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(404, "未找到原文片段，旧资料请重新上传以启用定位")
    doc = await db.get(Document, chunk.document_id)
    return {"content": chunk.content, "page": chunk.page_number,
            "page_end": (chunk.metadata_ or {}).get("page_end"), "filename": doc.filename,
            "source_url": f"/api/documents/{doc.id}/file"}


@router.get("/{document_id}/file")
async def source_file(document_id: str, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, document_id)
    if not doc or not doc.storage_path:
        raise HTTPException(404, "文档不存在")
    path = Path(doc.storage_path).resolve()
    if not path.is_relative_to(Path(settings.upload_dir).resolve()) or not path.is_file():
        raise HTTPException(404, "原文件不存在")
    return FileResponse(path, filename=doc.filename,
                        media_type="application/pdf" if doc.file_type == "pdf" else "application/octet-stream",
                        content_disposition_type="inline" if doc.file_type == "pdf" else "attachment")
