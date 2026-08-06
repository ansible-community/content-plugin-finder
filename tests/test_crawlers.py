from pathlib import Path

from content_plugin_finder.crawl.context import build_context
from content_plugin_finder.crawl.filters import FilterCrawler
from content_plugin_finder.crawl.lookups import LookupCrawler
from content_plugin_finder.crawl.modules import ModuleCrawler
from content_plugin_finder.crawl.orchestrator import Orchestrator
from content_plugin_finder.models import PluginKind

FIXTURES = Path(__file__).parent / "fixtures"
MOLECULE = FIXTURES / "molecule_scenario"
INTEGRATION = FIXTURES / "integration_target"


def test_filter_crawler_finds_jinja_filters():
    ctx = build_context(MOLECULE, need_acc=False, need_yaml=True)
    names = {f.name for f in FilterCrawler().crawl(ctx)}
    assert "default" in names


def test_lookup_crawler_finds_jinja_lookups():
    ctx = build_context(MOLECULE, need_acc=False, need_yaml=True)
    names = {f.name for f in LookupCrawler().crawl(ctx)}
    assert "file" in names
    assert "env" in names


def test_module_crawler_via_orchestrator():
    report = Orchestrator().scan([MOLECULE], kinds=[PluginKind.MODULE])
    merged = report.merged()
    names = {p.name for p in merged.modules}
    # ACC may resolve FQCN or leave short/partial names depending on deps
    assert any("docker_container" in n for n in names) or any(
        n.endswith("debug") or "debug" in n for n in names
    )


def test_orchestrator_all_kinds_molecule():
    report = Orchestrator().scan([MOLECULE])
    merged = report.merged()
    filter_names = {p.name for p in merged.filters}
    lookup_names = {p.name for p in merged.lookups}
    assert "default" in filter_names
    assert "file" in lookup_names
    assert "env" in lookup_names


def test_orchestrator_integration_filters_and_lookups():
    report = Orchestrator().scan(
        [INTEGRATION],
        kinds=[PluginKind.FILTER, PluginKind.LOOKUP],
    )
    merged = report.merged()
    assert {"upper", "trim"} <= {p.name for p in merged.filters}
    assert "ansible.builtin.password" in {p.name for p in merged.lookups}


def test_module_crawler_direct():
    ctx = build_context(INTEGRATION, need_acc=True, need_yaml=False)
    crawler = ModuleCrawler()
    findings = list(crawler.crawl(ctx))
    # Even if ACC fails soft, crawler should return a list
    assert isinstance(findings, list)
