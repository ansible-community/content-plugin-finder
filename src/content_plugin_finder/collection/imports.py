from __future__ import annotations

import ast
from pathlib import Path


def list_imports(module_source: str, *, module_qualname: str = "") -> list[str]:
    """Return import targets referenced by a Python module.

    Resolves relative imports when ``module_qualname`` is provided
    (e.g. ``ansible_collections.ns.name.plugins.action.application``).
    """
    try:
        tree = ast.parse(module_source)
    except SyntaxError:
        return []

    package_parts = module_qualname.split(".") if module_qualname else []
    # Drop the module leaf for relative import base (package path)
    package = package_parts[:-1] if package_parts else []

    found: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        found.append(name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and package:
                # level=1 -> current package; level=2 -> parent, etc.
                base = package[: max(0, len(package) - (node.level - 1))]
                if node.module:
                    full = ".".join([*base, *node.module.split(".")])
                else:
                    full = ".".join(base)
            elif node.module:
                full = node.module
            else:
                continue
            add(full)
            for alias in node.names:
                if alias.name == "*":
                    continue
                add(f"{full}.{alias.name}")
    return found


def file_to_qualname(path: Path, collection_root: Path, collection_fqcn: str) -> str:
    """Map a collection-relative .py path to ansible_collections.* qualname."""
    rel = path.resolve().relative_to(collection_root.resolve())
    if rel.suffix != ".py":
        raise ValueError(f"not a python file: {path}")
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["ansible_collections", *collection_fqcn.split("."), *parts])
