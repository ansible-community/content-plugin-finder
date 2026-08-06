from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class PluginKind(StrEnum):
    MODULE = "module"
    FILTER = "filter"
    LOOKUP = "lookup"


@dataclass(frozen=True, slots=True)
class Finding:
    kind: PluginKind
    name: str
    path: str = ""
    line: int | None = None
    source: str = ""

    def key(self) -> tuple[str, str]:
        return (self.kind.value, self.name)


@dataclass
class Location:
    path: str
    line: int | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"path": self.path, "source": self.source}
        if self.line is not None:
            data["line"] = self.line
        return data


@dataclass
class NamedPlugin:
    name: str
    locations: list[Location] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "locations": [loc.to_dict() for loc in self.locations],
        }


@dataclass
class DirectoryReport:
    directory: Path
    modules: list[NamedPlugin] = field(default_factory=list)
    filters: list[NamedPlugin] = field(default_factory=list)
    lookups: list[NamedPlugin] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modules": [p.to_dict() for p in self.modules],
            "filters": [p.to_dict() for p in self.filters],
            "lookups": [p.to_dict() for p in self.lookups],
        }


@dataclass
class ScanReport:
    directories: dict[str, DirectoryReport] = field(default_factory=dict)

    def merged(self) -> DirectoryReport:
        by_kind: dict[PluginKind, dict[str, NamedPlugin]] = {
            PluginKind.MODULE: {},
            PluginKind.FILTER: {},
            PluginKind.LOOKUP: {},
        }
        for dir_report in self.directories.values():
            for kind, plugins in (
                (PluginKind.MODULE, dir_report.modules),
                (PluginKind.FILTER, dir_report.filters),
                (PluginKind.LOOKUP, dir_report.lookups),
            ):
                for plugin in plugins:
                    existing = by_kind[kind].get(plugin.name)
                    if existing is None:
                        by_kind[kind][plugin.name] = NamedPlugin(
                            name=plugin.name,
                            locations=list(plugin.locations),
                        )
                    else:
                        existing.locations.extend(plugin.locations)

        def sorted_plugins(d: dict[str, NamedPlugin]) -> list[NamedPlugin]:
            return [by_kind_entry for _, by_kind_entry in sorted(d.items())]

        return DirectoryReport(
            directory=Path("."),
            modules=sorted_plugins(by_kind[PluginKind.MODULE]),
            filters=sorted_plugins(by_kind[PluginKind.FILTER]),
            lookups=sorted_plugins(by_kind[PluginKind.LOOKUP]),
        )

    def to_dict(self, by_directory: bool = False) -> dict[str, Any]:
        merged = self.merged()
        data: dict[str, Any] = {
            "all": {
                "modules": [p.to_dict() for p in merged.modules],
                "filters": [p.to_dict() for p in merged.filters],
                "lookups": [p.to_dict() for p in merged.lookups],
            }
        }
        if by_directory:
            data["directories"] = {
                path: report.to_dict() for path, report in sorted(self.directories.items())
            }
        return data
