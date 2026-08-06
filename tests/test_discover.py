from pathlib import Path

from content_plugin_finder.discover import discover_scan_roots, relative_depth

FIXTURES = Path(__file__).parent / "fixtures"


def test_relative_depth():
    parent = FIXTURES.resolve()
    child = (FIXTURES / "molecule_scenario").resolve()
    assert relative_depth(parent, parent) == 0
    assert relative_depth(child, parent) == 1


def test_discover_fixtures_as_parent(tmp_path: Path):
    # Build a mini collection-like tree
    mol = tmp_path / "extensions" / "molecule" / "default"
    mol.mkdir(parents=True)
    (mol / "molecule.yml").write_text("driver:\n  name: default\n")
    target = tmp_path / "tests" / "integration" / "targets" / "foo_test"
    target.mkdir(parents=True)
    (target / "aliases").write_text("foo\n")

    roots = discover_scan_roots(tmp_path, depth=4)
    assert mol.resolve() in roots
    assert target.resolve() in roots


def test_discover_respects_depth(tmp_path: Path):
    mol = tmp_path / "extensions" / "molecule" / "default"
    mol.mkdir(parents=True)
    (mol / "molecule.yml").write_text("x: 1\n")
    target = tmp_path / "tests" / "integration" / "targets" / "foo_test"
    target.mkdir(parents=True)

    shallow = discover_scan_roots(tmp_path, depth=2)
    assert mol.resolve() not in shallow
    assert target.resolve() not in shallow

    mid = discover_scan_roots(tmp_path, depth=3)
    assert mol.resolve() in mid
    assert target.resolve() not in mid

    deep = discover_scan_roots(tmp_path, depth=4)
    assert mol.resolve() in deep
    assert target.resolve() in deep
