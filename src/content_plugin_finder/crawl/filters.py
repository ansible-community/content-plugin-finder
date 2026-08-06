from __future__ import annotations

import re
from collections.abc import Iterable

from content_plugin_finder.crawl.base import Crawler
from content_plugin_finder.crawl.context import CrawlContext
from content_plugin_finder.models import Finding, PluginKind

# Jinja filter after a pipe: | filter_name or | ns.col.filter
_FILTER_RE = re.compile(
    r"\|\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2})\b"
)

# Common Jinja tests / keywords that appear after | in non-filter contexts — keep MVP
# permissive; only skip a small denylist of obvious non-filters.
_SKIP = frozenset(
    {
        "else",
        "endif",
        "endfor",
        "endraw",
        "endmacro",
        "not",
        "is",
    }
)


class FilterCrawler(Crawler):
    name = "filter"
    kinds = frozenset({PluginKind.FILTER})

    def crawl(self, ctx: CrawlContext) -> Iterable[Finding]:
        findings: list[Finding] = []
        seen: set[tuple[str, str, int | None]] = set()

        for scalar in ctx.yaml_scalars:
            if "|" not in scalar.text:
                continue
            for match in _FILTER_RE.finditer(scalar.text):
                name = match.group(1)
                if name in _SKIP:
                    continue
                path = str(scalar.path)
                dedupe = (name, path, scalar.line)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                findings.append(
                    Finding(
                        kind=PluginKind.FILTER,
                        name=name,
                        path=path,
                        line=scalar.line,
                        source="jinja-scalar",
                    )
                )
        return findings
