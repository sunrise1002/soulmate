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
