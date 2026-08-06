# content-plugin-finder

> **Unsupported prototype.** This repository is an early experiment under
> active development. APIs, CLI flags, and behavior may change without notice.
> There is no support commitment, stability guarantee, or production readiness
> claim. Use at your own risk.

Find Ansible **modules**, **filters**, and **lookups** used in directories such as Molecule scenarios or ansible-test integration targets, and map git changes to molecule scenarios / ansible-test integration targets that should run.

Uses a pluggable **crawler subsystem**. v1 ships three crawlers; more plugin kinds can be added later without changing the orchestrator.

License: **MIT** (see [LICENSE](LICENSE)).

This project vendors [ansible-content-capture](https://github.com/ansible/ansible-content-capture) (Apache-2.0) under `src/ansible_content_capture/`. See [LICENSE.ansible-content-capture](LICENSE.ansible-content-capture) and [NOTICE](NOTICE).

Vendored note: `loader.get_scanner_version()` was patched to use `importlib.metadata` instead of removed `pkg_resources` (setuptools ≥83).

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
content-plugin-finder path/to/scenario [path/to/target ...]
content-plugin-finder --format json --by-directory path/to/scenario
content-plugin-finder --types module,filter path/to/scenario
content-plugin-finder --list-crawlers

# Discover Molecule scenarios + integration targets under a collection/repo
content-plugin-finder --parent ../ansible.platform --depth 4 --list-roots
content-plugin-finder --parent ../ansible.platform --depth 4
```

`--parent` walks for:

- directories containing `molecule.yml`
- `tests/integration/targets/<name>/`

`--depth` is the max relative depth under `--parent` (default `4`).
For a collection root, depth `3` reaches `extensions/molecule/<scenario>`;
depth `4` also reaches `tests/integration/targets/<target>`.

## Crawler subsystem

| Crawler | Kind | Source |
|---------|------|--------|
| `module` | module | ansible-content-capture task/module trees |
| `filter` | filter | Jinja pipes in YAML scalars |
| `lookup` | lookup | ACC lookup/query tasks + Jinja `lookup()` / `query()` |

Modules and action plugins are reported together as modules (not distinguishable from content alone).

## Collection import graph

Build a Python import tree and plugin **name map** for a collection:

```bash
content-plugin-finder --collection-graph ../ansible.platform
content-plugin-finder --collection-graph ../ansible.platform --plugin application
content-plugin-finder --collection-graph ../ansible.platform --plugin ansible.platform.application --format json
```

Output is **per plugin** (FQCN): entry files (module + action when both exist) plus the
**transitive** in-collection dependency closure (`depends_on_files`). Direct
file→import edges remain available in the JSON under `plugins` / `imports`.

Plugin identity is always the **FQCN** `{namespace}.{name}.{plugin}` from `galaxy.yml`
plus the short plugin name (e.g. `ansible.platform.application`).
`--plugin application` is accepted as a short alias and resolved to that FQCN.

| Kind | Short name source (then prefixed with collection FQCN) |
|------|--------------------------------------------------------|
| module | `DOCUMENTATION` `module:` / file stem |
| action | `ActionModule.MODULE_NAME`, else matching `plugins/modules/<stem>.py`, else stem |
| filter | keys from `FilterModule.filters()` (one file may expose many filters) |
| lookup | `DOCUMENTATION` `name:` / file stem |

## Impact (git changes → tests to run)

```bash
# Local / CI with explicit base (PR target SHA or branch)
content-plugin-finder --impact . --parent . --base origin/main
content-plugin-finder --impact . --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA"

# Pipe changed paths (CI escape hatch)
git diff --name-only "$BASE" "$HEAD" | content-plugin-finder --impact . --from-stdin

# Emit only names for a matrix
content-plugin-finder --impact . --base origin/main --emit molecule --names-only
content-plugin-finder --impact . --base origin/main --emit integration --names-only
content-plugin-finder --impact . --base origin/main --format json
```

Text output (default):

```text
molecule	extensions/molecule/application_mock
integration	tests/integration/targets/applications_test
```

In CI, pass the PR **base SHA** (or fetch the target branch). Bare `git diff` without a base is not reliable on shallow/detached checkouts. Three-dot `base...head` is the default; use `--two-dot` for `base head`.

```text
git changed files
        │
        ├─ under scenario/target     → that root
        └─ collection .py            → file_to_plugins → FQCNs
                │
                └─ content index → molecule scenarios / integration targets
```

### Running Molecule or ansible-test from the list

Emit leaf names, then drive the tools your collection already uses:

```bash
content-plugin-finder --impact . --base origin/main \
  --emit molecule --names-only > molecule.txt
content-plugin-finder --impact . --base origin/main \
  --emit integration --names-only > integration.txt
```

**Molecule** (scenario name = directory under `extensions/molecule/` or `molecule/`):

```bash
while read -r scenario; do
  [ -n "$scenario" ] || continue
  molecule test -s "$scenario"
done < molecule.txt
```

**ansible-test integration** (target name = directory under `tests/integration/targets/`):

```bash
mapfile -t targets < integration.txt
if ((${#targets[@]})); then
  ansible-test integration --docker default "${targets[@]}"
fi
```

Adjust Molecule/ansible-test flags to match your collection CI. An empty file means nothing to run for that kind.

Minimal PR CI sketch (fetch full history or the base SHA first):

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- name: Select tests
  run: |
    content-plugin-finder --impact . \
      --base "${{ github.event.pull_request.base.sha }}" \
      --head "${{ github.sha }}" \
      --emit molecule --names-only | tee molecule.txt
    content-plugin-finder --impact . \
      --base "${{ github.event.pull_request.base.sha }}" \
      --head "${{ github.sha }}" \
      --emit integration --names-only | tee integration.txt

- name: Molecule
  run: |
    while read -r s; do
      [ -n "$s" ] || continue
      molecule test -s "$s"
    done < molecule.txt

- name: ansible-test
  run: |
    mapfile -t t < integration.txt
    ((${#t[@]})) || exit 0
    ansible-test integration --docker default "${t[@]}"
```

## Library

```python
from pathlib import Path
from content_plugin_finder.crawl.orchestrator import Orchestrator
from content_plugin_finder.collection import build_collection_graph
from content_plugin_finder.impact import compute_impact

report = Orchestrator().scan([Path("extensions/molecule/default")])
print(report.to_dict())

graph = build_collection_graph(Path("../ansible.platform"))
print(graph.resolve("application").name)  # ansible.platform.application

impact = compute_impact(
    collection_root=Path("../ansible.platform"),
    changed_files=["plugins/action/base_action.py"],
)
print(impact.molecule_scenarios)
print(impact.integration_targets)
```
