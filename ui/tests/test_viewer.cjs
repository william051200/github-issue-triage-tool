const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { createContext, runInContext } = require("node:vm");
const { parseCSV, parseIssues, githubURL, filterIssues, sortIssues } = require("../public/app.js");

const header = "Issue link,Title,Created time,Last updated time,Priority,verdict,PR";
const csv = `${header}\r\nhttps://github.com/acme/sdk/issues/7,"Unicode \u4e2d, ""quoted""\r\nsecond line",2026-10-01T10:00:00Z,2026-10-02T11:00:00Z,P0,needs-review,https://github.com/acme/sdk/pull/8;https://github.com/acme/sdk/pull/9\r\nhttps://github.com/acme/cli/issues/2,'=title,2026-10-03T00:00:00Z,2026-10-04T00:00:00Z,P2,no-action,\r\n`;

function runViewer(globals) {
  const context = createContext(globals);
  for (const [directory, filename] of [["shared", "issues.js"], ["public", "app.js"]]) {
    runInContext(readFileSync(join(__dirname, "..", directory, filename), "utf8"), context);
  }
}

test("loads exporter CSV with BOM, CRLF, quotes, multiline Unicode, and multiple PRs", () => {
  const issues = parseIssues("\uFEFF" + csv);
  assert.equal(issues.length, 2);
  assert.equal(issues[0].Title, 'Unicode \u4e2d, "quoted"\r\nsecond line');
  assert.equal(issues[0].PR.split(";").length, 2);
  assert.equal(issues[1].Title, "=title");
  assert.deepEqual(parseCSV("a,b\n\n1,2"), [["a", "b"], ["1", "2"]]);
});

test("accepts empty exports and reordered columns without a trailing newline", () => {
  assert.deepEqual(parseIssues(header), []);
  const columns = header.split(",").reverse();
  const values = ["", "no-action", "P2", "", "", "Title", "https://github.com/acme/cli/issues/2"];
  assert.equal(parseIssues(`${columns}\n${values}`)[0].Title, "Title");
});

test("rejects wrong formats, truncated records, duplicate headers, and malformed quoting", () => {
  for (const invalid of ["", "{}", `${header}\na,b`, `${header},Title`, `${header}\n"unfinished`,
    `${header}\n"a"x,b,c,d,e,f,g`, `${header}\na"b,c,d,e,f,g,h`]) {
    assert.throws(() => parseIssues(invalid));
  }
});

test("filters by title, repository, issue and PR, combined with priority and verdict", () => {
  const issues = parseIssues(csv);
  assert.equal(filterIssues(issues, " QUOTED ", "P0", "needs-review").length, 1);
  assert.equal(filterIssues(issues, "acme/cli", "", "").length, 1);
  assert.equal(filterIssues(issues, "/pull/9", "", "")[0], issues[0]);
  assert.equal(filterIssues(issues, "/issues/2", "P0", "").length, 0);
  assert.equal(filterIssues(issues, "", "", "no-action")[0], issues[1]);
  assert.deepEqual(filterIssues(issues, "", "", ""), issues);
});

test("only canonical HTTPS GitHub issue and PR URLs become links", () => {
  assert.ok(githubURL("https://github.com/acme/sdk/issues/7", "issues"));
  assert.ok(githubURL("https://github.com/acme/sdk/pull/8", "pull"));
  for (const url of ["javascript:alert(1)", "https://github.com.evil.test/acme/sdk/issues/7",
    "https://evil.test", "http://github.com/acme/sdk/issues/7",
    "https://user:pass@github.com/acme/sdk/issues/7", "https://github.com/acme/sdk/pull/7",
    "https://github.com/acme/sdk/issues/7?redirect=evil", "not a URL"]) {
    assert.equal(githubURL(url, "issues"), null, url);
  }
});

test("sorts text headers naturally in either direction without changing export order", () => {
  const issues = [
    { Title: "Issue 10", verdict: "review", PR: "https://github.com/acme/sdk/pull/10" },
    { Title: "issue 2", verdict: "awaiting", PR: "https://github.com/acme/sdk/pull/2" },
    { Title: "Issue 2", verdict: "review", PR: "" },
  ];
  assert.deepEqual(sortIssues(issues, "Title"), [issues[1], issues[2], issues[0]]);
  assert.deepEqual(sortIssues(issues, "Title", "descending"), [issues[0], issues[1], issues[2]]);
  assert.deepEqual(sortIssues(issues, "verdict"), [issues[1], issues[0], issues[2]]);
  assert.deepEqual(sortIssues(issues, "PR"), [issues[1], issues[0], issues[2]]);
  assert.deepEqual(sortIssues(issues, "PR", "descending"), [issues[0], issues[1], issues[2]]);
  assert.deepEqual(issues.map(issue => issue.Title), ["Issue 10", "issue 2", "Issue 2"]);
  assert.deepEqual(sortIssues(issues, ""), issues);
});

test("priority sort puts P0 first ascending and leaves unknown or empty priorities last", () => {
  const issues = ["P2", "P0", "P1", "", "P9"].map(Priority => ({ Priority }));
  assert.deepEqual(sortIssues(issues, "Priority").map(issue => issue.Priority), ["P0", "P1", "P2", "", "P9"]);
  assert.deepEqual(sortIssues(issues, "Priority", "descending").map(issue => issue.Priority), ["P2", "P1", "P0", "", "P9"]);
});

test("date headers sort chronologically across offsets, with missing or invalid dates last", () => {
  for (const column of ["Created time", "Last updated time"]) {
    const issues = ["2026-10-02T00:00:00Z", "2026-10-02T01:00:00+08:00", "", "invalid"]
      .map(value => ({ [column]: value }));
    assert.deepEqual(sortIssues(issues, column), [issues[1], issues[0], issues[2], issues[3]]);
    assert.deepEqual(sortIssues(issues, column, "descending"), [issues[0], issues[1], issues[2], issues[3]]);
  }
});

test("sorting composes with existing filters", () => {
  const issues = parseIssues(csv);
  const filtered = filterIssues(issues, "", "P0", "");
  assert.deepEqual(sortIssues(filtered, "Title", "descending"), [issues[0]]);
  assert.equal(issues.length, 2);
});

test("clicking the rules backdrop closes the modal, but content and padding do not", () => {
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        listeners: {},
        addEventListener(type, handler) { this.listeners[type] = handler; },
      });

      return elements.get(id);
    },
    querySelectorAll() { return []; },
  };
  const dialog = document.getElementById("rules-dialog");
  dialog.getBoundingClientRect = () => ({ left: 100, right: 700, top: 50, bottom: 650 });
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; };
  runViewer({ document });
  document.getElementById("open-rules").listeners.click();
  assert.equal(dialog.open, true);
  assert.equal(typeof dialog.listeners.click, "function", "Modal must handle backdrop clicks");

  for (const [clientX, clientY, target] of [
    [300, 200, {}], [110, 60, dialog], [100, 50, dialog], [700, 650, dialog],
  ]) {
    dialog.listeners.click({ clientX, clientY, target });
    assert.equal(dialog.open, true, "Clicks inside the modal must not close it");
  }
  for (const [clientX, clientY] of [[99, 200], [701, 200], [300, 49], [300, 651]]) {
    dialog.showModal();
    dialog.listeners.click({ clientX, clientY, target: dialog });
    assert.equal(dialog.open, false, "Clicks outside each edge must close the modal");
  }
});

function apiViewer(fetch, protocol = "http:") {
  class Element {
    constructor() {
      this.listeners = {};
      this.childNodes = [];
      this.value = "";
      this.hidden = true;
      this.disabled = true;
    }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    append(...nodes) { this.childNodes.push(...nodes); }
    replaceChildren(...nodes) { this.childNodes = nodes; }
    add(node) { this.childNodes.push(node); }
  }
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    },
    querySelectorAll() { return []; },
    createElement() { return new Element(); },
    createDocumentFragment() { return new Element(); },
  };
  runViewer({
    document, location: { protocol }, fetch, URL, Option: Element,
  });
  return id => document.getElementById(id);
}

function apiResult(overrides = {}) {
  return {
    filename: "issues.partial.csv", issues: parseIssues(csv),
    summary: {
      issue_count: 2, status: "partial", snapshot_time: "2026-10-29T00:00:00Z",
      warnings: ["Collection incomplete"],
    },
    ...overrides,
  };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test("HTTP viewer renders results with a concise incomplete-export notice", async () => {
  const calls = [];
  const element = apiViewer(async (url, options) => {
    calls.push([url, options.cache]);
    return { ok: true, json: async () => apiResult() };
  });
  await settle();
  assert.deepEqual(calls, [["/api/issues/latest", "no-store"]]);
  assert.equal(element("total-count").textContent, 2);
  assert.equal(element("p0-count").textContent, 1);
  assert.equal(element("p2-count").textContent, 1);
  assert.equal(element("result-count").textContent, "2 of 2 issues");
  assert.equal(element("error").hidden, true);
  assert.equal(element("search").disabled, false);
  assert.equal(element("file-status").textContent, "Results loaded. Export incomplete.");
});

test("complete API results hide collection diagnostics without an incomplete-export notice", async () => {
  const result = apiResult();
  result.filename = "issues.csv";
  result.summary.status = "complete";
  result.summary.warnings = ["Required CI configuration is unknown"];
  const element = apiViewer(async () => ({ ok: true, json: async () => result }));
  await settle();
  assert.equal(element("file-status").textContent, "Results loaded.");
  assert.equal(element("error").hidden, true);
});

test("API errors and invalid records leave manual CSV loading available", async () => {
  for (const response of [
    { ok: false, json: async () => ({ error: "No published exports" }) },
    { ok: true, json: async () => apiResult({ issues: [{}] }) },
    { ok: true, json: async () => apiResult({ issues: [] }) },
    { ok: true, json: async () => { throw new Error("Not JSON"); } },
  ]) {
    const element = apiViewer(async () => response);
    await settle();
    assert.equal(element("error").hidden, false);
    assert.match(element("error").textContent, /choose a CSV file instead/);
    assert.equal(element("search").disabled, true);
    await element("file-input").listeners.change({
      target: { files: [{ name: "manual.csv", text: async () => csv }] },
    });
    assert.equal(element("total-count").textContent, 2);
    assert.equal(element("file-status").textContent, "manual.csv");
    assert.equal(element("error").hidden, true);
  }
});

test("an API response or failure cannot replace a newer manual file selection", async () => {
  for (const ok of [true, false]) {
    let respond;
    const element = apiViewer(() => new Promise(resolve => { respond = resolve; }));
    await element("file-input").listeners.change({
      target: { files: [{ name: "manual.csv", text: async () => csv }] },
    });
    respond({ ok, json: async () => ok ? apiResult() : { error: "API unavailable" } });
    await settle();
    assert.equal(element("file-status").textContent, "manual.csv");
    assert.equal(element("error").hidden, true);
  }
});

test("direct local-file viewer never requests the API", () => {
  let called = false;
  apiViewer(() => { called = true; }, "file:");
  assert.equal(called, false);
});
