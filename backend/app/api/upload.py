"""文档上传 API —— 上传 → 解析 → 分块 → 向量化 → 入库"""

import os
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.models.db_models import Course, Document, Chunk
from app.models.schemas import DocumentUploadResponse
from app.rag.document_processor import parse_document, smart_chunk
from app.rag.vector_store import upsert_chunks

settings = get_settings()
router = APIRouter(prefix="/api/documents", tags=["文档管理"])


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """上传课程文档，自动解析、分块、向量化"""

    # ── 1. 校验文件格式 ──
    ext = Path(file.filename).suffix.lower().lstrip(".")
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 '.{ext}'，允许: {', '.join(settings.allowed_extensions)}",
        )

    # ── 2. 校验课程存在 ──
    from sqlalchemy import select
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在，请先创建课程")

    # ── 3. 保存文件到本地 ──
    upload_dir = Path(settings.upload_dir) / course_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{file.filename}"
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # ── 4. 解析文档 ──
    try:
        full_text = parse_document(str(file_path))
    except Exception as e:
        os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"文档解析失败: {str(e)}")

    # ── 5. 智能分块 ──
    chunks = smart_chunk(full_text)
    if not chunks:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail="文档内容为空或无法提取文本")

    # ── 6. 存入 Qdrant 向量数据库 ──
    from app.models.db_models import gen_uuid
    doc_id = gen_uuid()

    try:
        upsert_chunks(chunks, course_id=course_id, document_id=doc_id)
    except Exception as e:
        os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"向量化存储失败: {str(e)}")

    # ── 7. 记录到 PostgreSQL ──
    document = Document(
        id=doc_id,
        course_id=course_id,
        filename=file.filename,
        file_type=ext,
        file_size=file_path.stat().st_size,
        chunk_count=len(chunks),
        storage_path=str(file_path),
    )
    db.add(document)

    for chunk_data in chunks:
        chunk = Chunk(
            document_id=doc_id,
            qdrant_point_id=chunk_data["qdrant_point_id"],
            content=chunk_data["content"],
            chunk_index=chunk_data["chunk_index"],
            page_number=chunk_data.get("page_number"),
            metadata_={"filename": file.filename, "course_id": course_id},
        )
        db.add(chunk)

    await db.flush()

    return DocumentUploadResponse(
        document_id=doc_id,
        filename=file.filename,
        chunk_count=len(chunks),
        status="success",
    )
