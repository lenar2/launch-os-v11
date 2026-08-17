from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_phase4_production_workflow_has_no_connector_or_execution_imports() -> None:
    source = _source("src/launch_os_v11/application/production_workflow.py")
    assert "launch_os_v11.connectors" not in source
    assert "launch_os_v11.execution" not in source
    assert "Telegram" not in source or "TELEGRAM_POST_COPY" in source


def test_generic_worker_remains_production_role_agnostic() -> None:
    source = _source("src/launch_os_v11/runtime/worker.py")
    assert "content_director" not in source
    assert "telegram_writer" not in source
    assert "asset_controller" not in source


def test_phase4_does_not_add_provider_imports_outside_adapters() -> None:
    for relative in (
        "src/launch_os_v11/application/production_workflow.py",
        "src/launch_os_v11/application/workflow_dispatcher.py",
        "src/launch_os_v11/production/context.py",
    ):
        source = _source(relative)
        assert "from openai" not in source
        assert "import openai" not in source
