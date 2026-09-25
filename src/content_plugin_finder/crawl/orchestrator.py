from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
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


def default_workers() -> int:
    """Return a conservative default for CPU-bound directory scans."""
    return min(4, os.cpu_count() or 1)


def _scan_directory(
    raw: Path | str,
    kind_set: frozenset[PluginKind],
    registry: CrawlerRegistry,
) -> tuple[str, DirectoryReport]:
    root = Path(raw)
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")

    crawlers = registry.for_kinds(kind_set)
    need_acc = any(c.name in {"module", "lookup"} for c in crawlers)
    need_yaml = any(c.name in {"filter", "lookup"} for c in crawlers)
    ctx = build_context(root, need_acc=need_acc, need_yaml=need_yaml)

    findings: list[Finding] = []
    for crawler in crawlers:
        crawler.prepare(ctx)
        findings.extend(crawler.crawl(ctx))

    findings = [finding for finding in findings if finding.kind in kind_set]
    directory_report = Orchestrator._to_directory_report(root, findings)
    return str(root.resolve()), directory_report


class Orchestrator:
    def __init__(self, registry: CrawlerRegistry | None = None) -> None:
        self.registry = registry or default_registry()

    def scan(
        self,
        directories: Sequence[Path | str],
        kinds: Iterable[PluginKind] | None = None,
        workers: int = 1,
    ) -> ScanReport:
        kind_set = frozenset(kinds) if kinds is not None else frozenset(PluginKind)
        if workers < 1:
            raise ValueError("workers must be >= 1")

        inputs = list(directories)
        report = ScanReport()
        if workers == 1 or len(inputs) <= 1:
            results = (_scan_directory(raw, kind_set, self.registry) for raw in inputs)
            for path, directory_report in results:
                report.directories[path] = directory_report
            return report

        with ProcessPoolExecutor(max_workers=min(workers, len(inputs))) as executor:
            # executor.map preserves input order, keeping reports deterministic.
            results = executor.map(
                _scan_directory,
                inputs,
                [kind_set] * len(inputs),
                [self.registry] * len(inputs),
            )
            for path, directory_report in results:
                report.directories[path] = directory_report
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
