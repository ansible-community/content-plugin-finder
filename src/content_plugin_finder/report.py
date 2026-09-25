from __future__ import annotations

import json

from content_plugin_finder.models import DirectoryReport, NamedPlugin, ScanReport


def _names_lines(kind: str, plugins: list[NamedPlugin]) -> list[str]:
    return [f"{kind}: {plugin.name}" for plugin in plugins]


def format_text(report: ScanReport, *, by_directory: bool = False) -> str:
    lines: list[str] = []
    if by_directory:
        for path, dir_report in sorted(report.directories.items()):
            lines.append(f"# {path}")
            lines.extend(_format_dir(dir_report))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    return "\n".join(_format_dir(report.merged())) + "\n"


def _format_dir(dir_report: DirectoryReport) -> list[str]:
    lines: list[str] = []
    lines.extend(_names_lines("module", dir_report.modules))
    lines.extend(_names_lines("filter", dir_report.filters))
    lines.extend(_names_lines("lookup", dir_report.lookups))
    lines.extend(_names_lines("role", dir_report.roles))
    return lines


def format_json(report: ScanReport, *, by_directory: bool = False) -> str:
    return json.dumps(report.to_dict(by_directory=by_directory), indent=2) + "\n"
