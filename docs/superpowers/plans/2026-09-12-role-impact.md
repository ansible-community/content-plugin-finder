# Role-aware impact mapping implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Map changed Ansible collection role files to every discovered Molecule scenario and ansible-test integration target that uses the owning role.

**Architecture:** Add a focused PyYAML role-usage parser and store its reverse mapping in `ContentIndex` beside the existing plugin index. Extend `compute_impact()` and `ImpactReport` with role ownership, `affected_roles`, and role reasons, then teach the visualizer and README about the new relationship.

**Tech Stack:** Python 3.11+, dataclasses, pathlib, PyYAML, pytest, vanilla JavaScript, D3.js, CSS

**Spec:** `docs/superpowers/specs/2026-09-12-role-impact-design.md`

## Global constraints

- Keep plugin, direct-root, shared-Molecule, and integration-target impact behavior unchanged.
- Index role use in both Molecule scenarios and ansible-test integration targets.
- Resolve short role names against the collection FQCN read from `galaxy.yml`.
- Support play-level `roles:`, `include_role`, and `import_role` in short and `ansible.builtin` forms.
- Follow only literal static YAML imports whose resolved paths stay below the configured scan parent.
- Skip dynamic Jinja imports, missing files, unreadable files, and invalid YAML without aborting impact analysis.
- Treat every file below `roles/<role_name>/` as owned by that role, including deleted files.
- Always serialize `affected_roles`, using an empty list when no role is affected.
- Keep lists, reverse indexes, roots, and reasons sorted and deduplicated.
- Add no runtime dependency. PyYAML is already declared in `pyproject.toml`.
- Use `uv run --extra dev pytest` because this worktree does not have a standalone `pytest` command.

---

## File map

- Create `src/content_plugin_finder/impact/role_index.py` for structural role extraction and bounded static import traversal.
- Create `tests/test_role_index.py` for parser and traversal unit tests.
- Modify `src/content_plugin_finder/impact/content_index.py` to add `role_to_roots` and `roots_using_roles()`.
- Modify `src/content_plugin_finder/impact/engine.py` to classify changed role paths, populate `affected_roles`, and add role reasons.
- Modify `tests/test_impact.py` to cover Molecule and integration role impact, report serialization, negative cases, and mixed changes.
- Modify `viz/app.js` to render role nodes, edges, counts, and details.
- Modify `viz/style.css` to define the role-node color.
- Modify `README.md` to document role-aware impact selection and JSON output.
- Keep `content-plugin-finder-role-impact-rfe.md` as source material; do not add it to a commit unless the user asks.

---

### Task 1: Parse structural role usage and static imports

**Files:**
- Create: `src/content_plugin_finder/impact/role_index.py`
- Create: `tests/test_role_index.py`

**Interfaces:**
- Consumes: a discovered content root, the configured scan parent, and a collection FQCN.
- Produces: `roles_used_by_root(root: Path, *, parent: Path, collection: str) -> set[str]`.
- Produces: normalized role names such as `acme.widgets.agent`; external dotted role names remain unchanged.

- [ ] **Step 1: Write failing tests for direct role syntax**

Create `tests/test_role_index.py` with parametrized cases for play roles and role actions:

```python
from pathlib import Path

import pytest

from content_plugin_finder.impact.role_index import roles_used_by_root


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "- hosts: localhost\n  roles:\n    - agent\n",
            {"acme.widgets.agent"},
        ),
        (
            "- hosts: localhost\n  roles:\n    - role: acme.widgets.agent\n",
            {"acme.widgets.agent"},
        ),
        (
            "- hosts: localhost\n  tasks:\n    - include_role:\n        name: agent\n",
            {"acme.widgets.agent"},
        ),
        (
            "- hosts: localhost\n  tasks:\n    - ansible.builtin.include_role: agent\n",
            {"acme.widgets.agent"},
        ),
        (
            "- hosts: localhost\n  tasks:\n"
            "    - import_role:\n        name: acme.widgets.agent\n",
            {"acme.widgets.agent"},
        ),
        (
            "- hosts: localhost\n  tasks:\n"
            "    - ansible.builtin.import_role: external.vendor.agent\n",
            {"external.vendor.agent"},
        ),
    ],
)
def test_roles_used_by_root_extracts_supported_syntax(
    tmp_path: Path,
    content: str,
    expected: set[str],
):
    root = tmp_path / "molecule" / "default"
    root.mkdir(parents=True)
    (root / "converge.yml").write_text(content, encoding="utf-8")

    assert (
        roles_used_by_root(
            root,
            parent=tmp_path,
            collection="acme.widgets",
        )
        == expected
    )
```

- [ ] **Step 2: Run the direct-syntax tests and verify the missing module failure**

Run:

```bash
uv run --extra dev pytest tests/test_role_index.py::test_roles_used_by_root_extracts_supported_syntax -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'content_plugin_finder.impact.role_index'`.

- [ ] **Step 3: Write failing tests for static import traversal and parser safety**

Append tests that prove imported files outside the root but inside `parent` are followed, cycles terminate, and unsafe or unusable imports are skipped:

```python
def test_roles_used_by_root_follows_static_imports_once(tmp_path: Path):
    root = tmp_path / "molecule" / "default"
    shared = tmp_path / "molecule" / "shared"
    tasks = shared / "tasks"
    root.mkdir(parents=True)
    tasks.mkdir(parents=True)
    (root / "converge.yml").write_text(
        "- import_playbook: ../shared/playbook.yml\n",
        encoding="utf-8",
    )
    (shared / "playbook.yml").write_text(
        "- hosts: localhost\n  tasks:\n    - import_tasks: tasks/roles.yml\n",
        encoding="utf-8",
    )
    (tasks / "roles.yml").write_text(
        "- include_role:\n    name: agent\n- import_tasks: ../playbook.yml\n",
        encoding="utf-8",
    )

    assert roles_used_by_root(
        root,
        parent=tmp_path,
        collection="acme.widgets",
    ) == {"acme.widgets.agent"}


def test_roles_used_by_root_skips_dynamic_and_escaping_imports(tmp_path: Path):
    parent = tmp_path / "content"
    root = parent / "molecule" / "default"
    root.mkdir(parents=True)
    (tmp_path / "outside.yml").write_text(
        "- include_role:\n    name: outside\n",
        encoding="utf-8",
    )
    (root / "converge.yml").write_text(
        "- import_playbook: '{{ selected_playbook }}'\n"
        "- import_playbook: ../../../outside.yml\n",
        encoding="utf-8",
    )
    (root / "tasks.yml").write_text(
        "- include_role:\n    name: local\n",
        encoding="utf-8",
    )

    assert roles_used_by_root(
        root,
        parent=parent,
        collection="acme.widgets",
    ) == {"acme.widgets.local"}


def test_roles_used_by_root_skips_invalid_and_missing_yaml(tmp_path: Path):
    root = tmp_path / "molecule" / "default"
    root.mkdir(parents=True)
    (root / "converge.yml").write_text(
        "- import_playbook: missing.yml\n",
        encoding="utf-8",
    )
    (root / "broken.yml").write_text("[not valid", encoding="utf-8")
    (root / "valid.yaml").write_text(
        "- import_role:\n    name: agent\n",
        encoding="utf-8",
    )

    assert roles_used_by_root(
        root,
        parent=tmp_path,
        collection="acme.widgets",
    ) == {"acme.widgets.agent"}
```

- [ ] **Step 4: Implement the structural parser**

Create `src/content_plugin_finder/impact/role_index.py` with these constants, helpers, and public function:

```python
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import yaml

_YAML_SUFFIXES = frozenset({".yml", ".yaml"})
_ROLE_ACTIONS = frozenset(
    {
        "include_role",
        "import_role",
        "ansible.builtin.include_role",
        "ansible.builtin.import_role",
    }
)
_IMPORT_ACTIONS = frozenset(
    {
        "import_playbook",
        "import_tasks",
        "include_tasks",
        "ansible.builtin.import_playbook",
        "ansible.builtin.import_tasks",
        "ansible.builtin.include_tasks",
    }
)


def _option(value: Any, key: str) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate.strip() or None
    return None


def _normalize_role(name: str, collection: str) -> str | None:
    name = name.strip()
    if not name or "{{" in name or "{%" in name:
        return None
    if "." not in name:
        return f"{collection}.{name}"
    return name


def _walk_node(node: Any, collection: str) -> tuple[set[str], set[str]]:
    roles: set[str] = set()
    imports: set[str] = set()

    if isinstance(node, list):
        for item in node:
            item_roles, item_imports = _walk_node(item, collection)
            roles.update(item_roles)
            imports.update(item_imports)
        return roles, imports

    if not isinstance(node, dict):
        return roles, imports

    if "hosts" in node and isinstance(node.get("roles"), list):
        for item in node["roles"]:
            raw = item if isinstance(item, str) else _option(item, "role")
            if isinstance(raw, str):
                normalized = _normalize_role(raw, collection)
                if normalized:
                    roles.add(normalized)

    for action in _ROLE_ACTIONS:
        if action not in node:
            continue
        raw = _option(node[action], "name")
        if raw:
            normalized = _normalize_role(raw, collection)
            if normalized:
                roles.add(normalized)

    for action in _IMPORT_ACTIONS:
        if action not in node:
            continue
        raw = _option(node[action], "file")
        if raw and "{{" not in raw and "{%" not in raw:
            imports.add(raw)

    for value in node.values():
        child_roles, child_imports = _walk_node(value, collection)
        roles.update(child_roles)
        imports.update(child_imports)
    return roles, imports


def _is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def roles_used_by_root(
    root: Path,
    *,
    parent: Path,
    collection: str,
) -> set[str]:
    root = root.resolve()
    parent = parent.resolve()
    initial = sorted(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _YAML_SUFFIXES
    )
    queue: deque[Path] = deque(initial)
    visited: set[Path] = set()
    roles: set[str] = set()

    while queue:
        path = queue.popleft().resolve()
        if path in visited or not _is_below(path, parent):
            continue
        visited.add(path)
        try:
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError):
            continue

        for document in documents:
            found_roles, imports = _walk_node(document, collection)
            roles.update(found_roles)
            for imported in sorted(imports):
                imported_path = (path.parent / imported).resolve()
                if (
                    imported_path.is_file()
                    and imported_path.suffix.lower() in _YAML_SUFFIXES
                    and _is_below(imported_path, parent)
                ):
                    queue.append(imported_path)

    return roles
```

Keep helper functions private. Do not add roles to `PluginKind` or the generic crawler report.

- [ ] **Step 5: Run the parser tests**

Run:

```bash
uv run --extra dev pytest tests/test_role_index.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the parser**

```bash
git add src/content_plugin_finder/impact/role_index.py tests/test_role_index.py
git commit -m "feat(impact): parse role usage from YAML"
```

---

### Task 2: Add role usage to the content index

**Files:**
- Modify: `src/content_plugin_finder/impact/content_index.py:12-99`
- Modify: `tests/test_impact.py:10-69`
- Test: `tests/test_impact.py`

**Interfaces:**
- Consumes: `roles_used_by_root(root, parent=parent, collection=collection) -> set[str]` from Task 1.
- Produces: `ContentIndex.role_to_roots: dict[str, list[str]]`.
- Produces: `roots_using_roles(index: ContentIndex, roles: set[str]) -> dict[str, list[str]]`.

- [ ] **Step 1: Extend the mini collection fixture with a shared local role**

In `_mini_collection()`, create the collection role and make the existing Molecule scenario and integration target reference it. Keep their existing module tasks so plugin-impact tests retain their current contract:

```python
    role = tmp_path / "roles" / "agent" / "tasks"
    role.mkdir(parents=True)
    (role / "main.yml").write_text(
        "- ansible.builtin.debug:\n    msg: agent\n",
        encoding="utf-8",
    )
```

Change `thing_mock/converge.yml` to include a play-level role before its existing tasks:

```python
    (mol / "converge.yml").write_text(
        "- hosts: localhost\n"
        "  roles:\n"
        "    - role: acme.widgets.agent\n"
        "  tasks:\n"
        "    - acme.widgets.thing:\n"
        "        name: x\n",
        encoding="utf-8",
    )
```

Make `thing_test/tasks/main.yml` statically import a task file that uses `include_role`. This proves integration-root import traversal, rather than only direct role extraction:

```python
(target / "tasks" / "main.yml").write_text(
    "- acme.widgets.thing:\n    name: y\n- ansible.builtin.import_tasks: role.yml\n",
    encoding="utf-8",
)
(target / "tasks" / "role.yml").write_text(
    "- ansible.builtin.include_role:\n    name: agent\n",
    encoding="utf-8",
)
```

Change the unrelated Molecule scenario so it references an external role with the same leaf name. This proves local `acme.widgets.agent` changes do not match `external.vendor.agent`:

```python
    (other / "converge.yml").write_text(
        "- hosts: localhost\n"
        "  roles:\n"
        "    - external.vendor.agent\n"
        "  tasks:\n"
        "    - ansible.builtin.debug:\n"
        "        msg: hi\n",
        encoding="utf-8",
    )
```

- [ ] **Step 2: Write the failing content-index test**

Update the import from `content_index` to include `roots_using_roles`, then add:

```python
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
```

- [ ] **Step 3: Run the content-index test and verify the missing field failure**

Run:

```bash
uv run --extra dev pytest tests/test_impact.py::test_content_index_maps_roles_to_molecule_and_integration_roots -v
```

Expected: FAIL because `ContentIndex` has no `role_to_roots` attribute.

- [ ] **Step 4: Extend `ContentIndex` and its builder**

Import the Task 1 function:

```python
from content_plugin_finder.impact.role_index import roles_used_by_root
```

Add the reverse map to `ContentIndex`:

```python
    # role FQCN -> root relpaths
    role_to_roots: dict[str, list[str]] = field(default_factory=dict)
```

In `build_content_index()`, initialize a role accumulator beside `plugin_to_roots`:

```python
    role_to_roots: dict[str, set[str]] = defaultdict(set)
```

Store `kind` once per root and index roles for both supported root kinds:

```python
        kind = classify_root(root, parent)
        index.root_kinds[rel] = kind
        if kind in {"molecule", "integration"}:
            for role in roles_used_by_root(
                root,
                parent=parent,
                collection=collection,
            ):
                role_to_roots[role].add(rel)
```

Finalize the map before returning:

```python
    index.role_to_roots = {
        role: sorted(roots) for role, roots in sorted(role_to_roots.items())
    }
```

Add an exact-match reverse lookup because role names are normalized during indexing:

```python
def roots_using_roles(index: ContentIndex, roles: set[str]) -> dict[str, list[str]]:
    """Return root relpath to matching normalized role FQCNs."""
    hits: dict[str, set[str]] = defaultdict(set)
    for role in roles:
        for root in index.role_to_roots.get(role, []):
            hits[root].add(role)
    return {root: sorted(found) for root, found in sorted(hits.items())}
```

- [ ] **Step 5: Run content-index and existing impact tests**

Run:

```bash
uv run --extra dev pytest tests/test_impact.py -v
```

Expected: all existing tests plus the new content-index test pass. Existing plugin results still include both `thing_mock` and `thing_test`.

- [ ] **Step 6: Commit the reverse index**

```bash
git add src/content_plugin_finder/impact/content_index.py tests/test_impact.py
git commit -m "feat(impact): index role usage by content root"
```

---

### Task 3: Map changed role files into impact reports

**Files:**
- Modify: `src/content_plugin_finder/impact/engine.py:10-37,134-213`
- Modify: `tests/test_impact.py`

**Interfaces:**
- Consumes: `roots_using_roles(index, roles) -> dict[str, list[str]]` from Task 2.
- Produces: `ImpactReport.affected_roles: list[str]`.
- Produces: JSON with `affected_roles` directly after `affected_plugins`.
- Produces: reason strings shaped as `role:<FQCN> via <collection-relative-path>`.

- [ ] **Step 1: Write failing role-impact tests for both root kinds**

Import `json`, `pytest`, and `format_impact_json`, then add:

```python
import json

import pytest

from content_plugin_finder.impact.engine import (
    compute_impact,
    format_impact_json,
    format_impact_text,
)


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
```

The test deliberately names files that do not exist. Passing proves path ownership works for deleted files and every representative role subdirectory.

Add the exact three-scenario reproduction from the RFE:

```python
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
            "- hosts: localhost\n  roles:\n    - role: community.beszel.agent\n",
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
```

Add a deterministic-order test with two changed local roles:

```python
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
```

- [ ] **Step 2: Write failing report-contract and negative tests**

Add tests for stable JSON, unrelated roles, malformed paths, and mixed impact:

```python
def test_impact_json_always_contains_affected_roles(tmp_path: Path):
    root = _mini_collection(tmp_path)
    report = compute_impact(
        collection_root=root,
        changed_files=["plugins/module_utils/core.py"],
        parent=root,
    )

    payload = json.loads(format_impact_json(report))
    assert (
        list(payload).index("affected_roles")
        == list(payload).index("affected_plugins") + 1
    )
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
```

The external `external.vendor.agent` reference in the fixture must not make a local `roles/agent/...` change select the unrelated scenario. Recording `acme.widgets.unrelated` as affected is valid even though no root uses it. Malformed non-owned paths must leave `affected_roles` empty.

- [ ] **Step 3: Run the new engine tests and verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_impact.py -k "role_file or affected_roles or unreferenced_local_role or malformed_role_path or mixed_plugin_and_role" -v
```

Expected: FAIL because `ImpactReport` has no `affected_roles` and `compute_impact()` does not map role changes.

- [ ] **Step 4: Add `affected_roles` to the report contract**

Import `roots_using_roles` from `content_index`. Add the field directly after `affected_plugins`:

```python
@dataclass
class ImpactReport:
    collection: str
    changed_files: list[str] = field(default_factory=list)
    affected_plugins: list[str] = field(default_factory=list)
    affected_roles: list[str] = field(default_factory=list)
    molecule_scenarios: list[str] = field(default_factory=list)
    integration_targets: list[str] = field(default_factory=list)
    reasons: dict[str, list[str]] = field(default_factory=dict)
```

Add the serialized key in the same position:

```python
            "affected_plugins": self.affected_plugins,
            "affected_roles": self.affected_roles,
            "molecule_scenarios": self.molecule_scenarios,
```

- [ ] **Step 5: Classify collection-relative role paths**

Add a private helper near `_normalize_rel()`:

```python
def _role_for_file(changed: str, collection: str) -> str | None:
    parts = changed.split("/")
    if len(parts) < 3 or parts[0] != "roles":
        return None
    role = parts[1]
    if not role or role in {".", ".."}:
        return None
    return f"{collection}.{role}"
```

Do not check the filesystem. Impact analysis must continue to recognize deleted role files.

- [ ] **Step 6: Join affected roles to indexed roots**

Initialize the role set beside the plugin set:

```python
    affected_roles: set[str] = set()
```

Inside the changed-file loop, after plugin matching, add:

```python
        role = _role_for_file(changed, graph.collection)
        if role is not None:
            affected_roles.add(role)
            for root, matched in roots_using_roles(content_index, {role}).items():
                for matched_role in matched:
                    reason = f"role:{matched_role} via {changed}"
                    if reason not in reasons[root]:
                        reasons[root].append(reason)
```

Populate the report with sorted roles:

```text
        affected_plugins=sorted(affected_plugins),
        affected_roles=sorted(affected_roles),
        molecule_scenarios=molecule,
```

- [ ] **Step 7: Run focused and complete Python tests**

Run:

```bash
uv run --extra dev pytest tests/test_role_index.py tests/test_impact.py -v
uv run --extra dev pytest -v
```

Expected: both commands pass. The full suite verifies that plugin crawling, collection graphs, discovery, CLI behavior, and report formatting remain unchanged.

- [ ] **Step 8: Commit impact mapping**

```bash
git add src/content_plugin_finder/impact/engine.py tests/test_impact.py
git commit -m "feat(impact): map role changes to affected roots"
```

---

### Task 4: Render role impact in the visualizer

**Files:**
- Modify: `viz/app.js:53-81,303-430`
- Modify: `viz/style.css:1-17`

**Interfaces:**
- Consumes: `affected_roles: string[]` and `role:<FQCN> via <path>` reasons from Task 3.
- Produces: file-to-role-to-root graph edges, a role count, a role legend entry, and role details.
- Preserves: loading older impact JSON that omits `affected_roles`.

- [ ] **Step 1: Add role-aware normalization and nodes**

In `normalizeLoaded()`, retain backward compatibility after the collection-graph branches:

```javascript
    if (data && Array.isArray(data.molecule_scenarios) && Array.isArray(data.affected_plugins)) {
      if (!Array.isArray(data.affected_roles)) data.affected_roles = [];
      return data;
    }
```

In `buildImpactGraph()`, create role nodes after plugin nodes:

```javascript
    for (const role of data.affected_roles || []) {
      ensure(`role:${role}`, "role", role);
    }
```

Treat role nodes like plugin nodes when assigning their radius:

```javascript
        const middle = type === "plugin" || type === "role";
        nodeMap.set(id, { id, type, label: label || leaf(id), r: middle ? 8 : 7 });
```

- [ ] **Step 2: Parse role reasons and connect both root kinds**

Replace the plugin-only reason branch with a shared plugin-or-role branch:

```javascript
        } else if (reason.startsWith("plugin:") || reason.startsWith("role:")) {
          const type = reason.startsWith("plugin:") ? "plugin" : "role";
          const rest = reason.slice(`${type}:`.length);
          const viaIdx = rest.lastIndexOf(" via ");
          if (viaIdx === -1) continue;
          const name = rest.slice(0, viaIdx);
          const path = rest.slice(viaIdx + 5);
          const contentId = `${type}:${name}`;
          const fileId = `file:${path}`;
          ensure(contentId, type, name);
          ensure(fileId, "file", leaf(path));
          edge(fileId, contentId);
          edge(contentId, rootId);
```

Add `role` to the middle column and buckets:

```javascript
    const colX = {
      file: width * 0.18,
      plugin: width * 0.5,
      role: width * 0.5,
      molecule: width * 0.82,
      integration: width * 0.82,
    };
    const buckets = { file: [], plugin: [], role: [], molecule: [], integration: [] };
```

Update detail-prefix removal:

```javascript
        showDetail(`type: ${d.type}\nid: ${d.id.replace(/^(file|plugin|role|root):/, "")}\nlabel: ${d.label}`);
```

- [ ] **Step 3: Add role color, legend, and count**

In `viz/style.css`, add a distinct middle-node color:

```css
  --role: #f2cc60;
```

In the impact color function and legend, add:

```javascript
        if (d.type === "role") return "var(--role)";
```

```javascript
        ["var(--role)", "role FQCN"],
```

Add roles to the count line between plugins and roots:

```javascript
      `<strong>plugins</strong>${(data.affected_plugins || []).length} ` +
      `<strong>roles</strong>${(data.affected_roles || []).length} ` +
      `<strong>molecule</strong>${(data.molecule_scenarios || []).length} ` +
```

- [ ] **Step 4: Check JavaScript syntax**

Run:

```bash
node --check viz/app.js
```

Expected: exit code 0 with no output.

- [ ] **Step 5: Verify a representative role graph in the browser**

Create `/tmp/content-plugin-finder-role-impact.json` with:

```json
{
  "collection": "acme.widgets",
  "changed_files": ["roles/agent/tasks/main.yml"],
  "affected_plugins": [],
  "affected_roles": ["acme.widgets.agent"],
  "molecule_scenarios": ["extensions/molecule/thing_mock"],
  "integration_targets": ["tests/integration/targets/thing_test"],
  "reasons": {
    "extensions/molecule/thing_mock": [
      "role:acme.widgets.agent via roles/agent/tasks/main.yml"
    ],
    "tests/integration/targets/thing_test": [
      "role:acme.widgets.agent via roles/agent/tasks/main.yml"
    ]
  }
}
```

Serve `viz/` locally:

```bash
python3 -m http.server 8000 --directory viz
```

Open `http://127.0.0.1:8000`, load the JSON file, and verify:

- counts show one file, zero plugins, one role, one Molecule scenario, and one integration target;
- the graph contains one role node between the changed file and both selected roots;
- clicking the role node shows `type: role` and `id: acme.widgets.agent`;
- an older impact report without `affected_roles` still loads with a zero role count.

Stop the local server after verification.

- [ ] **Step 6: Commit visualizer support**

```bash
git add viz/app.js viz/style.css
git commit -m "feat(viz): render role impact relationships"
```

---

### Task 5: Document the contract and run final verification

**Files:**
- Modify: `README.md:122-162,248-268`
- Include: `docs/superpowers/specs/2026-09-12-role-impact-design.md`
- Include: `docs/superpowers/plans/2026-09-12-role-impact.md`
- Test: complete repository

**Interfaces:**
- Documents: the CLI behavior implemented in Tasks 1 through 4.
- Produces: one public explanation of role ownership, supported syntax, both root kinds, JSON shape, and static-import limits.

- [ ] **Step 1: Extend the README impact flow**

Replace the plugin-only changed-content branch with a role branch that names both selected root kinds:

```text
git changed files
        │
        ├─ under scenario/target     → that root
        │     (path layout works even if discovery depth missed the root)
        ├─ shared molecule file      → all discovered molecule scenarios
        │     (e.g. extensions/molecule/requirements.yml)
        ├─ roles/<role>/...          → local role FQCN
        │       │
        │       └─ role index → molecule scenarios / integration targets
        └─ collection .py            → file_to_plugins → plugin FQCNs
                │
                └─ content index → molecule scenarios / integration targets
```

Follow the diagram with prose that states:

```markdown
A changed path below `roles/<role_name>/` affects the local role
`<namespace>.<collection>.<role_name>`, using the collection identity from
`galaxy.yml`. Every discovered Molecule scenario or ansible-test integration
target that references that role is selected. The match is conservative: any
file owned by the role selects every root that uses the role.

Role indexing supports string and mapping entries under play-level `roles:`,
plus short and `ansible.builtin` forms of `include_role` and `import_role`.
Short role names resolve against the local collection. Literal
`import_playbook`, `import_tasks`, and `include_tasks` paths are followed while
they remain below `--parent`; dynamic Jinja import paths are not evaluated.
```

- [ ] **Step 2: Document the stable JSON field**

Add a compact JSON example after the impact commands:

```json
{
  "collection": "acme.widgets",
  "changed_files": ["roles/agent/tasks/main.yml"],
  "affected_plugins": [],
  "affected_roles": ["acme.widgets.agent"],
  "molecule_scenarios": ["extensions/molecule/thing_mock"],
  "integration_targets": ["tests/integration/targets/thing_test"],
  "reasons": {
    "extensions/molecule/thing_mock": [
      "role:acme.widgets.agent via roles/agent/tasks/main.yml"
    ],
    "tests/integration/targets/thing_test": [
      "role:acme.widgets.agent via roles/agent/tasks/main.yml"
    ]
  }
}
```

State directly below it that `affected_plugins` and `affected_roles` are always present and use empty lists when their content type is unaffected.

- [ ] **Step 3: Extend the library example**

After the existing impact report prints, add:

```python
print(impact.affected_plugins)
print(impact.affected_roles)
```

- [ ] **Step 4: Run formatting and syntax checks**

Run:

```bash
git diff --check
node --check viz/app.js
```

Expected: both commands exit 0; `node --check` prints no output.

- [ ] **Step 5: Run the focused and full test suites**

Run:

```bash
uv run --extra dev pytest tests/test_role_index.py tests/test_impact.py -v
uv run --extra dev pytest -v
```

Expected: all tests pass in both commands.

- [ ] **Step 6: Review the final diff against the spec**

Run:

```bash
git status --short
git diff --stat
git diff -- src/content_plugin_finder/impact tests/test_role_index.py tests/test_impact.py viz README.md docs/superpowers
```

Confirm every spec acceptance item has an implementation or test. Confirm no unrelated crawler, collection-graph, CLI-option, or vendored `ansible_content_capture` code changed. Confirm `content-plugin-finder-role-impact-rfe.md` remains outside the staged set unless the user explicitly requests it.

- [ ] **Step 7: Commit documentation and planning artifacts**

```bash
git add README.md docs/superpowers/specs/2026-09-12-role-impact-design.md docs/superpowers/plans/2026-09-12-role-impact.md
git commit -m "docs(impact): document role-aware selection"
```

- [ ] **Step 8: Verify the committed tree**

Run:

```bash
git status --short
git log -5 --oneline
```

Expected: only `content-plugin-finder-role-impact-rfe.md` remains untracked unless the user separately chose to add it. The recent log contains the parser, index, engine, visualizer, and documentation commits from this plan.
