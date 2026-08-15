import ast
from pathlib import Path

from launch_os_v11.persistence.models import Base


def test_domain_layer_does_not_depend_on_fastapi_ai_runtime_or_connectors() -> None:
    forbidden_roots = {"fastapi", "launch_os_v11.ai_runtime", "launch_os_v11.connectors"}
    for path in Path("src/launch_os_v11/domain").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported = {node.module}
            else:
                continue
            assert imported.isdisjoint(forbidden_roots), f"{path} imports {imported}"


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
