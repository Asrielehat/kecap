import asyncio
import io
import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.core.config import get_settings
from app.core.database import async_session
from app.core.work import cancel_event, checkpoint
from app.models.db_models import Document, Message
from app.rag.document_processor import smart_chunk
from app.rag.lexical import bm25, reciprocal_rank_fusion
from app.rag import vector_store, retriever
from app.api import chat, upload
from app.models.schemas import ChatRequest


class ChunkTests(unittest.TestCase):
    def test_long_paragraph_and_zero_overlap(self):
        chunks = smart_chunk("a" * 2001, 800, 0)
        self.assertEqual([len(c["content"]) for c in chunks], [800, 800, 401])
        self.assertEqual("".join(c["content"] for c in chunks), "a" * 2001)

    def test_pages_never_mix(self):
        chunks = smart_chunk("[PAGE:1]\n第一页\n\n[PAGE:2]\n第二页", 800, 150)
        self.assertEqual([(c["page_number"], c["page_end"]) for c in chunks], [(1, 1), (2, 2)])
        self.assertEqual(chunks[1]["content"], "第二页")

    def test_invalid_overlap(self):
        with self.assertRaises(ValueError):
            smart_chunk("abc", 10, 10)

    def test_cancellation(self):
        event = threading.Event()
        token = cancel_event.set(event)
        try:
            event.set()
            with self.assertRaises(InterruptedError):
                checkpoint()
        finally:
            cancel_event.reset(token)

    def test_bm25_and_fusion(self):
        corpus = [{"chunk_id": "a", "content": "栈遵循后进先出"}, {"chunk_id": "b", "content": "队列先进先出"}]
        self.assertEqual(bm25("栈后进先出", corpus)[0]["chunk_id"], "a")
        result = reciprocal_rank_fusion([corpus[0]], [corpus[0], corpus[1]])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["chunk_id"], "a")

    def test_disabled_reranker_not_loaded(self):
        with patch.object(retriever.settings, "reranker_enabled", False), patch.object(retriever, "_get_reranker") as loader:
            retriever.rerank("q", [{"score": i} for i in range(5)], 2)
            loader.assert_not_called()

    def test_embedding_batches_and_order(self):
        def embed(**kwargs):
            return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[float(i)]) for i in reversed(range(len(kwargs["input"])))])
        client = SimpleNamespace(embeddings=SimpleNamespace(create=unittest.mock.Mock(side_effect=embed)))
        with patch.object(vector_store, "_get_embedding_client", return_value=client), patch.object(vector_store.settings, "embedding_batch_size", 2):
            self.assertEqual(vector_store.embed_texts(["a", "b", "c"]), [[0.], [1.], [0.]])
            self.assertEqual(client.embeddings.create.call_count, 2)

    def test_strict_without_sources_does_not_call_model(self):
        from app.rag.generator import generate_answer_stream, llm_client
        from app.core.work import evidence_mode
        token = evidence_mode.set("strict")
        try:
            with patch.object(llm_client.chat.completions, "create") as create:
                result = list(generate_answer_stream("未知问题", []))
                self.assertIn("未检索到", result[0][1])
                create.assert_not_called()
        finally:
            evidence_mode.reset(token)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        vector_store._get_qdrant().close()

    def setUp(self):
        self.course = self.client.post("/api/courses/", json={"name": "测试课程"}).json()["id"]

    def send_upload(self, name="notes.txt", content=b"course text"):
        return self.client.post("/api/documents/upload", data={"course_id": self.course}, files={"file": (name, content)})

    def test_filename_rejection(self):
        for name in ("../outside.txt", "..\\outside.txt", "C:outside.txt"):
            with self.subTest(name=name):
                self.assertEqual(self.send_upload(name).status_code, 400)

    def test_size_limit(self):
        with patch.object(upload.settings, "max_upload_size_mb", 0):
            self.assertEqual(self.send_upload().status_code, 413)

    def test_same_filename_and_source(self):
        with patch.object(vector_store, "embed_texts", side_effect=lambda texts: [[1., 0., 0., 0.] for _ in texts]):
            first, second = self.send_upload(), self.send_upload(content=b"different")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(first.json()["document_id"], second.json()["document_id"])
        paths = list(Path(get_settings().upload_dir).glob("*.txt"))
        self.assertTrue(any(p.read_bytes() == b"course text" for p in paths))
        self.assertTrue(any(p.read_bytes() == b"different" for p in paths))

    def test_vector_failure_compensates(self):
        with patch.object(upload, "upsert_chunks", side_effect=RuntimeError("offline")):
            response = self.send_upload()
        self.assertEqual(response.status_code, 500)
        jobs = [json.loads(p.read_text(encoding="utf8")) for p in (Path(get_settings().upload_dir) / ".jobs").glob("*.json")]
        failed = [job for job in jobs if job["status"] == "failed"]
        self.assertTrue(failed)
        self.assertTrue(all(not Path(job["path"]).exists() for job in failed))

    def test_database_failure_removes_vectors(self):
        from sqlalchemy.ext.asyncio import AsyncSession
        with patch.object(vector_store, "embed_texts", side_effect=lambda texts: [[1., 0., 0., 0.] for _ in texts]), \
             patch.object(AsyncSession, "commit", new=AsyncMock(side_effect=RuntimeError("db failed"))), \
             patch.object(upload, "delete_document_vectors", wraps=upload.delete_document_vectors) as cleanup:
            response = self.send_upload()
        self.assertEqual(response.status_code, 500)
        cleanup.assert_called_once()

    def test_stream_error_is_persisted(self):
        with patch.object(chat, "_retrieve_docs", side_effect=RuntimeError("provider failed")):
            response = self.client.post("/api/chat/ask/stream", json={"course_id": self.course, "question": "问题"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertIn("error", [event["type"] for event in events])
        self.assertEqual(events[-1]["data"]["status"], "failed")
        conv = events[0]["conversation_id"]
        history = self.client.get(f"/api/conversations/{conv}/messages").json()["messages"]
        self.assertEqual(history[-1]["status"], "failed")

    def test_stream_complete_and_course_mismatch(self):
        def generate(*args, **kwargs):
            yield "token", "答案"
        with patch.object(chat, "_retrieve_docs", return_value=[]), patch.object(chat, "generate_answer_stream", side_effect=generate):
            response = self.client.post("/api/chat/ask/stream", json={"course_id": self.course, "question": "问题"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["data"]["status"], "complete")
        other = self.client.post("/api/courses/", json={"name": "其他"}).json()["id"]
        response = self.client.post("/api/chat/ask/stream", json={"course_id": other, "conversation_id": events[0]["conversation_id"], "question": "问题"})
        self.assertEqual(response.status_code, 404)

    def test_disconnect_saves_partial_and_cancels_later_work(self):
        release = threading.Event()
        finished = threading.Event()
        later_work = []
        def generate(*args, **kwargs):
            try:
                yield "token", "部分答案"
                release.wait(3)
                checkpoint()
                later_work.append("must not run")
                yield "token", "后续答案"
            finally:
                finished.set()
        async def disconnect():
            async with async_session() as db:
                response = await chat.ask_stream(ChatRequest(course_id=self.course, question="断开测试"), db)
                stream = response.body_iterator
                for _ in range(8):
                    event = await anext(stream)
                    if '"type": "token"' in event:
                        break
                await stream.aclose()
                release.set()
                rows = (await db.execute(select(Message).where(Message.content == "部分答案"))).scalars().all()
                self.assertEqual(rows[-1].status, "interrupted")
        with patch.object(chat, "_retrieve_docs", return_value=[]), patch.object(chat, "generate_answer_stream", side_effect=generate):
            self.client.portal.call(disconnect)
            self.assertTrue(finished.wait(3))
        self.assertEqual(later_work, [])

    def test_recovery_retries_pending_cleanup(self):
        job_id = upload.gen_uuid()
        target = Path(get_settings().upload_dir) / f"{job_id}.txt"
        target.write_text("orphan")
        job = {"id": job_id, "path": str(target), "status": "cleanup_pending"}
        upload.write_job(job)
        self.client.portal.call(upload.recover_uploads)
        self.assertFalse(target.exists())
        self.assertEqual(json.loads(upload.job_path(job_id).read_text())["status"], "failed")

    def test_source_preview(self):
        with patch.object(vector_store, "embed_texts", side_effect=lambda texts: [[1., 0., 0., 0.] for _ in texts]):
            response = self.send_upload(content=b"source preview")
        async def find_chunk():
            from app.models.db_models import Chunk
            async with async_session() as db:
                return (await db.execute(select(Chunk.id).where(Chunk.document_id == response.json()["document_id"]))).scalar_one()
        chunk_id = self.client.portal.call(find_chunk)
        preview = self.client.get(f"/api/documents/chunks/{chunk_id}").json()
        self.assertEqual(preview["content"], "source preview")
        self.assertEqual(self.client.get(preview["source_url"]).content, b"source preview")
