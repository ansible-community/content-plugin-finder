from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_DIRS = (
    "modules",
    "module_utils",
    "plugin_utils",
    "action",
    "filter",
    "lookup",
    "inventory",
    "connection",
    "callback",
    "doc_fragments",
)

_DOC_NAME_RE = re.compile(
    r'^DOCUMENTATION\s*=\s*(?:r?"""|r?\'\'\')(.*?)(?:"""|\'\'\')',
    re.DOTALL | re.MULTILINE,
)
_YAML_NAME_RE = re.compile(r"(?m)^\s*name:\s*[\"']?([A-Za-z0-9_.]+)[\"']?\s*$")
_YAML_MODULE_RE = re.compile(r"(?m)^\s*module:\s*[\"']?([A-Za-z0-9_.]+)[\"']?\s*$")


@dataclass
class PluginFile:
    kind: str  # modules, action, filter, ...
    path: Path
    relpath: str
    stem: str
    qualname: str
    # Public plugin names exposed by this file (FQCN short name or full filter names)
    names: list[str] = field(default_factory=list)
    # For action plugins: corresponding module stem
    module_stem: str | None = None
    imports: list[str] = field(default_factory=list)


def iter_plugin_python_files(collection_root: Path) -> list[tuple[str, Path]]:
    plugins_root = collection_root / "plugins"
    if not plugins_root.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for kind in PLUGIN_DIRS:
        kind_dir = plugins_root / kind
        if not kind_dir.is_dir():
            continue
        for path in sorted(kind_dir.rglob("*.py")):
            if path.name == "__init__.py" and path.parent == kind_dir and kind != "module_utils":
                # Keep nested package __init__ under module_utils/plugin_utils; skip empty top-level ones later
                pass
            found.append((kind, path))
    return found


def extract_documentation_name(source: str, *, prefer_module_key: bool = False) -> str | None:
    match = _DOC_NAME_RE.search(source)
    if not match:
        return None
    doc = match.group(1)
    if prefer_module_key:
        mod = _YAML_MODULE_RE.search(doc)
        if mod:
            return mod.group(1)
    name = _YAML_NAME_RE.search(doc)
    return name.group(1) if name else None


def has_toplevel_action_module(source: str) -> bool:
    """True when the file defines a top-level ``ActionModule`` class."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(isinstance(node, ast.ClassDef) and node.name == "ActionModule" for node in tree.body)


def extract_action_module_name(source: str, stem: str, module_stems: set[str]) -> str | None:
    """Resolve the module name an action plugin serves.

    Returns ``None`` when the file is not a real action plugin (no top-level
    ``ActionModule``), e.g. shared bases like ``base_action.py``.

    Preference order:
    1. ``MODULE_NAME`` class attribute on ``ActionModule``
    2. DOCUMENTATION ``module:`` / ``name:``
    3. Matching ``plugins/modules/<stem>.py``
    4. Action file stem
    """
    if not has_toplevel_action_module(source):
        return None

    mod_from_ast = _ast_action_module_name(source)
    if mod_from_ast:
        return mod_from_ast

    doc_name = extract_documentation_name(source, prefer_module_key=True)
    if doc_name:
        return doc_name.split(".")[-1]

    if stem in module_stems:
        return stem
    return stem


def _ast_action_module_name(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "ActionModule":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "MODULE_NAME":
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        return stmt.value.value
    return None


def extract_filter_names(source: str, stem: str) -> list[str]:
    """Return filter plugin names declared in ``FilterModule.filters()``."""
    names = _ast_filter_names(source)
    if names:
        return names
    # Fallback: file stem is a single filter name (common simple case)
    if stem != "__init__":
        return [stem]
    return []


def _ast_filter_names(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "FilterModule":
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != "filters":
                continue
            assigned: dict[str, ast.AST] = {}
            for stmt in item.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if isinstance(target, ast.Name):
                        assigned[target.id] = stmt.value
                elif isinstance(stmt, ast.Return) and stmt.value is not None:
                    value = stmt.value
                    if isinstance(value, ast.Name) and value.id in assigned:
                        value = assigned[value.id]
                    names.extend(_dict_string_keys(value))
    return names


def _dict_string_keys(node: ast.AST) -> list[str]:
    keys: list[str] = []
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.append(key.value)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        for kw in node.keywords:
            if kw.arg:
                keys.append(kw.arg)
    return keys


def extract_lookup_name(source: str, stem: str) -> str:
    doc_name = extract_documentation_name(source)
    if doc_name:
        return doc_name.split(".")[-1]
    return stem


def extract_module_name(source: str, stem: str) -> str:
    doc_name = extract_documentation_name(source, prefer_module_key=True)
    if doc_name:
        return doc_name.split(".")[-1]
    return stem
