"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const { createHash } = require("node:crypto");
const { once } = require("node:events");
const { access, mkdtemp, mkdir, readFile, rm, unlink, writeFile } = require("node:fs/promises");
const { request } = require("node:http");
const { tmpdir } = require("node:os");
const { dirname, join, resolve } = require("node:path");
const { fileURLToPath, pathToFileURL } = require("node:url");
const { ExportNotFoundError, findLatestExport, readExport, latestExport } = require("../server/exports.cjs");
const { createViewerServer } = require("../server/http.cjs");
const { parseOptions, resolveDirectories } = require("../server/cli.cjs");
const { COLUMNS } = require("../shared/issues.js");

const ROOT = resolve(__dirname, "..");
const sha256 = data => createHash("sha256").update(data).digest("hex");

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), "triage-viewer-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

async function publish(root, {
  folder = "run", snapshot = "2026-10-29T01:00:00Z", partial = false, empty = false,
} = {}) {
  const directory = join(root, folder);
  await mkdir(directory, { recursive: true });
  const marker = partial ? ".partial" : "";
  const records = [COLUMNS];
  if (!empty) records.push([
    "https://github.com/acme/sdk/issues/7", "'=Unicode \u4e2d,\r\n\"quoted\"",
    "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z", "P1",
    partial ? "data-incomplete" : "triage-needed", "",
  ]);
  const data = Buffer.from("\uFEFF" + records.map(row =>
    row.map(value => `"${value.replaceAll('"', '""')}"`).join(",")
  ).join("\r\n") + "\r\n");
  const csvPath = join(directory, `issues${marker}.csv`);
  const summaryPath = join(directory, `run-summary${marker}.json`);
  const summary = {
    snapshot_time: snapshot, status: partial ? "partial" : "complete",
    issue_count: records.length - 1, priority_counts: { P0: 0, P1: records.length - 1, P2: 0 },
    warnings: partial ? ["Collection incomplete"] : [],
    failures: partial ? ["acme/sdk"] : [],
    output_paths: { csv: csvPath },
    artifact_sha256: { csv: sha256(data) },
  };
  await writeFile(csvPath, data);
  await writeFile(summaryPath, JSON.stringify(summary));
  return { csvPath, summaryPath, summary, data };
}

test("selects newest UTC snapshot including partial runs across multiple roots", async t => {
  const directory = await temporaryDirectory(t);
  await publish(directory, { folder: "first/older", snapshot: "2026-10-29T08:30:00+08:00" });
  await publish(directory, { folder: "second/newer", partial: true });
  const result = await latestExport([join(directory, "first"), join(directory, "second")]);
  assert.equal(result.filename, "issues.partial.csv");
  assert.equal(result.summary.status, "partial");
  assert.deepEqual(result.summary.warnings, ["Collection incomplete"]);
  assert.equal(result.issues[0].Title, "'=Unicode \u4e2d,\r\n\"quoted\"");
  assert.equal(result.summary.issue_count, 1);
  assert.equal(Object.hasOwn(result.summary, "output_paths"), false);
});

test("snapshot selection retains collector microseconds rather than filesystem or path order", async t => {
  const directory = await temporaryDirectory(t);
  await publish(directory, { folder: "a-newer", snapshot: "2026-10-29T01:00:00.000002Z", partial: true });
  await publish(directory, { folder: "z-older", snapshot: "2026-10-29T09:00:00.000001+08:00" });
  assert.equal((await latestExport([directory])).filename, "issues.partial.csv");
});

test("ignores staging files, orphan CSVs and absent roots", async t => {
  const directory = await temporaryDirectory(t);
  await publish(directory, { folder: "run/.triage-stage-abcd", snapshot: "2030-01-01T00:00:00Z" });
  await mkdir(join(directory, "orphan"));
  await writeFile(join(directory, "orphan", "issues.csv"), "unpublished");
  await assert.rejects(latestExport([directory, join(directory, "absent")]), ExportNotFoundError);
  await publish(directory, { folder: "published" });
  assert.equal((await latestExport([directory])).summary.issue_count, 1);
});

test("relocated exports read matching siblings, never a saved external absolute path", async t => {
  const directory = await temporaryDirectory(t);
  const { summary, summaryPath } = await publish(directory);
  for (const savedPath of [join(directory, "old-checkout", "issues.csv"), join(directory, "outside.csv")]) {
    summary.output_paths.csv = savedPath;
    await writeFile(summaryPath, JSON.stringify(summary));
    assert.equal((await latestExport([directory])).filename, "issues.csv");
  }
});

test("rejects hashes, counts, status and malformed snapshots without serving mixed data", async t => {
  const directory = await temporaryDirectory(t);
  const { summary, summaryPath } = await publish(directory);
  for (const change of [
    { issue_count: 2 }, { status: "partial" }, { artifact_sha256: { csv: "incorrect" } },
    { snapshot_time: "2026-10-29T01:00:00" }, { snapshot_time: "2026-02-30T01:00:00Z" },
  ]) {
    await writeFile(summaryPath, JSON.stringify({ ...summary, ...change }));
    await assert.rejects(latestExport([directory]));
  }
});

test("rejects malformed, truncated and invalid UTF-8 CSV even with a matching hash", async t => {
  const directory = await temporaryDirectory(t);
  const { csvPath, summary, summaryPath } = await publish(directory);
  for (const data of [
    Buffer.from("wrong,columns\n1,2\n"),
    Buffer.from(`${COLUMNS.join(",")}\na,b\n`),
    Buffer.from(`${COLUMNS.join(",")}\n"unfinished`),
    Buffer.concat([Buffer.from(`${COLUMNS.join(",")}\n`), Buffer.from([0xff])]),
  ]) {
    await writeFile(csvPath, data);
    await writeFile(summaryPath, JSON.stringify({ ...summary, artifact_sha256: { csv: sha256(data) } }));
    await assert.rejects(latestExport([directory]));
  }
});

test("newest missing or publishing export never falls back to older data", async t => {
  const directory = await temporaryDirectory(t);
  await publish(directory, { folder: "older", snapshot: "2026-10-28T00:00:00Z" });
  const { csvPath } = await publish(directory, { folder: "newer" });
  const lock = join(dirname(csvPath), ".triage.lock");
  await writeFile(lock, "");
  await assert.rejects(latestExport([directory]), /being published/);
  await unlink(lock);
  await unlink(csvPath);
  await assert.rejects(latestExport([directory]), { code: "ENOENT" });
});

test("data reader detects changed summaries between discovery and reading", async t => {
  const directory = await temporaryDirectory(t);
  const { summaryPath, summary } = await publish(directory);
  const candidate = await findLatestExport([directory]);
  await writeFile(summaryPath, JSON.stringify({ ...summary, warnings: ["changed"] }));
  await assert.rejects(readExport(candidate), /changed while being read/);
});

test("empty published exports remain valid", async t => {
  const directory = await temporaryDirectory(t);
  await publish(directory, { empty: true });
  const result = await latestExport([directory]);
  assert.deepEqual(result.issues, []);
  assert.equal(result.summary.issue_count, 0);
});

async function startServer(t, directories) {
  const server = createViewerServer(directories);
  t.after(() => new Promise(resolve => server.close(resolve)));
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return (path, headers = {}, method = "GET") => new Promise((resolve, reject) => {
    const outgoing = request({
      host: "127.0.0.1", port: server.address().port, path, headers, method,
    }, response => {
      const chunks = [];
      response.on("data", chunk => chunks.push(chunk));
      response.on("end", () => resolve({
        status: response.statusCode, headers: response.headers,
        body: Buffer.concat(chunks).toString("utf8"), port: server.address().port,
      }));
      response.on("error", reject);
    });
    outgoing.on("error", reject);
    outgoing.end();
  });
}

test("HTTP serves only allowlisted assets and compatible latest-export payload", async t => {
  const directory = await temporaryDirectory(t);
  await publish(directory, { partial: true });
  const get = await startServer(t, [directory]);
  const result = await get("/api/issues/latest");
  assert.equal(result.status, 200);
  assert.deepEqual(JSON.parse(result.body), await latestExport([directory]));
  assert.equal(result.headers["cache-control"], "no-store");
  assert.equal(result.headers["access-control-allow-origin"], undefined);
  for (const path of [
    "/", "/index.html", "/app.js", "/shared/issues.js", "/styles.css",
    "/priority-rules.yml", "/verdict-rules.yml", "/docs/policy.md",
  ]) {
    assert.equal((await get(path)).status, 200, path);
  }
  const html = (await get("/")).body;
  assert.ok(html.indexOf("../shared/issues.js") < html.indexOf('"app.js"'));
  for (const path of ["/defaults.yml", "/output/run/issues.partial.csv", "/../defaults.yml", "/server/exports.cjs"]) {
    assert.equal((await get(path)).status, 404, path);
  }
});

test("HTTP rejects foreign hosts, cross-origin requests and writes", async t => {
  const directory = await temporaryDirectory(t);
  await publish(directory);
  const get = await startServer(t, [directory]);
  const { port } = await get("/");
  assert.equal((await get("/api/issues/latest", { Host: "evil.example" })).status, 403);
  for (const Origin of ["https://evil.example", "null"]) {
    assert.equal((await get("/api/issues/latest", { Origin })).status, 403);
  }
  assert.equal((await get("/api/issues/latest", { Origin: `http://127.0.0.1:${port}` })).status, 200);
  assert.equal((await get("/api/issues/latest", { Host: `localhost:${port}` })).status, 200);
  assert.equal((await get("/api/issues/latest", {}, "POST")).status, 501);
});

test("HTTP returns 404 for absent results and 409 for invalid results", async t => {
  const directory = await temporaryDirectory(t);
  const get = await startServer(t, [directory]);
  assert.equal((await get("/api/issues/latest")).status, 404);
  const { csvPath } = await publish(directory);
  await writeFile(csvPath, "corrupted");
  assert.equal((await get("/api/issues/latest")).status, 409);
  await unlink(csvPath);
  assert.equal((await get("/api/issues/latest")).status, 404);
});

test("viewer directories respect local YAML, example fallback and explicit overrides", async t => {
  const root = await temporaryDirectory(t);
  const cwd = join(root, "working");
  await writeFile(join(root, "defaults.example.yml"), 'output_dir: "example exports"\n');
  assert.deepEqual(await resolveDirectories(undefined, root, cwd), [
    join(root, "output"), join(cwd, "example exports"),
  ]);
  await writeFile(join(root, "defaults.yml"), 'output_dir: "custom # exports"\n');
  assert.deepEqual(await resolveDirectories(undefined, root, cwd), [
    join(root, "output"), join(cwd, "custom # exports"),
  ]);
  await writeFile(join(root, "defaults.yml"), "output_dir: [invalid]\n");
  assert.deepEqual(await resolveDirectories("chosen", root, cwd), [join(cwd, "chosen")]);
  await assert.rejects(resolveDirectories(undefined, root, cwd), /nonempty path string/);
  await writeFile(join(root, "defaults.yml"), "output_dir: first\noutput_dir: second\n");
  await assert.rejects(resolveDirectories(undefined, root, cwd), /Invalid defaults YAML/);
});

test("npm prefix keeps relative export paths anchored to the caller directory", async t => {
  const directory = await temporaryDirectory(t);
  const previous = process.env.INIT_CWD;
  process.env.INIT_CWD = directory;
  try {
    assert.deepEqual(await resolveDirectories("chosen"), [join(directory, "chosen")]);
  } finally {
    if (previous === undefined) delete process.env.INIT_CWD;
    else process.env.INIT_CWD = previous;
  }
});

test("standalone viewer scripts, styles and rule references resolve after relocation", async () => {
  const page = join(ROOT, "public", "index.html");
  const html = await readFile(page, "utf8");
  for (const [, reference] of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
    await access(fileURLToPath(new URL(reference, pathToFileURL(page))));
  }
});

test("CLI flags retain port, directory and open behavior with actionable errors", () => {
  assert.deepEqual(parseOptions(["--port", "8001", "--output-dir", "saved results", "--open"]), {
    port: 8001, outputDir: "saved results", open: true, help: false,
  });
  for (const args of [["--port", "-1"], ["--port", "65536"], ["--port", "NaN"], ["--output-dir", ""], ["--unknown"]]) {
    assert.throws(() => parseOptions(args));
  }
  const command = join(ROOT, "server", "cli.cjs");
  const help = spawnSync(process.execPath, [command, "--help"], { encoding: "utf8", timeout: 5000 });
  assert.equal(help.status, 0);
  assert.match(help.stdout, /never collect issues/);
  const invalid = spawnSync(process.execPath, [command, "--port", "invalid"], { encoding: "utf8", timeout: 5000 });
  assert.equal(invalid.status, 2);
  assert.match(invalid.stderr, /Port must be an integer/);
});
