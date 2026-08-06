from pathlib import Path

from content_plugin_finder.cli import main
from content_plugin_finder.collection.graph import build_collection_graph
from content_plugin_finder.collection.plugins import (
    extract_action_module_name,
    extract_filter_names,
)


def test_extract_action_module_name_from_constant():
    source = '''
class ActionModule:
    MODULE_NAME = "application"
'''
    assert extract_action_module_name(source, "application", {"application"}) == "application"


def test_extract_action_skips_base_helper():
    source = '''
class BaseResourceActionPlugin:
    pass
'''
    assert extract_action_module_name(source, "base_action", {"application"}) is None


def test_extract_filter_names_from_dict_return():
    source = '''
class FilterModule:
    def filters(self):
        return {
            "to_nice": to_nice,
            "my_other": my_other,
        }
'''
    assert extract_filter_names(source, "stuff") == ["to_nice", "my_other"]


def test_extract_filter_names_assigned_then_returned():
    source = '''
class FilterModule:
    def filters(self):
        filters = dict(alpha=alpha, beta=beta)
        return filters
'''
    assert extract_filter_names(source, "stuff") == ["alpha", "beta"]


def test_build_mini_collection_graph(tmp_path: Path):
    (tmp_path / "galaxy.yml").write_text(
        "namespace: acme\nname: widgets\n",
        encoding="utf-8",
    )
    modules = tmp_path / "plugins" / "modules"
    action = tmp_path / "plugins" / "action"
    filters = tmp_path / "plugins" / "filter"
    utils = tmp_path / "plugins" / "module_utils"
    for d in (modules, action, filters, utils):
        d.mkdir(parents=True)

    (modules / "thing.py").write_text(
        'DOCUMENTATION = """\nmodule: thing\n"""\n'
        "from ansible_collections.acme.widgets.plugins.module_utils import core\n",
        encoding="utf-8",
    )
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
    (filters / "text_filters.py").write_text(
        "class FilterModule:\n"
        "    def filters(self):\n"
        '        return {"shout": shout, "whisper": whisper}\n',
        encoding="utf-8",
    )
    (utils / "core.py").write_text("X = 1\n", encoding="utf-8")

    graph = build_collection_graph(tmp_path)
    assert graph.collection == "acme.widgets"

    action_plugin = next(p for p in graph.plugins if p.kind == "action" and p.stem == "thing")
    assert action_plugin.module_stem == "thing"
    assert action_plugin.names == ["acme.widgets.thing"]

    filter_plugin = next(p for p in graph.plugins if p.kind == "filter")
    assert "acme.widgets.shout" in filter_plugin.names
    assert "acme.widgets.whisper" in filter_plugin.names

    assert graph.name_index["acme.widgets.shout"] == ["plugins/filter/text_filters.py"]

    # Per-plugin full resolution (transitive), keyed by FQCN from galaxy.yml
    res = graph.resolve("thing")  # short alias ok
    assert res is not None
    assert res.name == "acme.widgets.thing"
    assert "thing" not in graph.resolved  # only FQCN keys
    assert "acme.widgets.thing" in graph.resolved
    assert set(res.entry_files) == {
        "plugins/action/thing.py",
        "plugins/modules/thing.py",
    }
    assert "plugins/action/base.py" in res.depends_on_files
    assert "plugins/module_utils/core.py" in res.depends_on_files


def test_cli_collection_graph_json(tmp_path: Path, capsys):
    (tmp_path / "galaxy.yml").write_text("namespace: acme\nname: widgets\n", encoding="utf-8")
    mod = tmp_path / "plugins" / "modules"
    mod.mkdir(parents=True)
    (mod / "thing.py").write_text("DOCUMENTATION = '''\nmodule: thing\n'''\n", encoding="utf-8")
    assert main(["--collection-graph", str(tmp_path), "--format", "json"]) == 0
    out = capsys.readouterr().out
    assert '"collection": "acme.widgets"' in out
    assert "thing" in out
