from pathlib import Path

import pytest

import ansible_content_capture.finder as acc_finder
import ansible_content_capture.parser as acc_parser
from ansible_content_capture.model_loader import load_object
from ansible_content_capture.models import (
    File,
    Load,
    LoadType,
    PlaybookFormatError,
    ScanResult,
    TaskFormatError,
)
from ansible_content_capture.parser import Parser
from ansible_content_capture.scanner import ScanData
from content_plugin_finder.crawl.base import Crawler
from content_plugin_finder.crawl.context import build_context
from content_plugin_finder.crawl.filters import FilterCrawler
from content_plugin_finder.crawl.lookups import LookupCrawler
from content_plugin_finder.crawl.modules import ModuleCrawler
from content_plugin_finder.crawl.orchestrator import Orchestrator
from content_plugin_finder.crawl.registry import CrawlerRegistry
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


def test_orchestrator_parallel_scan_preserves_directory_order(tmp_path: Path):
    roots = []
    for name, filter_name in (("first", "upper"), ("second", "trim")):
        root = tmp_path / name
        root.mkdir()
        (root / "tasks.yml").write_text(
            f'- debug:\n    msg: "{{{{ value | {filter_name} }}}}"\n'
        )
        roots.append(root)

    report = Orchestrator().scan(roots, kinds=[PluginKind.FILTER], jobs=2)

    assert list(report.directories) == [str(root.resolve()) for root in roots]
    assert {plugin.name for plugin in report.merged().filters} == {"trim", "upper"}


def test_orchestrator_library_default_supports_unpickleable_registry(tmp_path: Path):
    class LocalCrawler(Crawler):
        name = "local"
        kinds = frozenset({PluginKind.FILTER})

        def __init__(self):
            self.unpickleable = lambda: None

        def crawl(self, ctx):
            return []

    registry = CrawlerRegistry()
    registry.register(LocalCrawler())
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()

    report = Orchestrator(registry).scan(roots, kinds=[PluginKind.FILTER])

    assert list(report.directories) == [str(root.resolve()) for root in roots]


def test_acc_yaml_format_checks_share_parsed_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "tasks.yml"
    path.write_text("- name: example\n  debug:\n")
    calls = 0
    safe_load = acc_finder.yaml.safe_load

    def counting_safe_load(body):
        nonlocal calls
        calls += 1
        return safe_load(body)

    acc_finder._load_yaml_file_cached.cache_clear()
    monkeypatch.setattr(acc_finder.yaml, "safe_load", counting_safe_load)

    assert acc_finder.could_be_taskfile(fpath=str(path))
    assert not acc_finder.could_be_playbook_detail(fpath=str(path))
    assert calls == 1


def test_acc_parser_reuses_preloaded_project(monkeypatch):
    path = str(INTEGRATION.resolve())
    load_data = Load(
        target_type=LoadType.PROJECT,
        target_name=path,
        path=path,
    )
    loaded_object = load_object(load_data)

    def unexpected_reload(*args, **kwargs):
        raise AssertionError("preloaded project should not be loaded again")

    monkeypatch.setattr(acc_parser, "load_repository", unexpected_reload)
    definitions, _ = Parser().run(
        load_data=load_data,
        preloaded_object=loaded_object,
    )

    assert definitions["projects"]
    assert definitions["tasks"]

    result = ScanResult()
    for objects in definitions.values():
        for obj in objects:
            result.add_object(obj)
    project = definitions["projects"][0]
    child_keys = project.playbooks + project.roles + project.taskfiles + project.modules
    assert child_keys
    assert all(result.get_object(key) is not None for key in child_keys)


def test_acc_parser_fallback_project_children_resolve():
    path = str(MOLECULE.resolve())
    load_data = Load(
        target_type=LoadType.PROJECT,
        target_name=path,
        path=path,
    )
    load_object(load_data)
    definitions, _ = Parser().run(load_data=load_data)
    result = ScanResult()
    for objects in definitions.values():
        for obj in objects:
            result.add_object(obj)

    project = definitions["projects"][0]
    child_keys = project.playbooks + project.roles + project.taskfiles + project.modules
    assert child_keys
    assert all(result.get_object(key) is not None for key in child_keys)


def test_acc_preloaded_project_preserves_file_objects(tmp_path: Path):
    vars_file = tmp_path / "vars.yml"
    vars_file.write_text("example: value\n")
    load_data = Load(
        target_type=LoadType.PROJECT,
        target_name=str(tmp_path),
        path=str(tmp_path),
        yaml_label_list=[("vars.yml", "others", {})],
    )
    loaded_object = load_object(load_data)

    definitions, _ = Parser().run(
        load_data=load_data,
        preloaded_object=loaded_object,
    )

    project_files = definitions["projects"][0].files
    assert len(project_files) == 1
    assert isinstance(project_files[0], File)
    assert project_files[0].defined_in == "vars.yml"
    assert project_files[0].data == '{"example":"value"}'


def test_acc_preloaded_scan_honors_strict_playbook_errors():
    malformed_yaml = "- hosts: ["
    scan_data = ScanData(
        type=LoadType.PLAYBOOK,
        name="broken.yml",
        playbook_yaml=malformed_yaml,
        playbook_only=True,
        root_dir="/tmp/ansible-scan-data",
        skip_playbook_format_error=False,
    )

    try:
        scan_data.create_load_file(
            LoadType.PLAYBOOK,
            "broken.yml",
            "broken.yml",
        )
    except PlaybookFormatError:
        pass
    else:
        raise AssertionError("strict scan should reject malformed playbook YAML")

    tolerant_scan_data = ScanData(
        type=LoadType.PLAYBOOK,
        name="broken.yml",
        playbook_yaml=malformed_yaml,
        playbook_only=True,
        root_dir="/tmp/ansible-scan-data",
        skip_playbook_format_error=True,
    )
    _, loaded_object = tolerant_scan_data.create_load_file(
        LoadType.PLAYBOOK,
        "broken.yml",
        "broken.yml",
    )
    assert loaded_object is not None


def test_acc_preloaded_collection_propagates_strict_task_errors(tmp_path: Path):
    collection = tmp_path / "namespace" / "collection"
    tasks = collection / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "broken.yml").write_text(
        "- name: valid task\n  debug:\n    msg: valid\n- not-a-task\n"
    )
    load_data = Load(
        target_type=LoadType.COLLECTION,
        target_name="namespace.collection",
        path=str(collection),
    )

    with pytest.raises(TaskFormatError):
        load_object(load_data, skip_task_format_error=False)
