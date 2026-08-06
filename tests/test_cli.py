from pathlib import Path

from content_plugin_finder.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
MOLECULE = FIXTURES / "molecule_scenario"


def test_list_crawlers(capsys):
    assert main(["--list-crawlers"]) == 0
    out = capsys.readouterr().out
    assert "module" in out
    assert "filter" in out
    assert "lookup" in out


def test_cli_text_scan(capsys):
    assert main([str(MOLECULE), "--types", "filter,lookup"]) == 0
    out = capsys.readouterr().out
    assert "filter: default" in out
    assert "lookup: file" in out


def test_cli_json_scan(capsys):
    assert main([str(MOLECULE), "--format", "json", "--types", "filter"]) == 0
    out = capsys.readouterr().out
    assert '"filters"' in out
    assert "default" in out


def test_cli_missing_dir():
    assert main(["/no/such/directory/content_plugin_finder"]) == 2


def test_cli_list_roots(tmp_path: Path, capsys):
    mol = tmp_path / "extensions" / "molecule" / "default"
    mol.mkdir(parents=True)
    (mol / "molecule.yml").write_text("driver:\n  name: default\n")
    assert main(["--parent", str(tmp_path), "--depth", "3", "--list-roots"]) == 0
    out = capsys.readouterr().out
    assert "molecule/default" in out


def test_cli_parent_scan(tmp_path: Path, capsys):
    mol = tmp_path / "extensions" / "molecule" / "default"
    mol.mkdir(parents=True)
    (mol / "molecule.yml").write_text("driver:\n  name: default\n")
    (mol / "converge.yml").write_text(
        "- hosts: localhost\n"
        "  tasks:\n"
        "    - debug:\n"
        "        msg: \"{{ 'x' | default('y') }}\"\n"
    )
    assert (
        main(
            [
                "--parent",
                str(tmp_path),
                "--depth",
                "3",
                "--types",
                "filter",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "filter: default" in out
