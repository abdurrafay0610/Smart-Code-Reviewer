/* ============================================================================
   Smart Code Reviewer — app logic
   Three views (Connect / Map / Review) driven by a small central state object.
   ========================================================================== */

const state = {
  view: "projects",
  projects: [],
  active: null, // active project (public model)
  branches: null, // {branches, default_branch} for the active project
  branchesPopulated: false,
  hasCompared: false,
};

const VIEWS = {
  projects: {
    step: 1,
    title: "Projects",
    subtitle: "Connect a repository, then build its map and review changes.",
  },
  map: {
    step: 2,
    title: "Project map",
    subtitle: "Give the reviewer context about how this codebase is meant to fit together.",
  },
  review: {
    step: 3,
    title: "Review changes",
    subtitle: "Compare a feature branch against its base to see what it introduced.",
  },
};

let els = {};

function cacheEls() {
  els = {
    stages: document.getElementById("stages"),
    activeProject: document.getElementById("activeProject"),
    activeProjectName: document.getElementById("activeProjectName"),
    changeProjectBtn: document.getElementById("changeProjectBtn"),

    viewEyebrow: document.getElementById("viewEyebrow"),
    viewTitle: document.getElementById("viewTitle"),
    viewSubtitle: document.getElementById("viewSubtitle"),

    connectForm: document.getElementById("connectForm"),
    repoUrl: document.getElementById("repoUrl"),
    connectBtn: document.getElementById("connectBtn"),
    connectError: document.getElementById("connectError"),
    projectList: document.getElementById("projectList"),
    projectCount: document.getElementById("projectCount"),
    projectEmpty: document.getElementById("projectEmpty"),

    mapContext: document.getElementById("mapContext"),
    mapState: document.getElementById("mapState"),

    reviewContext: document.getElementById("reviewContext"),
    baseSelect: document.getElementById("baseSelect"),
    compareSelect: document.getElementById("compareSelect"),
    compareBtn: document.getElementById("compareBtn"),
    compareError: document.getElementById("compareError"),
    resultPanel: document.getElementById("resultPanel"),
    diffStats: document.getElementById("diffStats"),
    fileSummary: document.getElementById("fileSummary"),
    diffView: document.getElementById("diffView"),
    diffEmpty: document.getElementById("diffEmpty"),
    reviewPanel: document.getElementById("reviewPanel"),
    reviewBtn: document.getElementById("reviewBtn"),
    reviewError: document.getElementById("reviewError"),
    reviewResults: document.getElementById("reviewResults"),

    toast: document.getElementById("toast"),
  };
}

/* ------------------------------- utilities ------------------------------- */
const show = (el) => el && (el.hidden = false);
const hide = (el) => el && (el.hidden = true);

function busy(btn, on) {
  if (!btn) return;
  btn.disabled = on;
  btn.classList.toggle("is-busy", on);
}

function showError(el, msg) {
  el.textContent = msg;
  el.hidden = false;
}

let toastTimer = null;
function toast(msg, isError = false) {
  els.toast.textContent = msg;
  els.toast.classList.toggle("toast--error", isError);
  els.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (els.toast.hidden = true), 3200);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function initials(name) {
  return (name || "?").trim().slice(0, 2).toUpperCase();
}

/* ------------------------------ navigation ------------------------------- */
function stageAccessible(stage) {
  if (stage === "projects") return true;
  return !!state.active; // map & review need an active project
}

function stageStatus(stage) {
  if (stage === state.view) return "active";
  if (!stageAccessible(stage)) return "locked";
  if (stage === "projects") return "done"; // reachable ⇒ a project is active
  if (stage === "map") return state.active && state.active.map_status === "built" ? "done" : "";
  if (stage === "review") return state.hasCompared ? "done" : "";
  return "";
}

function setStages() {
  els.stages.querySelectorAll(".stage").forEach((btn) => {
    const status = stageStatus(btn.dataset.stage);
    btn.classList.toggle("is-active", status === "active");
    btn.classList.toggle("is-done", status === "done");
    btn.classList.toggle("is-locked", status === "locked");
  });
}

function updateActiveChip() {
  if (state.active) {
    els.activeProjectName.textContent = state.active.name;
    show(els.activeProject);
  } else {
    hide(els.activeProject);
  }
}

function showView(view) {
  if (!stageAccessible(view)) view = "projects";
  state.view = view;

  document.querySelectorAll(".view").forEach((section) => {
    section.hidden = section.dataset.view !== view;
  });

  const meta = VIEWS[view];
  els.viewEyebrow.textContent = `STEP ${meta.step} / 3`;
  els.viewTitle.textContent = meta.title;
  els.viewSubtitle.textContent = meta.subtitle;

  setStages();
  updateActiveChip();

  if (view === "map") enterMap();
  if (view === "review") enterReview();
}

function setActive(project) {
  state.active = project;
  state.branches = null;
  state.branchesPopulated = false;
  state.hasCompared = false;
  updateActiveChip();
}

/* -------------------------------- projects ------------------------------- */
async function loadProjects() {
  try {
    state.projects = await API.listProjects();
  } catch (err) {
    state.projects = [];
    toast(`Couldn't load projects: ${err.message}`, true);
  }
  renderProjects();
}

function renderProjects() {
  els.projectCount.textContent = state.projects.length;
  els.projectList.innerHTML = "";

  if (!state.projects.length) {
    show(els.projectEmpty);
    return;
  }
  hide(els.projectEmpty);

  for (const p of state.projects) {
    els.projectList.appendChild(projectCard(p));
  }
}

function projectCard(p) {
  const built = p.map_status === "built";
  const el = document.createElement("article");
  el.className = "project";
  el.dataset.id = p.id;
  el.innerHTML = `
    <div class="project__main">
      <div class="project__name"></div>
      <div class="project__url mono"></div>
    </div>
    <div class="project__meta">
      <span class="badge ${built ? "badge--ok" : "badge--pending"}">${built ? "Map ready" : "No map"}</span>
      ${p.default_branch ? `<span class="branch-chip mono">${escapeHtml(p.default_branch)}</span>` : ""}
    </div>
    <div class="project__actions">
      <button class="btn btn--ghost" data-action="remove" type="button">Remove</button>
      <button class="btn btn--primary" data-action="open" type="button">Open →</button>
    </div>`;
  el.querySelector(".project__name").textContent = p.name;
  el.querySelector(".project__url").textContent = p.url;
  return el;
}

async function connectProject(e) {
  e.preventDefault();
  const url = els.repoUrl.value.trim();
  hide(els.connectError);
  if (!url) {
    showError(els.connectError, "Enter a repository URL to connect.");
    return;
  }

  busy(els.connectBtn, true);
  try {
    const project = await API.addProject(url);
    els.repoUrl.value = "";
    state.projects.unshift(project);
    renderProjects();
    toast(`Connected ${project.name}`);
    setActive(project);
    showView("map");
  } catch (err) {
    showError(els.connectError, err.message);
  } finally {
    busy(els.connectBtn, false);
  }
}

function onProjectListClick(e) {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const card = btn.closest(".project");
  const id = card.dataset.id;
  const project = state.projects.find((p) => p.id === id);
  if (!project) return;

  if (btn.dataset.action === "open") {
    setActive(project);
    showView("map");
  } else if (btn.dataset.action === "remove") {
    removeProject(project, btn);
  }
}

async function removeProject(project, btn) {
  if (!confirm(`Remove ${project.name}? This deletes its local clone and map.`)) return;
  busy(btn, true);
  try {
    await API.deleteProject(project.id);
    state.projects = state.projects.filter((p) => p.id !== project.id);
    if (state.active && state.active.id === project.id) {
      state.active = null;
    }
    renderProjects();
    toast(`Removed ${project.name}`);
    if (state.view !== "projects") showView("projects");
    else setStages();
  } catch (err) {
    toast(err.message, true);
    busy(btn, false);
  }
}

/* ---------------------------- context bar (2/3) -------------------------- */
function renderContextBar(container) {
  const p = state.active;
  container.innerHTML = `
    <span class="context-bar__mark"></span>
    <div class="context-bar__text" style="min-width:0">
      <div class="context-bar__name"></div>
      <div class="context-bar__url"></div>
    </div>`;
  container.querySelector(".context-bar__mark").textContent = initials(p.name);
  container.querySelector(".context-bar__name").textContent = p.name;
  container.querySelector(".context-bar__url").textContent = p.url;
}

/* ---------------------------------- map ---------------------------------- */
async function enterMap() {
  renderContextBar(els.mapContext);
  els.mapState.innerHTML = `<div class="notice"><span class="notice__glyph">…</span><span>Checking map…</span></div>`;
  try {
    const res = await API.getMap(state.active.id);
    renderMapState(res);
  } catch (err) {
    els.mapState.innerHTML = "";
    const n = document.createElement("div");
    n.className = "form-error";
    n.textContent = err.message;
    els.mapState.appendChild(n);
  }
}

function renderMapState(res) {
  els.mapState.innerHTML = "";
  const hasMap = res && res.map;

  if (!hasMap) {
    // Not built yet — offer to build.
    const notice = document.createElement("div");
    notice.className = "notice notice--info";
    notice.innerHTML = `<span class="notice__glyph">◇</span><span>No map yet. Building the map scans the repository once and records module responsibilities and architectural invariants for the reviewer to check against.</span>`;
    els.mapState.appendChild(notice);

    const actions = document.createElement("div");
    actions.className = "map-actions";
    const build = document.createElement("button");
    build.className = "btn btn--primary";
    build.type = "button";
    build.textContent = "Build map";
    build.addEventListener("click", () => buildMap(build));
    actions.appendChild(build);
    els.mapState.appendChild(actions);
    return;
  }

  const map = res.map;
  const isStub = map.status === "stub";

  const notice = document.createElement("div");
  notice.className = `notice ${isStub ? "notice--info" : "notice--ok"}`;
  notice.innerHTML = isStub
    ? `<span class="notice__glyph">◇</span><span>Map scaffold created. The generation engine isn't wired up yet, so its fields are empty — but the project is marked as mapped and you can continue to review.</span>`
    : `<span class="notice__glyph">✓</span><span>Map ready.</span>`;
  els.mapState.appendChild(notice);

  // Field summary — mirrors the target map shape (Design §7.1).
  const sections = document.createElement("div");
  sections.className = "map-sections";
  const proseLen = (map.prose || "").trim().length;
  sections.append(
    mapSection("Module prose", proseLen ? `${proseLen} chars` : dash()),
    mapSection("File roles", count(map.file_roles)),
    mapSection("Architecture", Object.keys(map.architecture || {}).length ? `${Object.keys(map.architecture).length} entries` : dash()),
    mapSection("Invariants", count(map.invariants))
  );
  els.mapState.appendChild(sections);

  // Raw JSON, collapsed.
  const raw = document.createElement("details");
  raw.className = "raw";
  const summary = document.createElement("summary");
  summary.textContent = "map.json";
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(map, null, 2);
  raw.append(summary, pre);
  els.mapState.appendChild(raw);

  // Continue to review.
  const actions = document.createElement("div");
  actions.className = "map-actions";
  const cont = document.createElement("button");
  cont.className = "btn btn--primary";
  cont.type = "button";
  cont.textContent = "Continue to review →";
  cont.addEventListener("click", () => showView("review"));
  actions.appendChild(cont);
  els.mapState.appendChild(actions);
}

function mapSection(label, value) {
  const el = document.createElement("div");
  el.className = "map-section";
  el.innerHTML = `<div class="map-section__label"></div><div class="map-section__value"></div>`;
  el.querySelector(".map-section__label").textContent = label;
  el.querySelector(".map-section__value").innerHTML = value;
  return el;
}
const dash = () => `<span class="empty-dash">—</span>`;
const count = (arr) => (Array.isArray(arr) && arr.length ? String(arr.length) : dash());

async function buildMap(btn) {
  busy(btn, true);
  try {
    const res = await API.buildMap(state.active.id);
    // Reflect the new status locally.
    state.active.map_status = "built";
    const listed = state.projects.find((p) => p.id === state.active.id);
    if (listed) listed.map_status = "built";
    toast("Map built");
    renderMapState(res);
    setStages();
    renderProjects();
  } catch (err) {
    toast(err.message, true);
    busy(btn, false);
  }
}

/* -------------------------------- review --------------------------------- */
async function enterReview() {
  renderContextBar(els.reviewContext);
  hide(els.resultPanel);
  hide(els.compareError);
  hide(els.reviewPanel);
  hide(els.reviewError);
  els.reviewResults.innerHTML = "";

  if (!state.branches) {
    els.baseSelect.innerHTML = `<option>Loading…</option>`;
    els.compareSelect.innerHTML = `<option>Loading…</option>`;
    els.compareBtn.disabled = true;
    try {
      state.branches = await API.listBranches(state.active.id);
      state.branchesPopulated = false;
    } catch (err) {
      showError(els.compareError, `Couldn't load branches: ${err.message}`);
      return;
    }
  }

  if (!state.branchesPopulated) {
    populateBranchSelects();
    state.branchesPopulated = true;
  }
}

function fillSelect(sel, branches, selected) {
  sel.innerHTML = "";
  for (const b of branches) {
    const opt = document.createElement("option");
    opt.value = b;
    opt.textContent = b;
    if (b === selected) opt.selected = true;
    sel.appendChild(opt);
  }
}

function populateBranchSelects() {
  const { branches, default_branch } = state.branches;
  if (!branches.length) {
    showError(els.compareError, "This repository has no branches to compare.");
    els.compareBtn.disabled = true;
    return;
  }
  const base =
    default_branch && branches.includes(default_branch) ? default_branch : branches[0];
  const compare = branches.find((b) => b !== base) || base;
  fillSelect(els.baseSelect, branches, base);
  fillSelect(els.compareSelect, branches, compare);
  els.compareBtn.disabled = false;
}

async function runCompare() {
  const base = els.baseSelect.value;
  const compare = els.compareSelect.value;
  hide(els.compareError);
  if (base === compare) {
    showError(els.compareError, "Choose two different branches to compare.");
    return;
  }

  busy(els.compareBtn, true);
  try {
    const result = await API.compare(state.active.id, base, compare);
    state.hasCompared = true;
    renderCompareResult(result);
    setStages();

    // Reveal the AI-review step for this comparison.
    state.lastCompare = { base, compare };
    els.reviewResults.innerHTML = "";
    els.reviewBtn.textContent = "Run AI review";
    hide(els.reviewError);
    result.changed_files.length ? show(els.reviewPanel) : hide(els.reviewPanel);
  } catch (err) {
    hide(els.resultPanel);
    hide(els.reviewPanel);
    showError(els.compareError, err.message);
  } finally {
    busy(els.compareBtn, false);
  }
}

function renderCompareResult(result) {
  show(els.resultPanel);

  // Stats
  const mb = result.merge_base ? result.merge_base.slice(0, 7) : "—";
  els.diffStats.innerHTML = `
    <div class="stat stat--meta"><span class="stat__num">${result.stats.files_changed}</span><span class="stat__label">files changed</span></div>
    <div class="stat stat--add"><span class="stat__num">+${result.stats.additions}</span><span class="stat__label">additions</span></div>
    <div class="stat stat--del"><span class="stat__num">−${result.stats.deletions}</span><span class="stat__label">deletions</span></div>
    <div class="stat stat--meta"><span class="stat__num mono">${mb}</span><span class="stat__label">merge-base</span></div>`;

  // No changes → empty state, skip the rest.
  if (!result.changed_files.length) {
    els.fileSummary.innerHTML = "";
    els.diffView.innerHTML = "";
    show(els.diffEmpty);
    return;
  }
  hide(els.diffEmpty);

  // Changed-file summary
  els.fileSummary.innerHTML = "";
  for (const f of result.changed_files) {
    els.fileSummary.appendChild(fileRow(f));
  }

  // Diff
  els.diffView.innerHTML = "";
  for (const file of parseDiffFiles(result.diff)) {
    els.diffView.appendChild(diffFileEl(file));
  }
}

function fileRow(f) {
  const row = document.createElement("div");
  row.className = "file-row";
  const path = f.old_path ? `${f.old_path} → ${f.path}` : f.path;
  const counts =
    f.additions === null && f.deletions === null
      ? `<span class="mono" style="color:var(--muted)">bin</span>`
      : `<span class="add">+${f.additions ?? 0}</span><span class="del">−${f.deletions ?? 0}</span>`;
  row.innerHTML = `
    <span class="file-status fs-${escapeHtml(f.status)}">${escapeHtml(f.status)}</span>
    <span class="file-path"></span>
    <span class="file-counts">${counts}</span>`;
  row.querySelector(".file-path").textContent = path;
  return row;
}

/* --------------------------- diff parse + render ------------------------- */
function parseDiffFiles(patch) {
  if (!patch) return [];
  const files = [];
  let cur = null;
  for (const line of patch.split("\n")) {
    if (line.startsWith("diff --git")) {
      const m = line.match(/ b\/(.+)$/);
      cur = { name: m ? m[1] : line.replace("diff --git ", ""), lines: [] };
      files.push(cur);
    } else if (cur) {
      cur.lines.push(line);
    }
  }
  return files;
}

const DIFF_SKIP = [
  "index ",
  "--- ",
  "+++ ",
  "new file mode",
  "deleted file mode",
  "old mode",
  "new mode",
  "similarity index",
  "dissimilarity index",
  "rename from",
  "rename to",
  "copy from",
  "copy to",
  "\\ ",
];

function diffFileEl(file) {
  const wrap = document.createElement("div");
  wrap.className = "diff-file";

  const head = document.createElement("div");
  head.className = "diff-file__head";
  head.textContent = file.name;
  wrap.appendChild(head);

  const body = document.createElement("div");
  body.className = "diff-body";

  let oldNo = 0;
  let newNo = 0;

  for (const line of file.lines) {
    if (line === "") continue;

    if (line.startsWith("@@")) {
      const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) {
        oldNo = parseInt(m[1], 10);
        newNo = parseInt(m[2], 10);
      }
      body.appendChild(hunkRow(line));
      continue;
    }

    if (line.startsWith("Binary files")) {
      body.appendChild(hunkRow("Binary file — not shown"));
      continue;
    }

    if (DIFF_SKIP.some((p) => line.startsWith(p))) continue;

    let cls = "";
    let g1 = "";
    let g2 = "";
    if (line.startsWith("+")) {
      cls = "diff-row--add";
      g2 = newNo++;
    } else if (line.startsWith("-")) {
      cls = "diff-row--del";
      g1 = oldNo++;
    } else {
      g1 = oldNo++;
      g2 = newNo++;
    }

    const row = document.createElement("div");
    row.className = `diff-row ${cls}`.trim();
    row.innerHTML = `<span class="diff-gutter"></span><span class="diff-gutter"></span><span class="diff-code"></span>`;
    const kids = row.children;
    kids[0].textContent = g1 === "" ? "" : g1;
    kids[1].textContent = g2 === "" ? "" : g2;
    kids[2].textContent = line;
    body.appendChild(row);
  }

  wrap.appendChild(body);
  return wrap;
}

function hunkRow(text) {
  const el = document.createElement("div");
  el.className = "diff-hunk";
  el.textContent = text;
  return el;
}

/* --------------------------------- wiring -------------------------------- */
function bindEvents() {
  els.connectForm.addEventListener("submit", connectProject);
  els.projectList.addEventListener("click", onProjectListClick);
  els.changeProjectBtn.addEventListener("click", () => showView("projects"));
  els.compareBtn.addEventListener("click", runCompare);
  els.reviewBtn.addEventListener("click", runReview);

  els.stages.addEventListener("click", (e) => {
    const btn = e.target.closest(".stage");
    if (!btn) return;
    const stage = btn.dataset.stage;
    if (stageAccessible(stage)) showView(stage);
  });
}

async function init() {
  cacheEls();
  bindEvents();
  showView("projects");
  await loadProjects();
}

document.addEventListener("DOMContentLoaded", init);

/* ========================================================================== *
 *  AI review (Design section 6 + section 9)
 *  Appended to app.js. Runs the tools -> agents pipeline via POST /review and
 *  renders the Overview + per-axis tabs. Function declarations are hoisted, so
 *  this block can live at the end of the file.
 * ========================================================================== */

const AXIS_LABEL = {
  readability: "Readability",
  structure: "Structure",
  maintainability: "Maintainability",
};

async function runReview() {
  if (!state.lastCompare) return;
  const { base, compare } = state.lastCompare;
  hide(els.reviewError);
  els.reviewResults.innerHTML = reviewLoadingHTML();
  busy(els.reviewBtn, true);
  try {
    const result = await API.review(state.active.id, base, compare);
    renderReview(result);
    els.reviewBtn.textContent = "Re-run AI review";
  } catch (err) {
    els.reviewResults.innerHTML = "";
    showError(els.reviewError, err.message);
  } finally {
    busy(els.reviewBtn, false);
  }
}

function reviewLoadingHTML() {
  return `<div class="review-loading">
      <span class="review-loading__spinner" aria-hidden="true"></span>
      <span>Running the three review agents — one model call per axis. This can take a moment.</span>
    </div>`;
}

function renderReview(result) {
  els.reviewResults.innerHTML = "";

  const tabs = [
    { id: "overview", label: "Overview", count: result.finding_count },
    ...result.axes.map((a) => ({
      id: a.axis,
      label: AXIS_LABEL[a.axis] || a.axis,
      count: a.abstained && !a.findings.length ? null : a.findings.length,
    })),
  ];

  const tabBar = document.createElement("div");
  tabBar.className = "review-tabs";
  tabBar.setAttribute("role", "tablist");

  const panelWrap = document.createElement("div");

  const panels = {
    overview: overviewPanel(result),
    ...Object.fromEntries(result.axes.map((a) => [a.axis, axisPanel(a)])),
  };

  function activate(id) {
    tabBar.querySelectorAll(".review-tab").forEach((t) =>
      t.classList.toggle("is-active", t.dataset.tab === id)
    );
    Object.entries(panels).forEach(([pid, panel]) => {
      panel.hidden = pid !== id;
    });
  }

  for (const t of tabs) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "review-tab";
    btn.dataset.tab = t.id;
    btn.setAttribute("role", "tab");
    const label = document.createElement("span");
    label.textContent = t.label;
    btn.appendChild(label);
    if (t.count !== null && t.count !== undefined) {
      const c = document.createElement("span");
      c.className = "review-tab__count";
      c.textContent = String(t.count);
      btn.appendChild(c);
    }
    btn.addEventListener("click", () => activate(t.id));
    tabBar.appendChild(btn);
  }

  els.reviewResults.appendChild(tabBar);
  for (const panel of Object.values(panels)) panelWrap.appendChild(panel);
  els.reviewResults.appendChild(panelWrap);

  activate("overview");
}

function overviewPanel(result) {
  const panel = document.createElement("section");
  panel.className = "review-panel";
  panel.dataset.tab = "overview";

  const sev = { high: 0, medium: 0, low: 0, info: 0 };
  for (const a of result.axes)
    for (const f of a.findings) sev[f.severity] = (sev[f.severity] || 0) + 1;

  const allAbstained = result.axes.every((a) => a.abstained && !a.findings.length);

  const lead = document.createElement("p");
  lead.className = "review-lead";
  lead.textContent = allAbstained
    ? "No concerns surfaced — all three agents abstained on the provided evidence."
    : `${result.finding_count} finding${result.finding_count === 1 ? "" : "s"} across ${result.axes.length} axes.`;
  panel.appendChild(lead);

  if (!allAbstained) {
    const chips = document.createElement("div");
    chips.className = "sev-summary";
    for (const level of ["high", "medium", "low", "info"]) {
      if (!sev[level]) continue;
      const chip = sevChip(level);
      chip.classList.add("sev--pill");
      chip.textContent = `${sev[level]} ${level}`;
      chips.appendChild(chip);
    }
    panel.appendChild(chips);
  }

  const grid = document.createElement("div");
  grid.className = "overview-grid";
  for (const a of result.axes) {
    const card = document.createElement("div");
    card.className = "overview-card";
    const clean = a.abstained && !a.findings.length;
    card.innerHTML = `
      <div class="overview-card__head">
        <span class="overview-card__axis"></span>
        <span class="overview-card__count ${clean ? "is-clean" : ""}"></span>
      </div>
      <div class="overview-card__summary"></div>`;
    card.querySelector(".overview-card__axis").textContent =
      AXIS_LABEL[a.axis] || a.axis;
    card.querySelector(".overview-card__count").textContent = clean
      ? "clean"
      : `${a.findings.length} finding${a.findings.length === 1 ? "" : "s"}`;
    card.querySelector(".overview-card__summary").textContent = a.summary;
    grid.appendChild(card);
  }
  panel.appendChild(grid);

  panel.appendChild(reviewMeta(result));
  return panel;
}

function axisPanel(a) {
  const panel = document.createElement("section");
  panel.className = "review-panel";
  panel.dataset.tab = a.axis;

  const summary = document.createElement("p");
  summary.className = "axis-summary";
  summary.textContent = a.summary;
  panel.appendChild(summary);

  if (a.abstained && !a.findings.length) {
    const abstain = document.createElement("div");
    abstain.className = "review-abstain";
    abstain.innerHTML = `<span class="review-abstain__glyph">✓</span><span></span>`;
    abstain.querySelector("span:last-child").textContent = `No ${AXIS_LABEL[a.axis] ? AXIS_LABEL[a.axis].toLowerCase() : a.axis} concerns found in the evidence.`;
    panel.appendChild(abstain);
  } else {
    const order = { high: 0, medium: 1, low: 2, info: 3 };
    const sorted = [...a.findings].sort(
      (x, y) => (order[x.severity] ?? 9) - (order[y.severity] ?? 9)
    );
    for (const f of sorted) panel.appendChild(findingEl(f));
  }

  panel.appendChild(reviewMeta({ total_tokens: a.total_tokens, model: a.model }));
  return panel;
}

function findingEl(f) {
  const el = document.createElement("article");
  el.className = "finding";
  el.dataset.sev = f.severity;

  const head = document.createElement("div");
  head.className = "finding__head";
  head.appendChild(sevChip(f.severity));
  const title = document.createElement("span");
  title.className = "finding__title";
  title.textContent = f.title;
  head.appendChild(title);
  el.appendChild(head);

  if (f.detail) {
    const detail = document.createElement("p");
    detail.className = "finding__detail";
    detail.textContent = f.detail;
    el.appendChild(detail);
  }

  if (f.citations && f.citations.length) {
    const cites = document.createElement("div");
    cites.className = "finding__cites";
    const label = document.createElement("span");
    label.className = "finding__cites-label";
    label.textContent = "cited";
    cites.appendChild(label);
    for (const c of f.citations) {
      const chip = document.createElement("span");
      chip.className = "cite";
      chip.textContent = c;
      cites.appendChild(chip);
    }
    el.appendChild(cites);
  }

  if (f.suggestion) {
    const sug = document.createElement("div");
    sug.className = "finding__suggestion";
    const label = document.createElement("span");
    label.className = "finding__suggestion-label";
    label.textContent = "Suggestion";
    const text = document.createElement("span");
    text.textContent = f.suggestion;
    sug.append(label, text);
    el.appendChild(sug);
  }

  return el;
}

function sevChip(severity) {
  const chip = document.createElement("span");
  chip.className = `sev sev--${severity}`;
  chip.textContent = severity;
  return chip;
}

function reviewMeta(result) {
  const meta = document.createElement("div");
  meta.className = "review-meta";
  const bits = [];
  if (result.model) bits.push(result.model);
  if (result.total_tokens) bits.push(`${result.total_tokens.toLocaleString()} tokens`);
  meta.textContent = bits.join(" · ");
  return meta;
}
