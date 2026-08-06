/* global d3 */
(() => {
  "use strict";

  const ALL_CAP = 200;
  const state = {
    mode: "plugin", // plugin | impact
    data: null,
    kind: null, // collection-graph | impact
    focus: "",
    search: "",
    simulation: null,
  };

  const el = {
    mode: document.getElementById("mode"),
    file: document.getElementById("file"),
    focus: document.getElementById("focus"),
    search: document.getElementById("search"),
    counts: document.getElementById("counts"),
    hint: document.getElementById("hint"),
    canvas: document.getElementById("canvas"),
    detailBody: document.getElementById("detail-body"),
    pluginOnly: document.querySelectorAll(".plugin-only"),
    impactOnly: document.querySelectorAll(".impact-only"),
  };

  const svg = d3.select(el.canvas);
  const rootG = svg.append("g").attr("class", "viewport");
  const legendHost = document.querySelector(".main");

  svg
    .append("defs")
    .append("marker")
    .attr("id", "arrow")
    .attr("viewBox", "0 -4 8 8")
    .attr("refX", 14)
    .attr("refY", 0)
    .attr("markerWidth", 6)
    .attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M0,-4L8,0L0,4")
    .attr("fill", "#3d4f66");

  svg.call(
    d3
      .zoom()
      .scaleExtent([0.15, 4])
      .on("zoom", (event) => rootG.attr("transform", event.transform)),
  );

  function normalizeLoaded(data) {
    // Full collection-graph
    if (data && data.resolved && typeof data.resolved === "object") {
      if (!data.file_to_plugins) data.file_to_plugins = {};
      return data;
    }
    // Single --plugin resolution object → wrap as mini graph
    if (data && data.name && Array.isArray(data.entry_files) && Array.isArray(data.depends_on_files)) {
      const file_to_plugins = {};
      for (const f of [...data.entry_files, ...data.depends_on_files]) {
        file_to_plugins[f] = [data.name];
      }
      return {
        collection: data.name.includes(".")
          ? data.name.split(".").slice(0, 2).join(".")
          : "",
        resolved: { [data.name]: data },
        file_to_plugins,
      };
    }
    return data;
  }

  function detectKind(data) {
    if (data && data.resolved && typeof data.resolved === "object") return "collection-graph";
    if (data && Array.isArray(data.molecule_scenarios) && Array.isArray(data.affected_plugins)) {
      return "impact";
    }
    return null;
  }

  function setModeUI(mode) {
    state.mode = mode;
    el.mode.value = mode;
    el.pluginOnly.forEach((n) => {
      n.hidden = mode !== "plugin";
    });
    el.impactOnly.forEach((n) => {
      n.hidden = mode !== "impact";
    });
    if (mode === "plugin") {
      el.hint.innerHTML =
        "Plugin mode: load <code>content-plugin-finder --collection-graph . --format json &gt; graph.json</code>";
    } else {
      el.hint.innerHTML =
        "Impact mode: load <code>content-plugin-finder --impact . --base REF --format json &gt; impact.json</code>";
    }
  }

  function showDetail(text) {
    el.detailBody.textContent = text;
  }

  function clearCanvas() {
    if (state.simulation) {
      state.simulation.stop();
      state.simulation = null;
    }
    rootG.selectAll("*").remove();
    const oldLegend = legendHost.querySelector(".legend");
    if (oldLegend) oldLegend.remove();
  }

  function leaf(path) {
    const parts = String(path).split("/");
    return parts[parts.length - 1] || path;
  }

  function fileColor(path) {
    if (path.startsWith("plugins/modules/")) return "var(--modules)";
    if (path.startsWith("plugins/action/")) return "var(--action)";
    if (path.startsWith("plugins/module_utils/")) return "var(--module-utils)";
    if (path.startsWith("plugins/plugin_utils/")) return "var(--plugin-utils)";
    return "var(--other)";
  }

  function addLegend(items) {
    const div = document.createElement("div");
    div.className = "legend";
    div.innerHTML = items
      .map(([color, label]) => `<div><span style="background:${color}"></span>${label}</div>`)
      .join("");
    legendHost.appendChild(div);
  }

  function renderForceGraph(nodes, links, { colorFn, onClick, legend }) {
    clearCanvas();
    const width = el.canvas.clientWidth || 900;
    const height = el.canvas.clientHeight || 600;

    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const cleanLinks = links
      .map((l) => ({
        source: typeof l.source === "object" ? l.source.id : l.source,
        target: typeof l.target === "object" ? l.target.id : l.target,
      }))
      .filter((l) => nodeById.has(l.source) && nodeById.has(l.target));

    const link = rootG
      .append("g")
      .attr("class", "links")
      .selectAll("line")
      .data(cleanLinks)
      .join("line")
      .attr("class", "link");

    const node = rootG
      .append("g")
      .attr("class", "nodes")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("class", "node")
      .call(
        d3
          .drag()
          .on("start", (event, d) => {
            if (!event.active) state.simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) state.simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }),
      );

    node
      .append("circle")
      .attr("r", (d) => d.r || 7)
      .attr("fill", (d) => colorFn(d));

    node
      .append("text")
      .attr("dx", 10)
      .attr("dy", "0.32em")
      .text((d) => d.label);

    node.on("click", (event, d) => {
      event.stopPropagation();
      onClick(d);
    });

    state.simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(cleanLinks)
          .id((d) => d.id)
          .distance(70)
          .strength(0.4),
      )
      .force("charge", d3.forceManyBody().strength(-180))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide(18))
      .on("tick", () => {
        link
          .attr("x1", (d) => d.source.x)
          .attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x)
          .attr("y2", (d) => d.target.y);
        node.attr("transform", (d) => `translate(${d.x},${d.y})`);
      });

    if (state.search) {
      const q = state.search.toLowerCase();
      node.classed("dim", (d) => !String(d.label).toLowerCase().includes(q) && !String(d.id).toLowerCase().includes(q));
    }

    if (legend) addLegend(legend);
  }

  function buildPluginGraph(data, focusFqcn) {
    const resolved = data.resolved || {};
    const fqcns = focusFqcn ? [focusFqcn] : Object.keys(resolved).sort();
    const nodeIds = new Set();
    const links = [];

    for (const fqcn of fqcns) {
      const res = resolved[fqcn];
      if (!res) continue;
      const entries = res.entry_files || [];
      const deps = res.depends_on_files || [];
      for (const e of entries) nodeIds.add(e);
      for (const d of deps) {
        nodeIds.add(d);
        for (const e of entries) {
          links.push({ source: e, target: d });
        }
      }
    }

    if (!focusFqcn && nodeIds.size > ALL_CAP) {
      clearCanvas();
      showDetail(
        `Too many nodes (${nodeIds.size} > ${ALL_CAP}).\n` +
          `Select a Focus plugin to render a subgraph.`,
      );
      return;
    }

    let nodes = [...nodeIds].map((id) => ({
      id,
      label: leaf(id),
      kind: "file",
      path: id,
    }));

    if (state.search) {
      const q = state.search.toLowerCase();
      const keep = new Set(
        nodes.filter((n) => n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q)).map((n) => n.id),
      );
      // keep neighbors one hop
      for (const l of links) {
        if (keep.has(l.source) || keep.has(l.target)) {
          keep.add(l.source);
          keep.add(l.target);
        }
      }
      nodes = nodes.filter((n) => keep.has(n.id));
    }

    const fileToPlugins = data.file_to_plugins || {};
    renderForceGraph(nodes, links, {
      colorFn: (d) => fileColor(d.path),
      onClick: (d) => {
        const plugins = fileToPlugins[d.path] || [];
        showDetail(
          `path: ${d.path}\n` +
            `plugins (${plugins.length}):\n` +
            (plugins.length ? plugins.map((p) => `  - ${p}`).join("\n") : "  (none)"),
        );
      },
      legend: [
        ["var(--modules)", "modules"],
        ["var(--action)", "action"],
        ["var(--module-utils)", "module_utils"],
        ["var(--plugin-utils)", "plugin_utils"],
        ["var(--other)", "other"],
      ],
    });
  }

  function buildImpactGraph(data) {
    const reasons = data.reasons || {};
    const nodeMap = new Map();
    const links = [];

    function ensure(id, type, label) {
      if (!nodeMap.has(id)) {
        nodeMap.set(id, { id, type, label: label || leaf(id), r: type === "plugin" ? 8 : 7 });
      }
      return nodeMap.get(id);
    }

    for (const f of data.changed_files || []) {
      ensure(`file:${f}`, "file", leaf(f));
    }
    for (const p of data.affected_plugins || []) {
      ensure(`plugin:${p}`, "plugin", p);
    }
    for (const m of data.molecule_scenarios || []) {
      ensure(`root:${m}`, "molecule", leaf(m));
    }
    for (const t of data.integration_targets || []) {
      ensure(`root:${t}`, "integration", leaf(t));
    }

    const edgeKey = new Set();
    function edge(a, b) {
      const k = `${a}->${b}`;
      if (edgeKey.has(k)) return;
      edgeKey.add(k);
      links.push({ source: a, target: b });
    }

    for (const [root, reasonList] of Object.entries(reasons)) {
      const rootId = `root:${root}`;
      const kind = (data.molecule_scenarios || []).includes(root)
        ? "molecule"
        : (data.integration_targets || []).includes(root)
          ? "integration"
          : root.includes("molecule")
            ? "molecule"
            : "integration";
      ensure(rootId, kind, leaf(root));

      for (const reason of reasonList || []) {
        if (reason.startsWith("changed:")) {
          const path = reason.slice("changed:".length);
          const fid = `file:${path}`;
          ensure(fid, "file", leaf(path));
          edge(fid, rootId);
        } else if (reason.startsWith("plugin:")) {
          // plugin:FQCN via path
          const rest = reason.slice("plugin:".length);
          const viaIdx = rest.lastIndexOf(" via ");
          if (viaIdx === -1) continue;
          const plugin = rest.slice(0, viaIdx);
          const path = rest.slice(viaIdx + 5);
          const pid = `plugin:${plugin}`;
          const fid = `file:${path}`;
          ensure(pid, "plugin", plugin);
          ensure(fid, "file", leaf(path));
          edge(fid, pid);
          edge(pid, rootId);
        }
      }
    }

    const width = el.canvas.clientWidth || 900;
    const height = el.canvas.clientHeight || 600;
    const colX = { file: width * 0.18, plugin: width * 0.5, molecule: width * 0.82, integration: width * 0.82 };

    const nodes = [...nodeMap.values()];
    // Pre-position by column for layered feel; force will refine
    const buckets = { file: [], plugin: [], molecule: [], integration: [] };
    for (const n of nodes) {
      (buckets[n.type] || buckets.file).push(n);
    }
    for (const [type, list] of Object.entries(buckets)) {
      list.forEach((n, i) => {
        n.x = colX[type] || width / 2;
        n.y = ((i + 1) / (list.length + 1)) * height;
        n.fx = n.x;
      });
    }

    clearCanvas();
    // release fx after a short settle so drag works
    renderForceGraph(nodes, links, {
      colorFn: (d) => {
        if (d.type === "file") return "var(--file)";
        if (d.type === "plugin") return "var(--plugin)";
        if (d.type === "molecule") return "var(--molecule)";
        return "var(--integration)";
      },
      onClick: (d) => {
        showDetail(`type: ${d.type}\nid: ${d.id.replace(/^(file|plugin|root):/, "")}\nlabel: ${d.label}`);
      },
      legend: [
        ["var(--file)", "changed file"],
        ["var(--plugin)", "plugin FQCN"],
        ["var(--molecule)", "molecule scenario"],
        ["var(--integration)", "integration target"],
      ],
    });

    // column gravity
    if (state.simulation) {
      state.simulation
        .force(
          "x",
          d3
            .forceX((d) => colX[d.type] || width / 2)
            .strength(0.35),
        )
        .force("y", d3.forceY(height / 2).strength(0.02));
      // unlock after warm-up
      setTimeout(() => {
        for (const n of nodes) n.fx = null;
        if (state.simulation) state.simulation.alpha(0.2).restart();
      }, 1200);
    }

    el.counts.innerHTML =
      `<strong>files</strong>${(data.changed_files || []).length} ` +
      `<strong>plugins</strong>${(data.affected_plugins || []).length} ` +
      `<strong>molecule</strong>${(data.molecule_scenarios || []).length} ` +
      `<strong>integration</strong>${(data.integration_targets || []).length}`;
  }

  function populateFocus(data) {
    const keys = Object.keys((data && data.resolved) || {}).sort();
    el.focus.innerHTML = "";
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "All (capped)";
    el.focus.appendChild(all);
    for (const k of keys) {
      const opt = document.createElement("option");
      opt.value = k;
      opt.textContent = k;
      el.focus.appendChild(opt);
    }
    if (keys.includes("ansible.platform.application")) {
      el.focus.value = "ansible.platform.application";
      state.focus = "ansible.platform.application";
    } else if (keys.length) {
      el.focus.value = keys[0];
      state.focus = keys[0];
    }
  }

  function render() {
    if (!state.data) {
      clearCanvas();
      showDetail("Load a JSON file to begin.");
      return;
    }
    if (state.mode === "plugin") {
      if (state.kind !== "collection-graph") {
        clearCanvas();
        showDetail("Current JSON is not a collection-graph. Switch mode or load graph.json.");
        return;
      }
      buildPluginGraph(state.data, state.focus || "");
    } else {
      if (state.kind !== "impact") {
        clearCanvas();
        showDetail("Current JSON is not an impact report. Switch mode or load impact.json.");
        return;
      }
      buildImpactGraph(state.data);
    }
  }

  function loadData(raw) {
    const data = normalizeLoaded(raw);
    state.data = data;
    state.kind = detectKind(data);
    if (!state.kind) {
      showDetail("Unrecognized JSON. Expected collection-graph or impact output.");
      return;
    }
    if (state.kind === "collection-graph") {
      setModeUI("plugin");
      populateFocus(data);
    } else {
      setModeUI("impact");
    }
    render();
  }

  el.mode.addEventListener("change", () => {
    setModeUI(el.mode.value);
    render();
  });

  el.focus.addEventListener("change", () => {
    state.focus = el.focus.value;
    render();
  });

  el.search.addEventListener("input", () => {
    state.search = el.search.value.trim();
    render();
  });

  el.file.addEventListener("change", async () => {
    const file = el.file.files && el.file.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      loadData(JSON.parse(text));
    } catch (err) {
      showDetail(`Failed to parse JSON: ${err}`);
    }
  });

  window.addEventListener("resize", () => {
    if (state.data) render();
  });

  setModeUI("plugin");
  showDetail("Load a JSON file to begin.");
})();
