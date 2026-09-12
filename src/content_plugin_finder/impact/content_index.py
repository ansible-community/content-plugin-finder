from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from content_plugin_finder.crawl.orchestrator import Orchestrator
from content_plugin_finder.discover import discover_scan_roots
from content_plugin_finder.impact.role_index import roles_used_by_root
from content_plugin_finder.models import PluginKind


@dataclass
class ContentIndex:
    """Maps plugin FQCNs/names to scan roots that use them."""

    collection: str
    # plugin name (as found in content, plus FQCN when normalizable) -> root relpaths
    plugin_to_roots: dict[str, list[str]] = field(default_factory=dict)
    # root relpath -> root kind
    root_kinds: dict[str, str] = field(default_factory=dict)
    # role FQCN -> root relpaths
    role_to_roots: dict[str, list[str]] = field(default_factory=dict)
    # absolute root path -> relpath
    roots: dict[str, str] = field(default_factory=dict)


def classify_root(root: Path, parent: Path) -> str:
    """Return ``molecule`` or ``integration`` for a scan root."""
    if (root / "molecule.yml").is_file():
        return "molecule"
    try:
        rel = root.resolve().relative_to(parent.resolve())
    except ValueError:
        rel_parts = root.parts
    else:
        rel_parts = rel.parts
    if len(rel_parts) >= 4 and rel_parts[-4:-1] == ("tests", "integration", "targets"):
        return "integration"
    if (root / "aliases").is_file() or (root / "tasks").is_dir():
        return "integration"
    return "unknown"


def build_content_index(
    parent: Path,
    *,
    collection: str,
    depth: int = 4,
    kinds: list[PluginKind] | None = None,
) -> ContentIndex:
    parent = parent.resolve()
    scan_roots = discover_scan_roots(parent, depth)
    report = Orchestrator().scan(scan_roots, kinds=kinds or list(PluginKind))

    index = ContentIndex(collection=collection)
    plugin_to_roots: dict[str, set[str]] = defaultdict(set)
    role_to_roots: dict[str, set[str]] = defaultdict(set)

    for abs_dir, dir_report in report.directories.items():
        root = Path(abs_dir)
        try:
            rel = str(root.resolve().relative_to(parent))
        except ValueError:
            rel = str(root)
        index.roots[str(root.resolve())] = rel
        kind = classify_root(root, parent)
        index.root_kinds[rel] = kind
        if kind in {"molecule", "integration"}:
            for role in roles_used_by_root(
                root,
                parent=parent,
                collection=collection,
            ):
                role_to_roots[role].add(rel)

        names: list[str] = []
        for group in (dir_report.modules, dir_report.filters, dir_report.lookups):
            names.extend(p.name for p in group)

        for name in names:
            plugin_to_roots[name].add(rel)
            # Also index FQCN form when content used a short name from this collection
            if "." not in name:
                plugin_to_roots[f"{collection}.{name}"].add(rel)
            elif name.startswith(collection + "."):
                short = name[len(collection) + 1 :]
                plugin_to_roots[short].add(rel)

    index.plugin_to_roots = {k: sorted(v) for k, v in sorted(plugin_to_roots.items())}
    index.role_to_roots = {
        role: sorted(roots) for role, roots in sorted(role_to_roots.items())
    }
    return index


def roots_using_plugins(index: ContentIndex, plugins: set[str]) -> dict[str, list[str]]:
    """Return root_relpath -> list of matching plugin names."""
    hits: dict[str, list[str]] = defaultdict(list)
    for plugin in plugins:
        for root in index.plugin_to_roots.get(plugin, []):
            hits[root].append(plugin)
        # try FQCN / short variants
        if "." not in plugin:
            fqcn = f"{index.collection}.{plugin}"
            for root in index.plugin_to_roots.get(fqcn, []):
                if plugin not in hits[root]:
                    hits[root].append(plugin)
        elif plugin.startswith(index.collection + "."):
            short = plugin[len(index.collection) + 1 :]
            for root in index.plugin_to_roots.get(short, []):
                if plugin not in hits[root]:
                    hits[root].append(plugin)
    return {k: sorted(set(v)) for k, v in sorted(hits.items())}


def roots_using_roles(index: ContentIndex, roles: set[str]) -> dict[str, list[str]]:
    """Return root relpath to matching normalized role FQCNs."""
    hits: dict[str, set[str]] = defaultdict(set)
    for role in roles:
        for root in index.role_to_roots.get(role, []):
            hits[root].add(role)
    return {root: sorted(found) for root, found in sorted(hits.items())}
