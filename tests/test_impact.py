from pathlib import Path

from content_plugin_finder.cli import main
from content_plugin_finder.collection.graph import build_collection_graph
from content_plugin_finder.impact.content_index import build_content_index
from content_plugin_finder.impact.engine import compute_impact, format_impact_text
from content_plugin_finder.impact.git import read_changed_files_from_lines


def _mini_collection(tmp_path: Path) -> Path:
    (tmp_path / "galaxy.yml").write_text(
        "namespace: acme\nname: widgets\n",
        encoding="utf-8",
    )
    modules = tmp_path / "plugins" / "modules"
    action = tmp_path / "plugins" / "action"
    utils = tmp_path / "plugins" / "module_utils"
    for d in (modules, action, utils):
        d.mkdir(parents=True)

    (utils / "core.py").write_text("X = 1\n", encoding="utf-8")
    (action / "base.py").write_text(
        "from ansible_collections.acme.widgets.plugins.module_utils.core import X\n"
        "class Base:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (action / "thing.py").write_text(
        "from ansible_collections.acme.widgets.plugins.action.base import Base\n"
        "class ActionModule(Base):\n"
        '    MODULE_NAME = "thing"\n',
        encoding="utf-8",
    )
    (modules / "thing.py").write_text(
        'DOCUMENTATION = """\nmodule: thing\n"""\n',
        encoding="utf-8",
    )

    # molecule scenario using the module
    mol = tmp_path / "extensions" / "molecule" / "thing_mock"
    mol.mkdir(parents=True)
    (mol / "molecule.yml").write_text("driver:\n  name: default\n", encoding="utf-8")
    (mol / "converge.yml").write_text(
        "- hosts: localhost\n  tasks:\n    - acme.widgets.thing:\n        name: x\n",
        encoding="utf-8",
    )

    # integration target using the module
    target = tmp_path / "tests" / "integration" / "targets" / "thing_test"
    target.mkdir(parents=True)
    (target / "aliases").write_text("thing\n", encoding="utf-8")
    (target / "tasks").mkdir()
    (target / "tasks" / "main.yml").write_text(
        "- acme.widgets.thing:\n    name: y\n",
        encoding="utf-8",
    )

    # unrelated scenario
    other = tmp_path / "extensions" / "molecule" / "other"
    other.mkdir(parents=True)
    (other / "molecule.yml").write_text("driver:\n  name: default\n", encoding="utf-8")
    (other / "converge.yml").write_text(
        "- hosts: localhost\n  tasks:\n    - ansible.builtin.debug:\n        msg: hi\n",
        encoding="utf-8",
    )
    return tmp_path


def test_read_changed_files_from_lines():
    assert read_changed_files_from_lines(
        ["plugins/action/thing.py\n", "# comment\n", "\n", "  foo.yml  \n"]
    ) == ["plugins/action/thing.py", "foo.yml"]


def test_impact_plugin_change_selects_scenarios(tmp_path: Path):
    root = _mini_collection(tmp_path)
    graph = build_collection_graph(root)
    index = build_content_index(root, collection=graph.collection, depth=4)

    report = compute_impact(
        collection_root=root,
        changed_files=["plugins/module_utils/core.py"],
        parent=root,
        graph=graph,
        content_index=index,
    )
    assert "acme.widgets.thing" in report.affected_plugins
    assert "extensions/molecule/thing_mock" in report.molecule_scenarios
    assert "tests/integration/targets/thing_test" in report.integration_targets
    assert "extensions/molecule/other" not in report.molecule_scenarios


def test_impact_direct_scenario_edit(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=["extensions/molecule/thing_mock/converge.yml"],
        parent=root,
    )
    assert report.molecule_scenarios == ["extensions/molecule/thing_mock"]
    assert report.integration_targets == []


def test_impact_direct_integration_edit(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=["tests/integration/targets/thing_test/tasks/main.yml"],
        parent=root,
    )
    assert report.integration_targets == ["tests/integration/targets/thing_test"]
    assert report.molecule_scenarios == []


def test_impact_path_prefix_when_depth_too_low(tmp_path: Path):
    """Scenario/target edits still map via path layout when discovery finds nothing."""
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=[
            "extensions/molecule/thing_mock/converge.yml",
            "tests/integration/targets/thing_test/tasks/main.yml",
        ],
        parent=root,
        depth=0,
    )
    assert report.molecule_scenarios == ["extensions/molecule/thing_mock"]
    assert report.integration_targets == ["tests/integration/targets/thing_test"]


def test_impact_shared_molecule_selects_all_scenarios(tmp_path: Path):
    root = _mini_collection(tmp_path)
    (root / "extensions" / "molecule" / "requirements.yml").write_text(
        "collections: []\n",
        encoding="utf-8",
    )
    report = compute_impact(
        collection_root=root,
        changed_files=["extensions/molecule/requirements.yml"],
        parent=root,
    )
    assert set(report.molecule_scenarios) == {
        "extensions/molecule/thing_mock",
        "extensions/molecule/other",
    }
    assert report.integration_targets == []
    for root_rel in report.molecule_scenarios:
        assert any(r.endswith("(shared molecule)") for r in report.reasons[root_rel])


def test_impact_scenario_local_still_only_that_scenario(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=["extensions/molecule/other/converge.yml"],
        parent=root,
    )
    assert report.molecule_scenarios == ["extensions/molecule/other"]
    assert "extensions/molecule/thing_mock" not in report.molecule_scenarios


def test_format_impact_text_names_only(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=["plugins/action/thing.py"],
        parent=root,
    )
    text = format_impact_text(report, emit="molecule", names_only=True)
    assert text.strip() == "thing_mock"


def test_cli_impact_from_stdin(tmp_path: Path, monkeypatch, capsys):
    root = _mini_collection(tmp_path)
    monkeypatch.setattr(
        "sys.stdin",
        type("S", (), {"readlines": lambda self: ["plugins/action/base.py\n"]})(),
    )
    assert (
        main(
            [
                "--impact",
                str(root),
                "--parent",
                str(root),
                "--from-stdin",
                "--emit",
                "all",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "molecule\textensions/molecule/thing_mock" in out
    assert "integration\ttests/integration/targets/thing_test" in out
