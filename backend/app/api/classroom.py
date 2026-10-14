"""PDF document listing and optimistic, page-level ink synchronization."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.db_models import Course, Document, PageAnnotation

router = APIRouter(prefix="/api/classroom", tags=["上课模式"])


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    pressure: float = Field(ge=0, le=1)


class Stroke(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    tool: str = Field(pattern="^(pen|highlighter)$")
    color: str = Field(pattern="^#[0-9a-fA-F]{6}$")
    width: float = Field(ge=0.5, le=40)
    points: list[Point] = Field(min_length=1, max_length=10000)


class AnnotationWrite(BaseModel):
    base_version: int = Field(ge=0)
    strokes: list[Stroke] = Field(max_length=3000)


async def pdf_document(document_id: str, db: AsyncSession) -> Document:
    doc = await db.get(Document, document_id)
    if not doc or doc.file_type != "pdf":
        raise HTTPException(404, "PDF 不存在")
    return doc


@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document, Course.name).join(Course, Course.id == Document.course_id)
        .where(Document.file_type == "pdf").order_by(Document.created_at.desc())
    )
    return [dict(id=doc.id, course_id=doc.course_id, course_name=name,
                 filename=doc.filename, file_size=doc.file_size)
            for doc, name in result.all()]


@router.get("/documents/{document_id}/pages/{page_number}")
async def get_page(document_id: str, page_number: int, db: AsyncSession = Depends(get_db)):
    await pdf_document(document_id, db)
    if page_number < 1:
        raise HTTPException(400, "页码无效")
    row = await db.get(PageAnnotation, (document_id, page_number))
    return {"version": row.version if row else 0, "strokes": row.strokes if row else [],
            "updated_at": row.updated_at if row else None}


@router.put("/documents/{document_id}/pages/{page_number}")
async def put_page(document_id: str, page_number: int, body: AnnotationWrite,
                   db: AsyncSession = Depends(get_db)):
    await pdf_document(document_id, db)
    if page_number < 1:
        raise HTTPException(400, "页码无效")
    strokes = [s.model_dump() for s in body.strokes]
    now = datetime.utcnow()
    if body.base_version == 0:
        row = await db.get(PageAnnotation, (document_id, page_number))
        if row:
            raise HTTPException(409, detail={"message": "远端注释已变更", "version": row.version})
        db.add(PageAnnotation(document_id=document_id, page_number=page_number,
                              version=1, strokes=strokes, updated_at=now))
        try:
            await db.flush()
        except Exception:
            await db.rollback()
            raise HTTPException(409, "远端注释已变更")
        return {"version": 1, "updated_at": now}
    result = await db.execute(
        update(PageAnnotation).where(PageAnnotation.document_id == document_id,
                                     PageAnnotation.page_number == page_number,
                                     PageAnnotation.version == body.base_version)
        .values(version=body.base_version + 1, strokes=strokes, updated_at=now)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "远端注释已变更；本地笔迹仍保留，请先备份再处理冲突")
    return {"version": body.base_version + 1, "updated_at": now}
