from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_plugin_finder.collection.graph import CollectionGraph, build_collection_graph
from content_plugin_finder.discover import discover_scan_roots
from content_plugin_finder.impact.content_index import (
    ContentIndex,
    build_content_index,
    roots_using_plugins,
)
from content_plugin_finder.models import PluginKind


@dataclass
class ImpactReport:
    collection: str
    changed_files: list[str] = field(default_factory=list)
    affected_plugins: list[str] = field(default_factory=list)
    molecule_scenarios: list[str] = field(default_factory=list)
    integration_targets: list[str] = field(default_factory=list)
    # root relpath -> reasons (changed file and/or plugins)
    reasons: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "changed_files": self.changed_files,
            "affected_plugins": self.affected_plugins,
            "molecule_scenarios": self.molecule_scenarios,
            "integration_targets": self.integration_targets,
            "reasons": self.reasons,
        }


def _normalize_rel(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _root_containing_file(
    changed: str,
    roots_by_rel: dict[str, str],
    parent: Path,
) -> str | None:
    """If changed file lives under a scan root, return that root's relpath."""
    changed_path = (parent / changed).resolve()
    # Longest matching root wins
    best: str | None = None
    best_len = -1
    for abs_root, rel_root in roots_by_rel.items():
        try:
            changed_path.relative_to(Path(abs_root))
        except ValueError:
            continue
        if len(rel_root) > best_len:
            best = rel_root
            best_len = len(rel_root)
    return best


def compute_impact(
    *,
    collection_root: Path,
    changed_files: list[str],
    parent: Path | None = None,
    depth: int = 4,
    graph: CollectionGraph | None = None,
    content_index: ContentIndex | None = None,
) -> ImpactReport:
    """Map changed files to molecule scenarios and integration targets."""
    collection_root = collection_root.resolve()
    parent = (parent or collection_root).resolve()
    graph = graph or build_collection_graph(collection_root)
    content_index = content_index or build_content_index(
        parent,
        collection=graph.collection,
        depth=depth,
        kinds=list(PluginKind),
    )

    # Ensure roots map exists even if index was built separately
    if not content_index.roots:
        for root in discover_scan_roots(parent, depth):
            rel = str(root.resolve().relative_to(parent))
            content_index.roots[str(root.resolve())] = rel

    reasons: dict[str, list[str]] = defaultdict(list)
    affected_plugins: set[str] = set()
    normalized_files = [_normalize_rel(f) for f in changed_files]

    for changed in normalized_files:
        # 1) Direct edit inside a scenario / target
        direct_root = _root_containing_file(changed, content_index.roots, parent)
        if direct_root is not None:
            reasons[direct_root].append(f"changed:{changed}")

        # 2) Collection Python / plugin file → plugins → content roots
        plugins = graph.plugins_for_file(changed)
        for plugin in plugins:
            affected_plugins.add(plugin)
        if plugins:
            for root, matched in roots_using_plugins(content_index, set(plugins)).items():
                for plugin in matched:
                    reason = f"plugin:{plugin} via {changed}"
                    if reason not in reasons[root]:
                        reasons[root].append(reason)

    molecule: list[str] = []
    integration: list[str] = []
    for root in sorted(reasons):
        kind = content_index.root_kinds.get(root, "unknown")
        if kind == "molecule":
            molecule.append(root)
        elif kind == "integration":
            integration.append(root)
        else:
            # Prefer path heuristics
            if "molecule" in root.split("/"):
                molecule.append(root)
            elif "integration" in root.split("/") and "targets" in root.split("/"):
                integration.append(root)

    return ImpactReport(
        collection=graph.collection,
        changed_files=normalized_files,
        affected_plugins=sorted(affected_plugins),
        molecule_scenarios=molecule,
        integration_targets=integration,
        reasons={k: v for k, v in sorted(reasons.items())},
    )


def format_impact_text(
    report: ImpactReport,
    *,
    emit: str = "all",
    names_only: bool = False,
) -> str:
    """Emit selected roots as text lines.

    Default: ``molecule\\t<path>`` / ``integration\\t<path>``.
    With ``names_only`` and a single ``emit`` kind, print leaf names only.
    With ``names_only`` and ``emit=all``, print ``kind\\t<leaf>``.
    """
    items: list[tuple[str, str]] = []
    if emit in {"all", "molecule"}:
        items.extend(("molecule", path) for path in report.molecule_scenarios)
    if emit in {"all", "integration"}:
        items.extend(("integration", path) for path in report.integration_targets)

    lines: list[str] = []
    bare_names = names_only and emit in {"molecule", "integration"}
    for kind, path in items:
        value = Path(path).name if names_only else path
        lines.append(value if bare_names else f"{kind}\t{value}")
    return "\n".join(lines) + ("\n" if lines else "")


def format_impact_json(report: ImpactReport) -> str:
    import json

    return json.dumps(report.to_dict(), indent=2) + "\n"
