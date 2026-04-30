from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


def make_task_session_factory():
    """Build an async sessionmaker bound to a brand-new engine with NullPool.

    Celery tasks create a new asyncio event loop per invocation. The default
    module-level ``engine`` keeps asyncpg connections in a pool whose
    ``Future`` objects are bound to whichever loop first opened them, leading
    to ``RuntimeError: ... attached to a different loop`` on later calls.
    Using a fresh engine + ``NullPool`` per task invocation guarantees every
    connection lives only on the current loop, then is closed at the end.
    """
    task_engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)
    return task_engine, factory
