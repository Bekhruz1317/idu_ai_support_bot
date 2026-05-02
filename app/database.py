import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Log, StudentInfo, User

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "bot_data.db"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}")

engine = create_async_engine(DATABASE_URL, future=True)
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


def _run_alembic_upgrade() -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    sync_url = DATABASE_URL.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url)
    try:
        names = set(inspect(sync_engine).get_table_names())
    finally:
        sync_engine.dispose()

    # Pre-existing DB without alembic tracking: stamp current schema as head.
    if {"users", "logs"}.issubset(names) and "alembic_version" not in names:
        logger.info("Existing schema detected without alembic_version — stamping head.")
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


async def init_db() -> None:
    """Apply Alembic migrations to head."""
    await asyncio.to_thread(_run_alembic_upgrade)


async def insert_or_update_user(user_id: int, username: Optional[str]) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if user is None:
                session.add(User(user_id=user_id, username=username))
            else:
                user.username = username
                user.last_seen = datetime.utcnow()


async def log_message(
    user_id: int, message: str, predicted_intent: str, confidence: float
) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            session.add(
                Log(
                    user_id=user_id,
                    message=message,
                    predicted_intent=predicted_intent,
                    confidence=confidence,
                )
            )


async def get_student_by_id(student_id: str) -> Optional[StudentInfo]:
    """Look up a single student by their university student_id."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(StudentInfo).where(StudentInfo.student_id == student_id).limit(1)
        )
        return result.scalar_one_or_none()


async def bulk_insert_students(rows: list[dict]) -> int:
    """Insert StudentInfo records from a list of dicts. Returns count inserted."""
    if not rows:
        return 0
    async with SessionLocal() as session:
        async with session.begin():
            session.add_all([StudentInfo(**r) for r in rows])
    return len(rows)


async def get_stats() -> Dict[str, Any]:
    async with SessionLocal() as session:
        total_messages = (
            await session.execute(select(func.count(Log.id)))
        ).scalar_one()
        total_users = (
            await session.execute(select(func.count(func.distinct(User.user_id))))
        ).scalar_one()
        row = (
            await session.execute(
                select(Log.predicted_intent, func.count(Log.id).label("c"))
                .group_by(Log.predicted_intent)
                .order_by(func.count(Log.id).desc())
                .limit(1)
            )
        ).first()
        most_common_intent = row[0] if row else "None"
        return {
            "total_messages": total_messages,
            "total_users": total_users,
            "most_common_intent": most_common_intent,
        }
