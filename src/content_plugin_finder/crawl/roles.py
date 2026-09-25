from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from content_plugin_finder.crawl.base import Crawler
from content_plugin_finder.crawl.context import CrawlContext
from content_plugin_finder.models import Finding, PluginKind

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


def _literal(value: str | None) -> bool:
    return bool(value) and "{{" not in value and "{%" not in value


def _walk_node(
    node: Any,
    visited: set[int] | None = None,
) -> tuple[set[str], set[str]]:
    roles: set[str] = set()
    imports: set[str] = set()
    if visited is None:
        visited = set()
    if isinstance(node, (list, dict)):
        if id(node) in visited:
            return roles, imports
        visited.add(id(node))

    if isinstance(node, list):
        for item in node:
            child_roles, child_imports = _walk_node(item, visited)
            roles.update(child_roles)
            imports.update(child_imports)
        return roles, imports
    if not isinstance(node, dict):
        return roles, imports

    role_list = node.get("roles")
    if "hosts" in node and isinstance(role_list, list):
        for item in role_list:
            raw = _option(item, "role")
            if _literal(raw):
                roles.add(raw)

    for action in _ROLE_ACTIONS:
        if action not in node:
            continue
        raw = _option(node[action], "name")
        if _literal(raw):
            roles.add(raw)

    for action in _IMPORT_ACTIONS:
        raw = _option(node.get(action), "file")
        if _literal(raw):
            imports.add(raw)

    for value in node.values():
        child_roles, child_imports = _walk_node(value, visited)
        roles.update(child_roles)
        imports.update(child_imports)
    return roles, imports


def _below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


class RoleCrawler(Crawler):
    name = "role"
    kinds = frozenset({PluginKind.ROLE})

    def crawl(self, ctx: CrawlContext) -> Iterable[Finding]:
        root = ctx.root.resolve()
        parent = (ctx.parent or root).resolve()
        queue: deque[Path] = deque(
            sorted(
                path.resolve()
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in _YAML_SUFFIXES
            )
        )
        visited: set[Path] = set()
        findings: list[Finding] = []
        seen: set[tuple[str, str]] = set()

        while queue:
            path = queue.popleft().resolve()
            if path in visited or not _below(path, parent):
                continue
            visited.add(path)
            try:
                documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, yaml.YAMLError):
                continue

            for document in documents:
                if document is None:
                    continue
                roles, imports = _walk_node(document)
                for name in sorted(roles):
                    key = (name, str(path))
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(
                        Finding(
                            kind=PluginKind.ROLE,
                            name=name,
                            path=str(path),
                            source="yaml-role-reference",
                        )
                    )
                for imported in sorted(imports):
                    imported_path = (path.parent / imported).resolve()
                    if (
                        imported_path.is_file()
                        and imported_path.suffix.lower() in _YAML_SUFFIXES
                        and _below(imported_path, parent)
                    ):
                        queue.append(imported_path)
        return findings
