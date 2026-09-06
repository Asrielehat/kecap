"""Bounded blocking work; cooperative cancellation propagates across pipeline stages."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from threading import Event
import asyncio

from app.core.config import get_settings

cancel_event: ContextVar[Event | None] = ContextVar("cancel_event", default=None)
evidence_mode: ContextVar[str] = ContextVar("evidence_mode", default="supplement")
executor = ThreadPoolExecutor(max_workers=get_settings().max_chat_workers, thread_name_prefix="kecap")
slots = asyncio.Semaphore(get_settings().max_chat_workers)


def checkpoint():
    event = cancel_event.get()
    if event is not None and event.is_set():
        raise InterruptedError("生成已停止")


async def run_blocking(fn, *args, **kwargs):
    async with slots:
        context = copy_context()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, lambda: context.run(fn, *args, **kwargs))
