from __future__ import annotations

import re
from collections.abc import Iterable

from content_plugin_finder.crawl.base import Crawler
from content_plugin_finder.crawl.context import CrawlContext
from content_plugin_finder.models import Finding, PluginKind

_LOOKUP_ACTIONS = frozenset(
    {
        "lookup",
        "query",
        "ansible.builtin.lookup",
        "ansible.builtin.query",
    }
)

# Jinja: lookup('file', ...) / query("env", ...)
_JINJA_LOOKUP_RE = re.compile(
    r"""\b(?:lookup|query)\s*\(\s*['"]([A-Za-z0-9_.]+)['"]""",
    re.IGNORECASE,
)


def _lookup_name_from_module_options(module_options: object) -> str | None:
    if isinstance(module_options, str):
        # e.g. lookup: file
        name = module_options.strip().split()[0] if module_options.strip() else ""
        return name or None
    if isinstance(module_options, dict):
        for key in ("_raw_params", "terms"):
            val = module_options.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().split()[0]
            if isinstance(val, list) and val and isinstance(val[0], str):
                return val[0]
        # First positional-ish string value
        for val in module_options.values():
            if isinstance(val, str) and val.strip() and not val.startswith("{{"):
                return val.strip().split()[0]
    return None


class LookupCrawler(Crawler):
    name = "lookup"
    kinds = frozenset({PluginKind.LOOKUP})

    def crawl(self, ctx: CrawlContext) -> Iterable[Finding]:
        findings: list[Finding] = []
        seen: set[tuple[str, str, int | None, str]] = set()

        findings.extend(self._from_acc(ctx, seen))
        findings.extend(self._from_jinja(ctx, seen))
        return findings

    def _from_acc(
        self,
        ctx: CrawlContext,
        seen: set[tuple[str, str, int | None, str]],
    ) -> list[Finding]:
        if ctx.acc_result is None:
            return []

        out: list[Finding] = []
        for tree in getattr(ctx.acc_result, "trees", []) or []:
            for call in getattr(tree, "items", []) or []:
                obj = getattr(call, "spec", None)
                if obj is None or getattr(obj, "type", "") != "task":
                    continue
                action = getattr(obj, "module", "") or ""
                if action not in _LOOKUP_ACTIONS:
                    continue
                name = _lookup_name_from_module_options(
                    getattr(obj, "module_options", None)
                )
                if not name:
                    continue
                path = getattr(obj, "filepath", "") or ""
                lines = getattr(obj, "line_num_in_file", None) or []
                line = int(lines[0]) if lines else None
                dedupe = (name, path, line, "acc-lookup-task")
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                out.append(
                    Finding(
                        kind=PluginKind.LOOKUP,
                        name=name,
                        path=path,
                        line=line,
                        source="acc-lookup-task",
                    )
                )
        return out

    def _from_jinja(
        self,
        ctx: CrawlContext,
        seen: set[tuple[str, str, int | None, str]],
    ) -> list[Finding]:
        out: list[Finding] = []
        for scalar in ctx.yaml_scalars:
            for match in _JINJA_LOOKUP_RE.finditer(scalar.text):
                name = match.group(1)
                path = str(scalar.path)
                dedupe = (name, path, scalar.line, "jinja-scalar")
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                out.append(
                    Finding(
                        kind=PluginKind.LOOKUP,
                        name=name,
                        path=path,
                        line=scalar.line,
                        source="jinja-scalar",
                    )
                )
        return out
