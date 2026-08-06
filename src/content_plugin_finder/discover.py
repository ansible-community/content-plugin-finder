from __future__ import annotations

from pathlib import Path


def relative_depth(path: Path, parent: Path) -> int:
    """Number of path parts under parent (parent itself is depth 0)."""
    resolved_parent = parent.resolve()
    resolved_path = path.resolve()
    rel = resolved_path.relative_to(resolved_parent)
    if rel == Path("."):
        return 0
    return len(rel.parts)


def discover_scan_roots(parent: Path, depth: int) -> list[Path]:
    """Discover molecule scenarios and ansible-test targets under parent.

    A directory is selected when its relative depth is ``<= depth`` and it is either:
    - a Molecule scenario (contains ``molecule.yml``), or
    - an ansible-test integration target
      (``tests/integration/targets/<name>/``).
    """
    if depth < 0:
        raise ValueError("depth must be >= 0")

    parent = parent.resolve()
    if not parent.is_dir():
        raise FileNotFoundError(f"not a directory: {parent}")

    roots: set[Path] = set()

    for molecule_yml in parent.rglob("molecule.yml"):
        scenario = molecule_yml.parent
        try:
            if relative_depth(scenario, parent) <= depth:
                roots.add(scenario)
        except ValueError:
            continue

    # Classic layout: <parent>/tests/integration/targets/<target>
    for targets_dir in _find_integration_targets_dirs(parent, depth):
        for target in targets_dir.iterdir():
            if not target.is_dir():
                continue
            try:
                if relative_depth(target, parent) <= depth:
                    roots.add(target.resolve())
            except ValueError:
                continue

    return sorted(roots)


def _find_integration_targets_dirs(parent: Path, depth: int) -> list[Path]:
    """Find ``tests/integration/targets`` dirs whose path depth is within limit."""
    found: list[Path] = []
    marker = Path("tests") / "integration" / "targets"
    # Direct child layout first
    direct = parent / marker
    if direct.is_dir() and relative_depth(direct, parent) <= depth:
        found.append(direct.resolve())

    # Nested (e.g. collections inside a repo) — still respect depth on the targets dir
    for candidate in parent.rglob("targets"):
        if not candidate.is_dir():
            continue
        try:
            rel = candidate.relative_to(parent)
        except ValueError:
            continue
        if rel.parts[-3:] != ("tests", "integration", "targets"):
            continue
        if len(rel.parts) > depth:
            continue
        resolved = candidate.resolve()
        if resolved not in found:
            found.append(resolved)
    return found
