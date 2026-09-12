from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import yaml

_YAML_SUFFIXES = frozenset({".yml", ".yaml"})
_ROLE_ACTIONS = frozenset(
    {
        "include_role",
        "import_role",
        "ansible.builtin.include_role",
        "ansible.builtin.import_role",
    }
)
_IMPORT_ACTIONS = frozenset(
    {
        "import_playbook",
        "import_tasks",
        "include_tasks",
        "ansible.builtin.import_playbook",
        "ansible.builtin.import_tasks",
        "ansible.builtin.include_tasks",
    }
)


def _option(value: Any, key: str) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate.strip() or None
    return None


def _normalize_role(name: str, collection: str) -> str | None:
    name = name.strip()
    if not name or "{{" in name or "{%" in name:
        return None
    if "." not in name:
        return f"{collection}.{name}"
    return name


def _walk_node(node: Any, collection: str) -> tuple[set[str], set[str]]:
    roles: set[str] = set()
    imports: set[str] = set()

    if isinstance(node, list):
        for item in node:
            item_roles, item_imports = _walk_node(item, collection)
            roles.update(item_roles)
            imports.update(item_imports)
        return roles, imports

    if not isinstance(node, dict):
        return roles, imports

    if "hosts" in node and isinstance(node.get("roles"), list):
        for item in node["roles"]:
            raw = item if isinstance(item, str) else _option(item, "role")
            if isinstance(raw, str):
                normalized = _normalize_role(raw, collection)
                if normalized:
                    roles.add(normalized)

    for action in _ROLE_ACTIONS:
        if action not in node:
            continue
        raw = _option(node[action], "name")
        if raw:
            normalized = _normalize_role(raw, collection)
            if normalized:
                roles.add(normalized)

    for action in _IMPORT_ACTIONS:
        if action not in node:
            continue
        raw = _option(node[action], "file")
        if raw and "{{" not in raw and "{%" not in raw:
            imports.add(raw)

    for value in node.values():
        child_roles, child_imports = _walk_node(value, collection)
        roles.update(child_roles)
        imports.update(child_imports)
    return roles, imports


def _is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def roles_used_by_root(
    root: Path,
    *,
    parent: Path,
    collection: str,
) -> set[str]:
    root = root.resolve()
    parent = parent.resolve()
    initial = sorted(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _YAML_SUFFIXES
    )
    queue: deque[Path] = deque(initial)
    visited: set[Path] = set()
    roles: set[str] = set()

    while queue:
        path = queue.popleft().resolve()
        if path in visited or not _is_below(path, parent):
            continue
        visited.add(path)
        try:
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError):
            continue

        for document in documents:
            found_roles, imports = _walk_node(document, collection)
            roles.update(found_roles)
            for imported in sorted(imports):
                imported_path = (path.parent / imported).resolve()
                if (
                    imported_path.is_file()
                    and imported_path.suffix.lower() in _YAML_SUFFIXES
                    and _is_below(imported_path, parent)
                ):
                    queue.append(imported_path)

    return roles
