from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from content_plugin_finder.crawl.context import build_context
from content_plugin_finder.crawl.registry import CrawlerRegistry, default_registry
from content_plugin_finder.models import (
    DirectoryReport,
    Finding,
    Location,
    NamedPlugin,
    PluginKind,
    ScanReport,
)


class Orchestrator:
    def __init__(self, registry: CrawlerRegistry | None = None) -> None:
        self.registry = registry or default_registry()

    def scan(
        self,
        directories: Sequence[Path | str],
        kinds: Iterable[PluginKind] | None = None,
    ) -> ScanReport:
        kind_set = frozenset(kinds) if kinds is not None else frozenset(PluginKind)
        crawlers = self.registry.for_kinds(kind_set)
        need_acc = any(c.name in {"module", "lookup"} for c in crawlers)
        need_yaml = any(c.name in {"filter", "lookup"} for c in crawlers)

        report = ScanReport()
        for raw in directories:
            root = Path(raw)
            if not root.is_dir():
                raise FileNotFoundError(f"not a directory: {root}")

            ctx = build_context(root, need_acc=need_acc, need_yaml=need_yaml)
            findings: list[Finding] = []
            for crawler in crawlers:
                crawler.prepare(ctx)
                findings.extend(crawler.crawl(ctx))

            # Keep only requested kinds (crawler may emit subset)
            findings = [f for f in findings if f.kind in kind_set]
            report.directories[str(root.resolve())] = self._to_directory_report(root, findings)
        return report

    @staticmethod
    def _to_directory_report(root: Path, findings: list[Finding]) -> DirectoryReport:
        buckets: dict[PluginKind, dict[str, NamedPlugin]] = {
            PluginKind.MODULE: {},
            PluginKind.FILTER: {},
            PluginKind.LOOKUP: {},
        }
        for finding in findings:
            bucket = buckets[finding.kind]
            plugin = bucket.get(finding.name)
            if plugin is None:
                plugin = NamedPlugin(name=finding.name)
                bucket[finding.name] = plugin
            plugin.locations.append(
                Location(path=finding.path, line=finding.line, source=finding.source)
            )

        def sorted_named(d: dict[str, NamedPlugin]) -> list[NamedPlugin]:
            return [d[name] for name in sorted(d)]

        return DirectoryReport(
            directory=root.resolve(),
            modules=sorted_named(buckets[PluginKind.MODULE]),
            filters=sorted_named(buckets[PluginKind.FILTER]),
            lookups=sorted_named(buckets[PluginKind.LOOKUP]),
        )
