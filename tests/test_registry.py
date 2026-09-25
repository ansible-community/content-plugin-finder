from content_plugin_finder.crawl.registry import default_registry
from content_plugin_finder.models import PluginKind


def test_default_registry_has_four_crawlers():
    registry = default_registry()
    names = {c.name for c in registry.all()}
    assert names == {"module", "filter", "lookup", "role"}


def test_for_kinds_selects_subset():
    registry = default_registry()
    selected = registry.for_kinds({PluginKind.FILTER})
    assert [c.name for c in selected] == ["filter"]
    assert [c.name for c in registry.for_kinds({PluginKind.ROLE})] == ["role"]


def test_list_info():
    info = default_registry().list_info()
    assert {i["name"] for i in info} == {"module", "filter", "lookup", "role"}
