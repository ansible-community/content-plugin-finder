from __future__ import annotations

from collections.abc import Iterable

from content_plugin_finder.crawl.base import Crawler
from content_plugin_finder.crawl.context import CrawlContext
from content_plugin_finder.models import Finding, PluginKind

# Task actions that are control/include flow, not plugins we want as "modules"
_SKIP_MODULES = frozenset(
    {
        "include",
        "include_tasks",
        "include_role",
        "import_tasks",
        "import_role",
        "import_playbook",
        "ansible.builtin.include",
        "ansible.builtin.include_tasks",
        "ansible.builtin.include_role",
        "ansible.builtin.import_tasks",
        "ansible.builtin.import_role",
        "ansible.builtin.import_playbook",
        "block",
        "rescue",
        "always",
        "meta",
        "ansible.builtin.meta",
    }
)


class ModuleCrawler(Crawler):
    name = "module"
    kinds = frozenset({PluginKind.MODULE})

    def crawl(self, ctx: CrawlContext) -> Iterable[Finding]:
        if ctx.acc_result is None:
            return []

        findings: list[Finding] = []
        seen: set[tuple[str, str, int | None]] = set()

        for tree in getattr(ctx.acc_result, "trees", []) or []:
            for call in getattr(tree, "items", []) or []:
                obj = getattr(call, "spec", None)
                if obj is None:
                    continue
                obj_type = getattr(obj, "type", "")
                name = ""
                path = getattr(obj, "filepath", "") or ""
                line: int | None = None

                if obj_type == "task":
                    name = getattr(obj, "resolved_name", "") or getattr(obj, "module", "") or ""
                    lines = getattr(obj, "line_num_in_file", None) or []
                    if lines:
                        line = int(lines[0])
                elif obj_type == "module":
                    name = getattr(obj, "fqcn", "") or getattr(obj, "name", "") or ""
                else:
                    continue

                if not name or name in _SKIP_MODULES:
                    continue

                dedupe = (name, path, line)
                if dedupe in seen:
                    continue
                seen.add(dedupe)

                findings.append(
                    Finding(
                        kind=PluginKind.MODULE,
                        name=name,
                        path=path,
                        line=line,
                        source="acc-tree",
                    )
                )
        return findings
