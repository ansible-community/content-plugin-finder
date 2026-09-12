import json
from pathlib import Path

import pytest

from content_plugin_finder.cli import main
from content_plugin_finder.collection.graph import build_collection_graph
from content_plugin_finder.impact.content_index import build_content_index, roots_using_roles
from content_plugin_finder.impact.engine import (
    compute_impact,
    format_impact_json,
    format_impact_text,
)
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
    role = tmp_path / "roles" / "agent" / "tasks"
    role.mkdir(parents=True)
    (role / "main.yml").write_text(
        "- ansible.builtin.debug:\n    msg: agent\n",
        encoding="utf-8",
    )
    (mol / "converge.yml").write_text(
        "- hosts: localhost\n"
        "  roles:\n"
        "    - role: acme.widgets.agent\n"
        "  tasks:\n"
        "    - acme.widgets.thing:\n"
        "        name: x\n",
        encoding="utf-8",
    )

    # integration target using the module
    target = tmp_path / "tests" / "integration" / "targets" / "thing_test"
    target.mkdir(parents=True)
    (target / "aliases").write_text("thing\n", encoding="utf-8")
    (target / "tasks").mkdir()
    (target / "tasks" / "main.yml").write_text(
        "- acme.widgets.thing:\n    name: y\n"
        "- ansible.builtin.import_tasks: role.yml\n",
        encoding="utf-8",
    )
    (target / "tasks" / "role.yml").write_text(
        "- ansible.builtin.include_role:\n"
        "    name: agent\n",
        encoding="utf-8",
    )

    # unrelated scenario
    other = tmp_path / "extensions" / "molecule" / "other"
    other.mkdir(parents=True)
    (other / "molecule.yml").write_text("driver:\n  name: default\n", encoding="utf-8")
    (other / "converge.yml").write_text(
        "- hosts: localhost\n"
        "  roles:\n"
        "    - external.vendor.agent\n"
        "  tasks:\n"
        "    - ansible.builtin.debug:\n"
        "        msg: hi\n",
        encoding="utf-8",
    )
    return tmp_path


def test_read_changed_files_from_lines():
    assert read_changed_files_from_lines(
        ["plugins/action/thing.py\n", "# comment\n", "\n", "  foo.yml  \n"]
    ) == ["plugins/action/thing.py", "foo.yml"]


def test_content_index_maps_roles_to_molecule_and_integration_roots(tmp_path: Path):
    root = _mini_collection(tmp_path)
    graph = build_collection_graph(root)
    index = build_content_index(root, collection=graph.collection, depth=4)

    assert index.role_to_roots["acme.widgets.agent"] == [
        "extensions/molecule/thing_mock",
        "tests/integration/targets/thing_test",
    ]
    assert index.role_to_roots["external.vendor.agent"] == [
        "extensions/molecule/other",
    ]
    assert roots_using_roles(index, {"acme.widgets.agent"}) == {
        "extensions/molecule/thing_mock": ["acme.widgets.agent"],
        "tests/integration/targets/thing_test": ["acme.widgets.agent"],
    }


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
        assert any(
            r.endswith("(shared molecule)") for r in report.reasons[root_rel]
        )


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


@pytest.mark.parametrize(
    "changed",
    [
        "roles/agent/defaults/main.yml",
        "roles/agent/handlers/main.yml",
        "roles/agent/meta/main.yml",
        "roles/agent/tasks/main.yml",
        "roles/agent/tasks/agent_present.yml",
        "roles/agent/templates/service.j2",
        "roles/agent/vars/main.yml",
        "roles/agent/files/archive.tar.gz",
    ],
)
def test_role_file_selects_molecule_and_integration_roots(
    tmp_path: Path,
    changed: str,
):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=[changed],
        parent=root,
    )

    assert report.affected_roles == ["acme.widgets.agent"]
    assert report.affected_plugins == []
    assert report.molecule_scenarios == ["extensions/molecule/thing_mock"]
    assert report.integration_targets == ["tests/integration/targets/thing_test"]
    expected_reason = f"role:acme.widgets.agent via {changed}"
    assert report.reasons == {
        "extensions/molecule/thing_mock": [expected_reason],
        "tests/integration/targets/thing_test": [expected_reason],
    }


def test_role_change_selects_all_rfe_molecule_scenarios(tmp_path: Path):
    (tmp_path / "galaxy.yml").write_text(
        "namespace: community\nname: beszel\n",
        encoding="utf-8",
    )
    for name in ("agent_airgap", "agent_default", "agent_token"):
        scenario = tmp_path / "extensions" / "molecule" / name
        scenario.mkdir(parents=True)
        (scenario / "molecule.yml").write_text(
            "driver:\n  name: default\n",
            encoding="utf-8",
        )
        (scenario / "converge.yml").write_text(
            "- hosts: localhost\n"
            "  roles:\n"
            "    - role: community.beszel.agent\n",
            encoding="utf-8",
        )

    report = compute_impact(
        collection_root=tmp_path,
        changed_files=["roles/agent/tasks/agent_present.yml"],
        parent=tmp_path / "extensions",
    )

    assert report.affected_roles == ["community.beszel.agent"]
    assert report.molecule_scenarios == [
        "molecule/agent_airgap",
        "molecule/agent_default",
        "molecule/agent_token",
    ]


def test_affected_roles_are_sorted(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=[
            "roles/zebra/tasks/main.yml",
            "roles/alpha/tasks/main.yml",
        ],
        parent=root,
    )

    assert report.affected_roles == [
        "acme.widgets.alpha",
        "acme.widgets.zebra",
    ]


def test_impact_json_always_contains_affected_roles(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=["plugins/module_utils/core.py"],
        parent=root,
    )

    payload = json.loads(format_impact_json(report))
    assert list(payload).index("affected_roles") == list(payload).index("affected_plugins") + 1
    assert payload["affected_roles"] == []


def test_unreferenced_local_role_has_no_affected_roots(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=["roles/unrelated/tasks/main.yml"],
        parent=root,
    )

    assert report.affected_roles == ["acme.widgets.unrelated"]
    assert report.molecule_scenarios == []
    assert report.integration_targets == []
    assert report.reasons == {}


@pytest.mark.parametrize(
    "changed",
    [
        "roles/agent",
        "roles//tasks/main.yml",
        "other/roles/agent/tasks/main.yml",
    ],
)
def test_malformed_role_path_does_not_affect_roles(
    tmp_path: Path,
    changed: str,
):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=[changed],
        parent=root,
    )

    assert report.affected_roles == []
    assert report.molecule_scenarios == []
    assert report.integration_targets == []
    assert report.reasons == {}


def test_mixed_plugin_and_role_changes_are_deduplicated(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=[
            "plugins/module_utils/core.py",
            "roles/agent/tasks/main.yml",
        ],
        parent=root,
    )

    assert report.affected_plugins == ["acme.widgets.thing"]
    assert report.affected_roles == ["acme.widgets.agent"]
    assert report.molecule_scenarios == ["extensions/molecule/thing_mock"]
    assert report.integration_targets == ["tests/integration/targets/thing_test"]
    for reasons in report.reasons.values():
        assert len(reasons) == 2
        assert len(reasons) == len(set(reasons))
