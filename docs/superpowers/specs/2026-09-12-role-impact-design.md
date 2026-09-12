# Role-aware impact mapping design

## Purpose

Extend `content-plugin-finder` impact analysis so a changed file owned by an Ansible collection role selects every discovered Molecule scenario and ansible-test integration target that uses that role.

The change must preserve existing plugin, direct scenario, shared Molecule, and integration-target impact behavior. JSON reports must add `affected_roles` as a stable peer to `affected_plugins`.

## Scope

This design covers:

- collection-relative paths under `roles/<role_name>/...`;
- local role names derived from the collection FQCN in `galaxy.yml`;
- role references in `roles:` play entries within Molecule scenarios and integration targets;
- `ansible.builtin.include_role`, `include_role`, `ansible.builtin.import_role`, and `import_role` tasks;
- short local role names and fully qualified local role names;
- static YAML imports used by either kind of content root;
- role-aware impact reasons, JSON output, visualization, tests, and README documentation.

This design does not evaluate Jinja expressions, variables, Ansible inventory, conditions, or runtime role selection. It maps every file below a role root to the owning role. That conservative rule avoids false negatives caused by task-level execution analysis.

## Existing architecture

`build_collection_graph()` reads `galaxy.yml`, builds the plugin dependency graph, and maps changed Python files to affected plugin FQCNs.

`build_content_index()` discovers Molecule scenarios and integration targets, scans each root for plugin usage, and builds the reverse `plugin_to_roots` map.

`compute_impact()` combines direct path matches and plugin reverse-index matches into selected roots and reason strings. `ImpactReport.to_dict()` defines the JSON contract.

The visualizer parses `plugin:` and `changed:` reasons. It does not understand roles, so role reasons would otherwise leave changed files and selected roots disconnected.

## Chosen approach

Add a dedicated structural YAML role index beside the existing plugin index.

This keeps role discovery independent from the vendored `ansible-content-capture` parser. The role syntax needed by this feature is small and explicit, and PyYAML is already a runtime dependency. A focused parser is easier to test than extending plugin crawler models with a new content type.

## Components

### Role usage parser

Add `src/content_plugin_finder/impact/role_index.py` with small functions that:

1. load YAML documents with `yaml.safe_load_all()`;
2. walk mappings and sequences structurally;
3. extract role names from play-level `roles:` lists;
4. extract role names from `include_role` and `import_role` task actions in short and `ansible.builtin` forms;
5. identify static `import_playbook`, `import_tasks`, and `include_tasks` references;
6. follow static referenced YAML files while preventing cycles and duplicate parsing;
7. return normalized role FQCNs.

Supported `roles:` entries are string items and mappings with a `role` key. Supported include and import options are a scalar role name or a mapping with a `name` key.

A short role name such as `agent` resolves to `<collection>.agent`. A role name equal to or prefixed by the local collection FQCN remains unchanged. Other dotted names remain external and cannot match a changed local role.

Only literal string import paths are followed. Paths containing Jinja delimiters are dynamic and skipped. A resolved import must remain under the configured scan parent. Missing, unreadable, or invalid imported YAML files do not abort impact analysis.

### Content index

Extend `ContentIndex` with:

```text
role_to_roots: dict[str, list[str]]
```

During `build_content_index()`, parse role usage for every discovered Molecule and integration root. Add each local or external role name to the reverse index. Both root kinds remain eligible for plugin and role impact.

Add `roots_using_roles()` beside `roots_using_plugins()`. It accepts role FQCNs and returns sorted, deduplicated root matches.

Role extraction should inspect all YAML files directly below each content-root tree. The static import traversal adds referenced files outside that tree when they remain below the scan parent.

### Changed role classification

Add a helper in the impact layer that recognizes normalized paths shaped as:

```text
roles/<role_name>/<owned_path>
```

The path must contain a role name and at least one owned path component. The helper returns `<collection>.<role_name>`. It does not require the changed file to exist, so deleted role files remain detectable.

Paths outside `roles/`, the role directory itself, and malformed paths do not produce an affected role.

### Impact engine and report

Extend `ImpactReport` with an `affected_roles` list directly after `affected_plugins`. Include the key in `to_dict()` for every report, including an empty list.

For each changed path, `compute_impact()` will:

1. preserve direct root and path-prefix matching;
2. preserve plugin graph matching;
3. classify a local role owner;
4. add the owner FQCN to `affected_roles`;
5. query `roots_using_roles()`;
6. add `role:<FQCN> via <changed-path>` to each matched root's reasons.

All report lists and mappings remain sorted. Existing reason deduplication continues to prevent repeated output. Mixed plugin and role changes naturally produce the union because both paths add entries to the same root-reason map.

### Visualizer

Update `viz/app.js` to:

- recognize `affected_roles` while remaining able to load older impact reports that omit it;
- create role nodes from `affected_roles`;
- parse `role:<FQCN> via <path>` reasons;
- draw changed file to role to Molecule or integration-root edges;
- place role and plugin nodes in the middle impact column;
- add a role legend entry and role color.

Update `viz/style.css` only if a new CSS custom property is needed for the role color.

### Documentation

Update the README impact section to show the additional role branch in the data-flow diagram. Document:

- role-root ownership matching;
- supported role syntax;
- short-name resolution against the local collection FQCN;
- static import traversal and the dynamic-path limitation;
- the always-present `affected_roles` JSON field;
- conservative selection of all Molecule scenarios and integration targets that reference the owning role.

## Error handling and safety

Role parsing is best-effort, matching the current content scanning behavior. Unreadable or invalid YAML does not stop the command. The parser skips that file and continues with the remaining root content.

Static import traversal uses resolved filesystem paths and rejects files outside the configured parent. A visited-path set prevents cycles. Dynamic import expressions are skipped rather than guessed.

The changed role classifier is path-based and does not access the changed file. This keeps deleted-file impact working.

## Testing strategy

Use test-driven development. Extend the existing mini collection fixture with local roles, Molecule scenarios, and ansible-test integration targets.

Add focused parser tests for:

- string and mapping forms in `roles:`;
- short and fully qualified local role names;
- short and fully qualified `include_role` and `import_role` actions;
- scalar and mapping task options;
- static imported playbooks and task files;
- import cycles;
- dynamic, missing, invalid, and escaping import paths;
- unrelated external roles.

Add impact tests for:

- representative paths under defaults, handlers, meta, tasks, templates, vars, and files;
- the three-scenario RFE reproduction;
- an integration target that uses the changed role through its task files;
- role usage in integration-target playbooks and statically imported resources;
- an unrelated local role;
- mixed plugin and role changes with deduplicated Molecule and integration roots;
- deleted role files;
- sorted `affected_roles`;
- an empty `affected_roles` list for plugin-only and direct-path changes;
- exact role reason strings;
- JSON serialization with both affected-content keys;
- unchanged text and names-only output.

Run the complete `pytest` suite after focused tests pass. The visualizer has no JavaScript test harness, so verify it with a representative role-impact JSON document in the existing browser UI and confirm that file, role, Molecule, and integration nodes are connected.

## Acceptance mapping

The implementation is complete when:

- any owned path under `roles/<role_name>/` resolves to the local role FQCN;
- role references select only the Molecule scenarios and integration targets that use that role;
- `roles:`, `include_role`, and `import_role` syntax works in short and FQCN forms;
- static imported YAML participates in role indexing;
- role-root matching covers transitive task loading without evaluating variables;
- mixed plugin and role impact is deduplicated across both root kinds;
- `affected_roles` is always present in JSON;
- role reasons identify both the role and changed path;
- the visualizer connects role-impact nodes;
- existing impact tests and the full test suite pass;
- README documentation states the conservative and unsupported cases.
