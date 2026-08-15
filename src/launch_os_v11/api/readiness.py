from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError

from launch_os_v11.persistence.session import create_engine_from_settings
from launch_os_v11.platform.config import Settings


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    database: str
    detail: str
    migration_version: str | None = None
    expected_migration_version: str | None = None


class ReadinessChecker(Protocol):
    def __call__(self, settings: Settings) -> ReadinessResult:
        pass


def expected_alembic_head() -> str | None:
    alembic_config = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_config)
    return script.get_current_head()


def check_database_readiness(settings: Settings) -> ReadinessResult:
    expected_head = expected_alembic_head()
    try:
        url = make_url(settings.database_url)
    except Exception as exc:
        return ReadinessResult(
            ready=False,
            database="invalid_url",
            detail=str(exc),
            expected_migration_version=expected_head,
        )

    if url.get_backend_name() != "postgresql":
        return ReadinessResult(
            ready=False,
            database="not_postgresql",
            detail="readiness requires PostgreSQL",
            expected_migration_version=expected_head,
        )

    engine = create_engine_from_settings(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
            migration_version = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        return ReadinessResult(
            ready=False,
            database="unavailable",
            detail=str(exc),
            expected_migration_version=expected_head,
        )
    finally:
        engine.dispose()

    if migration_version != expected_head:
        return ReadinessResult(
            ready=False,
            database="migration_mismatch",
            detail="database migration version is not at head",
            migration_version=str(migration_version) if migration_version is not None else None,
            expected_migration_version=expected_head,
        )

    return ReadinessResult(
        ready=True,
        database="ok",
        detail="ready",
        migration_version=str(migration_version),
        expected_migration_version=expected_head,
    )
