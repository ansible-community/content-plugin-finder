from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from content_plugin_finder.collection.graph import (
    build_collection_graph,
    format_collection_graph_text,
    format_resolution_json,
)
from content_plugin_finder.crawl.orchestrator import Orchestrator
from content_plugin_finder.crawl.registry import default_registry
from content_plugin_finder.discover import discover_scan_roots
from content_plugin_finder.impact.engine import (
    compute_impact,
    format_impact_json,
    format_impact_text,
)
from content_plugin_finder.impact.git import (
    list_changed_files,
    read_changed_files_from_lines,
)
from content_plugin_finder.models import PluginKind
from content_plugin_finder.report import format_json, format_text


def _parse_kinds(value: str) -> list[PluginKind]:
    kinds: list[PluginKind] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            kinds.append(PluginKind(part))
        except ValueError as exc:
            valid = ", ".join(k.value for k in PluginKind)
            raise argparse.ArgumentTypeError(
                f"unknown plugin type {part!r}; choose from: {valid}"
            ) from exc
    if not kinds:
        raise argparse.ArgumentTypeError("at least one plugin type is required")
    return kinds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="content-plugin-finder",
        description=(
            "Extract Ansible plugins used in Molecule/integration content, "
            "build a collection import graph, or map git changes to tests to run."
        ),
    )
    parser.add_argument(
        "directories",
        nargs="*",
        type=Path,
        help="Directories to scan (molecule scenarios or integration targets)",
    )
    parser.add_argument(
        "--parent",
        type=Path,
        help=(
            "Parent directory to search for Molecule scenarios and "
            "ansible-test integration targets"
        ),
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=4,
        help=(
            "Max relative depth under --parent for discovered roots "
            "(default: 4; e.g. tests/integration/targets/<name>)"
        ),
    )
    parser.add_argument(
        "--list-roots",
        action="store_true",
        help="List discovered scan roots (with --parent) and exit",
    )
    parser.add_argument(
        "--collection-graph",
        type=Path,
        metavar="COLLECTION",
        help=(
            "Build per-plugin transitive dependency resolution for a collection "
            "(action names from MODULE_NAME / modules; filter names from FilterModule.filters())"
        ),
    )
    parser.add_argument(
        "--plugin",
        help=(
            "With --collection-graph, show full resolution for one plugin "
            "(short name or FQCN, e.g. application or ansible.platform.application)"
        ),
    )
    parser.add_argument(
        "--impact",
        type=Path,
        metavar="COLLECTION",
        help=(
            "Map changed files to molecule scenarios / integration targets "
            "for COLLECTION (uses --parent/--depth for content discovery; "
            "defaults parent to COLLECTION)"
        ),
    )
    parser.add_argument(
        "--base",
        help="Git base ref/SHA for --impact (PR target branch or base SHA)",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Git head ref/SHA for --impact (default: HEAD)",
    )
    parser.add_argument(
        "--two-dot",
        action="store_true",
        help="With --impact/--base, use two-dot git diff (base head) instead of base...head",
    )
    parser.add_argument(
        "--from-stdin",
        action="store_true",
        help="With --impact, read changed file paths from stdin (one per line)",
    )
    parser.add_argument(
        "--emit",
        choices=("all", "molecule", "integration"),
        default="all",
        help="With --impact text output, which roots to print (default: all)",
    )
    parser.add_argument(
        "--names-only",
        action="store_true",
        help="With --impact, emit leaf scenario/target names instead of relative paths",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--by-directory",
        action="store_true",
        help="Group results per input directory",
    )
    parser.add_argument(
        "--types",
        type=_parse_kinds,
        default=None,
        help="Comma-separated plugin kinds: module,filter,lookup",
    )
    parser.add_argument(
        "--list-crawlers",
        action="store_true",
        help="List registered crawlers and exit",
    )
    return parser


def _resolve_directories(args: argparse.Namespace) -> list[Path]:
    directories = list(args.directories)
    if args.parent is not None:
        discovered = discover_scan_roots(args.parent, args.depth)
        directories.extend(discovered)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in directories:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _run_collection_graph(collection: Path, fmt: str, plugin: str | None) -> int:
    try:
        graph = build_collection_graph(collection)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if plugin:
        res = graph.resolve(plugin)
        if res is None:
            print(f"error: unknown plugin {plugin!r}", file=sys.stderr)
            return 2
        if fmt == "json":
            sys.stdout.write(format_resolution_json(res))
        else:
            sys.stdout.write(format_collection_graph_text(graph, plugin=plugin))
        return 0
    if fmt == "json":
        sys.stdout.write(json.dumps(graph.to_dict(), indent=2) + "\n")
    else:
        sys.stdout.write(format_collection_graph_text(graph))
    return 0


def _run_impact(args: argparse.Namespace) -> int:
    collection = args.impact.resolve()
    parent = (args.parent or args.impact).resolve()

    try:
        if args.from_stdin:
            changed = read_changed_files_from_lines(sys.stdin.readlines())
        elif args.base:
            changed = list_changed_files(
                collection,
                base=args.base,
                head=args.head,
                merge_base=not args.two_dot,
            )
        else:
            print(
                "error: --impact requires --base REF or --from-stdin",
                file=sys.stderr,
            )
            return 2

        report = compute_impact(
            collection_root=collection,
            changed_files=changed,
            parent=parent,
            depth=args.depth,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        sys.stdout.write(format_impact_json(report))
    else:
        sys.stdout.write(
            format_impact_text(report, emit=args.emit, names_only=args.names_only)
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_crawlers:
        for info in default_registry().list_info():
            print(f"{info['name']}\tkinds={info['kinds']}")
        return 0

    if args.impact is not None:
        return _run_impact(args)

    if args.collection_graph is not None:
        return _run_collection_graph(args.collection_graph, args.format, args.plugin)

    if args.depth < 0:
        parser.error("--depth must be >= 0")

    if args.list_roots:
        if args.parent is None:
            parser.error("--list-roots requires --parent")
        try:
            for root in discover_scan_roots(args.parent, args.depth):
                print(root)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0

    try:
        directories = _resolve_directories(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not directories:
        parser.error(
            "at least one directory is required "
            "(positional and/or --parent), or use --list-crawlers / "
            "--list-roots / --collection-graph / --impact"
        )

    try:
        report = Orchestrator().scan(directories, kinds=args.types)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        sys.stdout.write(format_json(report, by_directory=args.by_directory))
    else:
        sys.stdout.write(format_text(report, by_directory=args.by_directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
