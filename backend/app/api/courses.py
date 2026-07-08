"""课程管理 API"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.db_models import Course, Document, Chunk, gen_uuid
from app.models.schemas import CourseCreate, CourseResponse

router = APIRouter(prefix="/api/courses", tags=["课程管理"])


@router.post("/", response_model=CourseResponse)
async def create_course(course: CourseCreate, db: AsyncSession = Depends(get_db)):
    """创建课程"""
    c = Course(id=gen_uuid(), name=course.name, description=course.description)
    db.add(c)
    await db.flush()
    return CourseResponse(
        id=c.id, name=c.name, description=c.description,
        document_count=0, chunk_count=0, created_at=c.created_at,
    )


@router.get("/", response_model=list[CourseResponse])
async def list_courses(db: AsyncSession = Depends(get_db)):
    """列出所有课程"""
    result = await db.execute(select(Course).order_by(Course.created_at.desc()))
    courses = result.scalars().all()

    resp = []
    for c in courses:
        # 统计文档数和分块数
        doc_count = (await db.execute(
            select(func.count(Document.id)).where(Document.course_id == c.id)
        )).scalar() or 0
        chunk_count = (await db.execute(
            select(func.count(Chunk.id)).where(
                Chunk.document_id.in_(
                    select(Document.id).where(Document.course_id == c.id)
                )
            )
        )).scalar() or 0

        resp.append(CourseResponse(
            id=c.id, name=c.name, description=c.description,
            document_count=doc_count, chunk_count=chunk_count,
            created_at=c.created_at,
        ))
    return resp


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(course_id: str, db: AsyncSession = Depends(get_db)):
    """获取课程详情"""
    result = await db.execute(select(Course).where(Course.id == course_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="课程不存在")

    doc_count = (await db.execute(
        select(func.count(Document.id)).where(Document.course_id == c.id)
    )).scalar() or 0
    chunk_count = (await db.execute(
        select(func.count(Chunk.id)).where(
            Chunk.document_id.in_(
                select(Document.id).where(Document.course_id == c.id)
            )
        )
    )).scalar() or 0

    return CourseResponse(
        id=c.id, name=c.name, description=c.description,
        document_count=doc_count, chunk_count=chunk_count,
        created_at=c.created_at,
    )


@router.delete("/{course_id}")
async def delete_course(course_id: str, db: AsyncSession = Depends(get_db)):
    """删除课程及其所有文档和向量"""
    result = await db.execute(select(Course).where(Course.id == course_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 删除 Qdrant 中的向量
    from app.rag.vector_store import delete_document_vectors
    docs_result = await db.execute(select(Document).where(Document.course_id == course_id))
    for doc in docs_result.scalars().all():
        delete_document_vectors(doc.id)

    await db.delete(c)
    await db.flush()
    return {"message": "课程已删除", "course_id": course_id}
