"""文档解析 + 智能分块"""

import os
import uuid
import re
from pathlib import Path
from app.core.config import get_settings

settings = get_settings()


def parse_document(file_path: str) -> str:
    """
    多格式文档解析 → 纯文本
    支持: PDF / PPT / PPTX / DOC / DOCX / MD / TXT
    """
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        return _parse_pdf(file_path)
    elif ext in (".ppt", ".pptx"):
        return _parse_ppt(file_path)
    elif ext == ".docx":
        return _parse_docx(file_path)
    elif ext == ".doc":
        # 旧格式 .doc 不支持，提示用户另存为 .docx
        raise ValueError("不支持旧版 .doc 格式，请在 Word 中另存为 .docx 格式后再上传")
    elif ext in (".md", ".txt"):
        return Path(file_path).read_text(encoding="utf-8")
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def _parse_pdf(file_path: str) -> str:
    """PDF 解析，保留页码信息"""
    import fitz  # PyMuPDF
    doc = fitz.open(file_path)
    texts = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text()
        if text.strip():
            texts.append(f"[PAGE:{page_num}]\n{text}")
    return "\n\n".join(texts)


def _parse_ppt(file_path: str) -> str:
    """PPT 解析"""
    from pptx import Presentation
    prs = Presentation(file_path)
    texts = []
    for slide_num, slide in enumerate(prs.slides, start=1):
        slide_texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    if para.text.strip():
                        slide_texts.append(para.text)
        if slide_texts:
            texts.append(f"[SLIDE:{slide_num}]\n" + "\n".join(slide_texts))
    return "\n\n".join(texts)


def _parse_docx(file_path: str) -> str:
    """Word 文档解析"""
    from docx import Document
    doc = Document(file_path)
    texts = []
    for para in doc.paragraphs:
        if para.text.strip():
            # 检测标题样式
            if para.style.name.startswith("Heading"):
                level = para.style.name.split()[-1]
                texts.append(f"{'#' * int(level)} {para.text}")
            else:
                texts.append(para.text)
    return "\n\n".join(texts)


def smart_chunk(text: str, chunk_size: int = None, overlap: int = None) -> list[dict]:
    """Page-contained chunks with a hard character bound and exact page metadata."""
    chunk_size = settings.chunk_size if chunk_size is None else chunk_size
    overlap = settings.chunk_overlap if overlap is None else overlap
    if chunk_size < 1 or not 0 <= overlap < chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0")
    sections = re.split(r"\[(?:PAGE|SLIDE):(\d+)\]\n", text)
    pages = [(None, sections[0])]
    pages.extend((int(sections[i]), sections[i + 1]) for i in range(1, len(sections), 2))
    chunks = []
    for page, content in pages:
        content = content.strip()
        start = 0
        while start < len(content):
            end = min(start + chunk_size, len(content))
            if end < len(content):
                boundary = max(content.rfind("\n", start + chunk_size // 2, end),
                               content.rfind("。", start + chunk_size // 2, end))
                if boundary >= 0:
                    end = boundary + 1
            piece = content[start:end].strip()
            if piece:
                chunks.append({"id": str(uuid.uuid4()), "content": piece,
                               "chunk_index": len(chunks), "page_number": page, "page_end": page})
            if end == len(content):
                break
            start = max(start + 1, end - overlap)
    return chunks
