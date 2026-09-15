from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_plugin_finder.collection.galaxy import read_collection_fqcn
from content_plugin_finder.collection.imports import file_to_qualname, list_imports
from content_plugin_finder.collection.plugins import (
    PluginFile,
    extract_action_module_name,
    extract_filter_names,
    extract_lookup_name,
    extract_module_name,
    iter_plugin_python_files,
)


@dataclass
class PluginResolution:
    """Full collection-local dependency closure for one public plugin name."""

    name: str
    kind: str  # primary kind: module/action/filter/lookup/...
    entry_files: list[str] = field(default_factory=list)
    entry_qualnames: list[str] = field(default_factory=list)
    # Transitive collection-local modules this plugin depends on
    depends_on_qualnames: list[str] = field(default_factory=list)
    depends_on_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "entry_files": self.entry_files,
            "entry_qualnames": self.entry_qualnames,
            "depends_on_qualnames": self.depends_on_qualnames,
            "depends_on_files": self.depends_on_files,
        }


@dataclass
class CollectionGraph:
    collection: str
    root: Path
    plugins: list[PluginFile] = field(default_factory=list)
    # qualname -> direct imports
    imports: dict[str, list[str]] = field(default_factory=dict)
    # imported qualname -> list of importer relpaths (direct)
    imported_by: dict[str, list[str]] = field(default_factory=dict)
    # public plugin name -> providing files
    name_index: dict[str, list[str]] = field(default_factory=dict)
    # public plugin name -> full transitive resolution
    resolved: dict[str, PluginResolution] = field(default_factory=dict)
    # collection-relative file -> plugin FQCNs that depend on it (entry or transitive)
    file_to_plugins: dict[str, list[str]] = field(default_factory=dict)

    def resolve(self, name: str) -> PluginResolution | None:
        """Look up by FQCN, or short name aliased to ``{collection}.{short}``."""
        if name in self.resolved:
            return self.resolved[name]
        if "." not in name:
            return self.resolved.get(f"{self.collection}.{name}")
        return None

    def plugins_for_file(self, relpath: str) -> list[str]:
        """Return FQCNs impacted when ``relpath`` (collection-relative) changes."""
        normalized = relpath.replace("\\", "/").lstrip("./")
        return list(self.file_to_plugins.get(normalized, []))

    def to_dict(self) -> dict[str, Any]:
        by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for plugin in self.plugins:
            entry: dict[str, Any] = {
                "path": plugin.relpath,
                "stem": plugin.stem,
                "qualname": plugin.qualname,
                "names": plugin.names,
                "imports": plugin.imports,
            }
            if plugin.module_stem is not None:
                entry["module"] = plugin.module_stem
            by_kind[plugin.kind].append(entry)

        return {
            "collection": self.collection,
            "root": str(self.root),
            "resolved": {
                name: res.to_dict() for name, res in sorted(self.resolved.items())
            },
            "file_to_plugins": self.file_to_plugins,
            "plugins": dict(by_kind),
            "imports": self.imports,
            "imported_by": self.imported_by,
            "name_index": self.name_index,
        }


def _known_module_qualnames(plugins: list[PluginFile]) -> dict[str, str]:
    """Map module qualname -> relpath (packages and modules)."""
    return {p.qualname: p.relpath for p in plugins}


def _match_import_to_known(
    imported: str, known: dict[str, str], prefix: str
) -> str | None:
    """Strip attribute suffixes until we hit a known module qualname."""
    if not imported.startswith((prefix, "ansible_collections.")):
        return None
    parts = imported.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in known:
            return candidate
        if not candidate.startswith(prefix):
            break
        parts.pop()
    return None


def _transitive_deps(
    entry_qualnames: list[str],
    imports_map: dict[str, list[str]],
    known: dict[str, str],
    prefix: str,
) -> tuple[list[str], list[str]]:
    """Return sorted (depends_on_qualnames, depends_on_files) excluding entries themselves."""
    entry_set = set(entry_qualnames)
    seen: set[str] = set()
    queue: deque[str] = deque(entry_qualnames)

    while queue:
        current = queue.popleft()
        for imported in imports_map.get(current, []):
            matched = _match_import_to_known(imported, known, prefix)
            if matched is None or matched in entry_set or matched in seen:
                continue
            seen.add(matched)
            queue.append(matched)

    qualnames = sorted(seen)
    files = sorted({known[q] for q in qualnames if q in known})
    return qualnames, files


def _primary_kind(files: list[PluginFile]) -> str:
    order = [
        "modules",
        "action",
        "filter",
        "lookup",
        "inventory",
        "connection",
        "callback",
    ]
    kinds = {p.kind for p in files}
    for kind in order:
        if kind in kinds:
            return kind
    return files[0].kind if files else "unknown"


def _fqcn(collection: str, short: str) -> str:
    """Build ``namespace.name.plugin`` from galaxy collection FQCN + short plugin name."""
    if short.startswith(f"{collection}."):
        return short
    return f"{collection}.{short}"


def _build_resolved(
    collection: str,
    plugins: list[PluginFile],
    imports_map: dict[str, list[str]],
) -> dict[str, PluginResolution]:
    """Build resolutions keyed only by FQCN (``{collection}.{plugin}``)."""
    prefix = f"ansible_collections.{collection}."
    known = _known_module_qualnames(plugins)

    by_fqcn: dict[str, list[PluginFile]] = defaultdict(list)
    for plugin in plugins:
        for name in plugin.names:
            by_fqcn[name].append(plugin)

    resolved: dict[str, PluginResolution] = {}
    for fqcn, files in by_fqcn.items():
        uniq: dict[str, PluginFile] = {p.qualname: p for p in files}
        file_list = list(uniq.values())
        entry_qualnames = sorted(uniq.keys())
        entry_files = sorted(p.relpath for p in file_list)
        deps_q, deps_f = _transitive_deps(entry_qualnames, imports_map, known, prefix)
        resolved[fqcn] = PluginResolution(
            name=fqcn,
            kind=_primary_kind(file_list),
            entry_files=entry_files,
            entry_qualnames=entry_qualnames,
            depends_on_qualnames=deps_q,
            depends_on_files=deps_f,
        )
    return resolved


def _build_file_to_plugins(
    resolved: dict[str, PluginResolution],
) -> dict[str, list[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for fqcn, res in resolved.items():
        for path in (*res.entry_files, *res.depends_on_files):
            mapping[path.replace("\\", "/")].add(fqcn)
    return {path: sorted(plugins) for path, plugins in sorted(mapping.items())}


def build_collection_graph(collection_root: Path) -> CollectionGraph:
    root = collection_root.resolve()
    collection = read_collection_fqcn(root)
    prefix = f"ansible_collections.{collection}."

    # First pass: module stems for action↔module mapping
    module_stems: set[str] = set()
    for kind, path in iter_plugin_python_files(root):
        if kind == "modules" and path.name != "__init__.py":
            module_stems.add(path.stem)

    plugins: list[PluginFile] = []
    imports_map: dict[str, list[str]] = {}
    imported_by: dict[str, list[str]] = defaultdict(list)
    name_index: dict[str, list[str]] = defaultdict(list)

    for kind, path in iter_plugin_python_files(root):
        if (
            path.name == "__init__.py"
            and kind
            in {
                "action",
                "filter",
                "lookup",
                "modules",
                "connection",
                "inventory",
                "callback",
            }
            and path.parent == root / "plugins" / kind
        ):
            continue

        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue

        try:
            qualname = file_to_qualname(path, root, collection)
        except ValueError:
            continue

        relpath = str(path.relative_to(root))
        stem = path.stem if path.name != "__init__.py" else path.parent.name
        names: list[str] = []
        module_stem: str | None = None

        if kind == "modules":
            short = extract_module_name(source, path.stem)
            names = [_fqcn(collection, short)]
        elif kind == "action":
            module_stem = extract_action_module_name(source, path.stem, module_stems)
            if module_stem:
                names = [_fqcn(collection, module_stem)]
            else:
                names = []
        elif kind == "filter":
            names = [
                _fqcn(collection, short)
                for short in extract_filter_names(source, path.stem)
            ]
        elif kind == "lookup":
            short = extract_lookup_name(source, path.stem)
            names = [_fqcn(collection, short)]
        elif kind in {"inventory", "connection", "callback"}:
            names = [_fqcn(collection, path.stem)]

        file_imports = list_imports(source, module_qualname=qualname)
        plugins.append(
            PluginFile(
                kind=kind,
                path=path,
                relpath=relpath,
                stem=stem,
                qualname=qualname,
                names=names,
                module_stem=module_stem,
                imports=file_imports,
            )
        )
        imports_map[qualname] = file_imports
        for imported in file_imports:
            if imported.startswith((prefix, "ansible_collections.")):
                imported_by[imported].append(relpath)
        for name in names:
            name_index[name].append(relpath)

    for key, value in imported_by.items():
        imported_by[key] = sorted(set(value))
    for key, value in name_index.items():
        name_index[key] = sorted(set(value))

    resolved = _build_resolved(collection, plugins, imports_map)
    file_to_plugins = _build_file_to_plugins(resolved)

    return CollectionGraph(
        collection=collection,
        root=root,
        plugins=plugins,
        imports=imports_map,
        imported_by=dict(sorted(imported_by.items())),
        name_index=dict(sorted(name_index.items())),
        resolved=resolved,
        file_to_plugins=file_to_plugins,
    )


def format_collection_graph_text(
    graph: CollectionGraph, *, plugin: str | None = None
) -> str:
    lines: list[str] = [f"collection: {graph.collection}", f"root: {graph.root}", ""]

    if plugin:
        res = graph.resolve(plugin)
        if res is None:
            return f"collection: {graph.collection}\nerror: unknown plugin {plugin!r}\n"
        return _format_resolution(res) + "\n"

    lines.append(
        f"[resolved plugins]  (FQCN = {graph.collection}.<plugin> from galaxy.yml)"
    )
    for name, res in sorted(graph.resolved.items()):
        lines.append(f"  {name}  ({res.kind})")
        lines.append(f"    entry: {', '.join(res.entry_files)}")
        if res.depends_on_files:
            lines.append(f"    depends_on ({len(res.depends_on_files)} files):")
            for dep in res.depends_on_files:
                lines.append(f"      - {dep}")
        else:
            lines.append("    depends_on: (none in-collection)")
    lines.append("")
    return "\n".join(lines)


def _format_resolution(res: PluginResolution) -> str:
    lines = [
        f"plugin: {res.name}",
        f"kind: {res.kind}",
        "entry_files:",
    ]
    lines.extend(f"  - {p}" for p in res.entry_files)
    lines.append("depends_on_files:")
    if res.depends_on_files:
        lines.extend(f"  - {p}" for p in res.depends_on_files)
    else:
        lines.append("  (none)")
    lines.append("depends_on_qualnames:")
    if res.depends_on_qualnames:
        lines.extend(f"  - {q}" for q in res.depends_on_qualnames)
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def format_resolution_json(res: PluginResolution) -> str:
    import json

    return json.dumps(res.to_dict(), indent=2) + "\n"
