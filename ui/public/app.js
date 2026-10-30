"use strict";

const { COLUMNS, parseCSV, parseIssues, normalizeIssues } =
  typeof module !== "undefined" && module.exports ? require("../shared/issues.js") : globalThis.TriageIssues;

function githubURL(value, kind) {
  try {
    const url = new URL(value);
    const path = new RegExp(`^/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/${kind}/[1-9][0-9]*/?$`);
    if (url.protocol === "https:" && url.hostname === "github.com" &&
        !url.username && !url.password && !url.port && !url.search && !url.hash &&
        path.test(url.pathname)) return url;
  } catch {
    // Untrusted or malformed CSV links remain plain text.
  }
  return null;
}

function filterIssues(issues, search, priority, verdict) {
  const query = search.trim().toLowerCase();
  return issues.filter(issue =>
    (!priority || issue.Priority === priority) &&
    (!verdict || issue.verdict === verdict) &&
    (!query || COLUMNS.some(column => issue[column].toLowerCase().includes(query)))
  );
}

function sortIssues(issues, column, direction = "ascending") {
  const sorted = [...issues];
  if (!column) return sorted;
  const isDate = column === "Created time" || column === "Last updated time";
  function value(issue) {
    const raw = issue[column];
    if (!raw.trim()) return null;
    if (isDate) {
      const timestamp = Date.parse(raw);
      return Number.isNaN(timestamp) ? null : timestamp;
    }
    if (column === "Priority") return ["P0", "P1", "P2"].includes(raw) ? Number(raw[1]) : null;
    return raw;
  }
  return sorted.sort((left, right) => {
    const a = value(left);
    const b = value(right);
    if (a === null) return b === null ? 0 : 1;
    if (b === null) return -1;
    const comparison = typeof a === "number" ? a - b
      : a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
    return direction === "descending" ? -comparison : comparison;
  });
}

function startViewer() {
  const elements = Object.fromEntries([
    "file-input", "file-status", "error", "total-count", "p0-count", "p1-count",
    "p2-count", "search", "priority", "verdict", "clear-filters", "result-count",
    "issue-rows", "empty-state",
  ].map(id => [id, document.getElementById(id)]));
  let issues = [];
  let loaded = false;
  let selection = 0;
  let sortColumn = "";
  let sortDirection = "ascending";
  const sortButtons = [...document.querySelectorAll("button[data-sort]")];

  function updateSortHeaders() {
    for (const button of sortButtons) {
      const active = button.dataset.sort === sortColumn;
      button.closest("th").setAttribute("aria-sort", active ? sortDirection : "none");
      const next = active && sortDirection === "ascending" ? "descending" : "ascending";
      button.setAttribute("aria-label", `${button.textContent}, sort ${next}`);
    }
  }

  function link(value, kind, label, className) {
    const url = githubURL(value, kind);
    const node = document.createElement(url ? "a" : "span");
    node.textContent = label;
    node.className = className;
    if (url) {
      node.href = url.href;
      node.target = "_blank";
      node.rel = "noopener noreferrer";
    }
    return node;
  }

  function reference(value, kind) {
    const url = githubURL(value, kind);
    if (!url) return value;
    const [, owner, repo, , number] = url.pathname.split("/");
    return `${owner}/${repo}#${number}`;
  }

  function dateCell(value) {
    const cell = document.createElement("td");
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime())) {
      cell.textContent = value || "-";
    } else {
      const time = document.createElement("time");
      time.dateTime = date.toISOString();
      time.textContent = date.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, "");
      cell.append(time);
    }
    return cell;
  }

  function render() {
    const visible = sortIssues(
      filterIssues(issues, elements.search.value, elements.priority.value, elements.verdict.value),
      sortColumn, sortDirection,
    );
    const fragment = document.createDocumentFragment();
    for (const issue of visible) {
      const row = document.createElement("tr");
      const title = document.createElement("td");
      title.append(
        link(issue["Issue link"], "issues", issue.Title || "(Untitled issue)", "issue-title"),
        link(issue["Issue link"], "issues", reference(issue["Issue link"], "issues"), "issue-reference"),
      );
      const priority = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `badge ${["P0", "P1", "P2"].includes(issue.Priority) ? issue.Priority.toLowerCase() : ""}`;
      badge.textContent = issue.Priority || "-";
      priority.append(badge);
      const verdict = document.createElement("td");
      verdict.textContent = issue.verdict || "-";
      const prs = document.createElement("td");
      for (const value of issue.PR.split(";").map(value => value.trim()).filter(Boolean)) {
        prs.append(link(value, "pull", reference(value, "pull"), "pr-link"));
      }
      if (!prs.childNodes.length) prs.textContent = "-";
      row.append(title, priority, verdict, dateCell(issue["Created time"]), dateCell(issue["Last updated time"]), prs);
      fragment.append(row);
    }
    elements["issue-rows"].replaceChildren(fragment);
    elements["result-count"].textContent = `${visible.length} of ${issues.length} issues`;
    elements["empty-state"].hidden = visible.length > 0;
    elements["empty-state"].textContent = !loaded ? "Choose a CSV file."
      : issues.length ? "No matching issues." : "No issues in this export.";
  }

  function clearFilters() {
    elements.search.value = "";
    elements.priority.value = "";
    elements.verdict.value = "";
    render();
  }

  function showIssues(nextIssues, status) {
    issues = nextIssues;
    loaded = true;
    sortColumn = "";
    sortDirection = "ascending";
    for (const button of sortButtons) button.disabled = false;
    updateSortHeaders();
    const verdicts = [...new Set(issues.map(issue => issue.verdict).filter(Boolean))].sort();
    elements.verdict.replaceChildren(new Option("All verdicts", ""));
    for (const verdict of verdicts) elements.verdict.add(new Option(verdict, verdict));
    for (const id of ["search", "priority", "verdict", "clear-filters"]) elements[id].disabled = false;
    elements["total-count"].textContent = issues.length;
    for (const priority of ["P0", "P1", "P2"]) {
      elements[`${priority.toLowerCase()}-count`].textContent = issues.filter(issue => issue.Priority === priority).length;
    }
    elements["file-status"].textContent = status;
    clearFilters();
  }

  elements["file-input"].addEventListener("change", async event => {
    const file = event.target.files[0];
    if (!file) return;
    const currentSelection = ++selection;
    elements.error.hidden = true;
    elements["file-status"].textContent = `Reading ${file.name}...`;
    try {
      const nextIssues = parseIssues(await file.text());
      if (currentSelection !== selection) return;
      showIssues(nextIssues, `${file.name}${
        file.name.includes(".partial.") ? " | Partial export: results may be incomplete" : ""
      }`);
    } catch (error) {
      if (currentSelection !== selection) return;
      elements.error.textContent = `Could not load ${file.name}: ${error.message}`;
      elements.error.hidden = false;
      elements["file-status"].textContent = loaded ? "Showing previous results." : "No file loaded.";
    } finally {
      if (currentSelection === selection) elements["file-input"].value = "";
    }
  });
  elements.search.addEventListener("input", render);
  elements.priority.addEventListener("change", render);
  elements.verdict.addEventListener("change", render);
  elements["clear-filters"].addEventListener("click", clearFilters);
  for (const button of sortButtons) {
    button.addEventListener("click", () => {
      sortDirection = sortColumn === button.dataset.sort && sortDirection === "ascending"
        ? "descending" : "ascending";
      sortColumn = button.dataset.sort;
      updateSortHeaders();
      render();
    });
  }
  updateSortHeaders();
  const rulesDialog = document.getElementById("rules-dialog");
  document.getElementById("open-rules").addEventListener("click", () => {
    rulesDialog.showModal();
  });
  rulesDialog.addEventListener("click", event => {
    if (event.target !== rulesDialog) return;
    const bounds = rulesDialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom) {
      rulesDialog.close();
    }
  });

  async function loadLatest() {
    const currentSelection = ++selection;
    elements["file-status"].textContent = "Loading latest saved export...";
    try {
      const response = await fetch("/api/issues/latest", { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      const nextIssues = normalizeIssues(result.issues);
      if (nextIssues.length !== result.summary.issue_count) throw new Error("Export issue count does not match.");
      if (currentSelection !== selection) return;
      showIssues(nextIssues, result.summary.status === "partial"
        ? "Results loaded. Export incomplete." : "Results loaded.");
      elements.error.hidden = true;
    } catch (error) {
      if (currentSelection !== selection) return;
      elements.error.textContent = `Could not load latest export: ${error.message} You can choose a CSV file instead.`;
      elements.error.hidden = false;
      elements["file-status"].textContent = "No file loaded.";
    }
  }
  if (typeof location !== "undefined" && ["http:", "https:"].includes(location.protocol)) {
    loadLatest();
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { parseCSV, parseIssues, normalizeIssues, githubURL, filterIssues, sortIssues };
} else {
  startViewer();
}
