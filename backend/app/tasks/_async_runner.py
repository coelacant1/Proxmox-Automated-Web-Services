"""Run async coroutines from sync Celery tasks with a fresh DB engine per call.

Celery prefork workers create a brand-new asyncio event loop on every task
invocation. The application-wide SQLAlchemy ``engine`` keeps an asyncpg
connection pool whose ``Future`` wakeups are bound to whichever loop first
touched them, so the *second* task that runs in a worker explodes with
``RuntimeError: ... attached to a different loop``.

To keep task code unchanged (it just does ``from app.core.database import
async_session``), this helper monkey-patches ``app.core.database.engine`` and
``async_session`` to a fresh ``NullPool`` engine for the lifetime of the call,
then disposes it and restores the originals.
"""

from __future__ import annotations

import asyncio


def run_task_async(coro):
    from app.core import database as db_module

    async def _runner():
        task_engine, task_session = db_module.make_task_session_factory()
        original_engine = db_module.engine
        original_session = db_module.async_session
        db_module.engine = task_engine
        db_module.async_session = task_session
        try:
            return await coro
        finally:
            db_module.engine = original_engine
            db_module.async_session = original_session
            await task_engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_runner())
    finally:
        loop.close()
