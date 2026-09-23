import json
from pathlib import Path

from content_plugin_finder.cli import build_parser, main
from content_plugin_finder.crawl.orchestrator import default_workers

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
    payload = json.loads(out)
    assert payload["all"]["filters"][0]["name"] == "default"


def test_cli_json_routes_scanner_warnings_to_stderr(monkeypatch, capfd):
    import ansible_content_capture.logger as scanner_logger
    from ansible_content_capture.scanner import AnsibleScanner

    scanner_logger.set_logger_channel("ansible-scan")
    scanner_logger.set_log_level("warning")

    def run_with_warning(self, target_dir="", raw_yaml="", **kwargs):
        scanner_logger.warning("metadata not found: amazon.aws")
        return type("ScanResult", (), {"trees": []})()

    monkeypatch.setattr(AnsibleScanner, "run", run_with_warning)

    assert main([str(MOLECULE), "--format", "json", "--types", "module"]) == 0
    captured = capfd.readouterr()

    json.loads(captured.out)
    assert "WARNING" not in captured.out
    assert captured.err == "WARNING:ansible-scan:metadata not found: amazon.aws\n"


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


def test_cli_rejects_invalid_workers():
    try:
        main([str(MOLECULE), "--workers", "0"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected argparse to reject --workers 0")


def test_cli_uses_parallel_default():
    assert build_parser().parse_args([str(MOLECULE)]).workers == default_workers()
