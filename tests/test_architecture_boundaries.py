import ast
from pathlib import Path

from launch_os_v11.persistence.models import Base


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def _imports_root(imported: set[str], root: str) -> bool:
    return any(module == root or module.startswith(f"{root}.") for module in imported)


def test_domain_layer_does_not_depend_on_fastapi_ai_runtime_or_connectors() -> None:
    forbidden_roots = {
        "fastapi",
        "redis",
        "sqlalchemy",
        "launch_os_v11.ai_runtime",
        "launch_os_v11.connectors",
        "launch_os_v11.persistence",
        "launch_os_v11.runtime",
    }
    for path in Path("src/launch_os_v11/domain").glob("*.py"):
        imported = _imported_modules(path)
        for root in forbidden_roots:
            assert not _imports_root(imported, root), f"{path} imports {root}"


def test_business_scoped_tables_have_tenant_and_business_columns() -> None:
    exempt = {"users", "organizations", "businesses", "alembic_version"}
    for table_name, table in Base.metadata.tables.items():
        if table_name in exempt:
            continue
        assert "organization_id" in table.c
        assert "business_id" in table.c


def test_no_v10_code_path_exists_in_phase_0_or_phase_1_source() -> None:
    source_paths = [path for path in Path("src").rglob("*") if path.is_file()]
    assert all("v10" not in path.as_posix().lower() for path in source_paths)


def test_application_layer_does_not_import_concrete_external_connectors() -> None:
    forbidden_roots = {"launch_os_v11.connectors"}
    for path in Path("src/launch_os_v11/application").glob("*.py"):
        imported = _imported_modules(path)
        for root in forbidden_roots:
            assert not _imports_root(imported, root), f"{path} imports {root}"


def test_persistence_layer_has_no_ai_connector_or_application_workflow_imports() -> None:
    forbidden_roots = {
        "launch_os_v11.ai_runtime",
        "launch_os_v11.connectors",
        "launch_os_v11.application",
        "launch_os_v11.domain.entities",
    }
    for path in Path("src/launch_os_v11/persistence").glob("*.py"):
        imported = _imported_modules(path)
        for root in forbidden_roots:
            assert not _imports_root(imported, root), f"{path} imports {root}"


def test_reserved_packages_do_not_create_direct_agent_to_write_path() -> None:
    reserved_paths = [
        *Path("src/launch_os_v11/ai_runtime").rglob("*.py"),
        *Path("src/launch_os_v11/connectors").rglob("*.py"),
        *Path("src/launch_os_v11/execution").rglob("*.py"),
    ]
    forbidden_terms = {
        "send_message(",
        "publish_to",
        "external_write(",
        "execute_connector(",
        "connector_client",
        "execution_engine",
    }
    for path in reserved_paths:
        text = path.read_text()
        assert not any(term in text for term in forbidden_terms), path


def test_runtime_worker_has_no_ai_connector_or_business_decision_logic() -> None:
    forbidden_roots = {
        "launch_os_v11.ai_runtime",
        "launch_os_v11.connectors",
        "launch_os_v11.production",
        "launch_os_v11.execution",
    }
    forbidden_terms = {
        "telegram",
        "instagram",
        "getcourse",
        "model_router",
        "controller_matrix",
        "selected_action",
    }
    runtime_logic_paths = [
        Path("src/launch_os_v11/runtime/worker.py"),
        Path("src/launch_os_v11/runtime/scheduler.py"),
        Path("src/launch_os_v11/runtime/handlers.py"),
    ]
    for path in runtime_logic_paths:
        imported = _imported_modules(path)
        for root in forbidden_roots:
            assert not _imports_root(imported, root), f"{path} imports {root}"
        text = path.read_text().lower()
        assert not any(term in text for term in forbidden_terms), path


def test_openai_sdk_import_is_confined_to_provider_adapter() -> None:
    allowed_path = Path("src/launch_os_v11/ai_runtime/adapters/openai.py")
    for path in Path("src/launch_os_v11").rglob("*.py"):
        imported = _imported_modules(path)
        if path == allowed_path:
            assert _imports_root(imported, "openai")
        else:
            assert not _imports_root(imported, "openai"), f"{path} imports OpenAI SDK"


def test_ai_runtime_does_not_import_connectors_or_execution() -> None:
    forbidden_roots = {
        "launch_os_v11.connectors",
        "launch_os_v11.execution",
    }
    for path in Path("src/launch_os_v11/ai_runtime").rglob("*.py"):
        imported = _imported_modules(path)
        for root in forbidden_roots:
            assert not _imports_root(imported, root), f"{path} imports {root}"
