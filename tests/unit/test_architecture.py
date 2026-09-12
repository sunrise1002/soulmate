"""Enforce the kernel's source and package dependency boundary."""

import ast
import sys
import tomllib
from pathlib import Path


def test_kernel_imports_only_itself_and_the_standard_library() -> None:
    root = Path(__file__).resolve().parents[2] / "packages" / "core-python"
    allowed = (sys.stdlib_module_names - {"sqlite3"}) | {"soulmate_core", "__future__"}
    violations = []
    for source in (root / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports = [node.module]
            else:
                continue
            for module in imports:
                if module.split(".")[0] not in allowed:
                    violations.append(f"{source.relative_to(root)}:{node.lineno}: {module}")
    message = "Kernel must remain infrastructure-independent:\n" + "\n".join(violations)
    assert not violations, message


def test_kernel_declares_no_runtime_dependencies() -> None:
    root = Path(__file__).resolve().parents[2]
    with (root / "packages/core-python/pyproject.toml").open("rb") as source:
        metadata = tomllib.load(source)
    assert metadata["project"]["dependencies"] == []
    assert not metadata["project"].get("optional-dependencies")


def test_connector_sdk_is_dependency_free_and_kernel_does_not_import_it() -> None:
    root = Path(__file__).resolve().parents[2]
    sdk = root / "packages/connector-sdk"
    with (sdk / "pyproject.toml").open("rb") as package_file:
        metadata = tomllib.load(package_file)
    assert metadata["project"]["dependencies"] == []

    kernel_imports: list[str] = []
    for source_path in (root / "packages/core-python/src").rglob("*.py"):
        for node in ast.walk(ast.parse(source_path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                kernel_imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                kernel_imports.append(node.module)
    assert not any(name.startswith("soulmate_connector_sdk") for name in kernel_imports)
