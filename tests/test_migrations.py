from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from launch_os_v11.platform.config import get_settings


def test_initial_migration_upgrade_and_downgrade_clean_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("LAUNCH_OS_DATABASE_URL", database_url)
    get_settings.cache_clear()

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    try:
        tables_after_upgrade = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "businesses" in tables_after_upgrade
    assert "business_snapshots" in tables_after_upgrade
    assert "outbox_events" in tables_after_upgrade
    assert "approvals" in tables_after_upgrade
    assert "checkpoint_definitions" in tables_after_upgrade
    assert "connector_observations" in tables_after_upgrade
    assert "metric_versions" in tables_after_upgrade
    assert "learning_details" in tables_after_upgrade
    assert "decision_learning_links" in tables_after_upgrade

    command.downgrade(config, "base")

    engine = create_engine(database_url, future=True)
    try:
        tables_after_downgrade = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    get_settings.cache_clear()

    assert "businesses" not in tables_after_downgrade
    assert "outbox_events" not in tables_after_downgrade
    assert "metric_versions" not in tables_after_downgrade
