"use strict";

const { createHash } = require("node:crypto");
const { readdir, readFile, realpath, stat } = require("node:fs/promises");
const { dirname, isAbsolute, join, relative, resolve, sep } = require("node:path");
const { TextDecoder } = require("node:util");
const { parseIssueRecords, REVIEW_COLUMNS, REVIEW_FIELDS } = require("../shared/issues.js");

class ExportNotFoundError extends Error {}

function isWithin(directory, path) {
  const child = relative(directory, path);
  return child !== ".." && !child.startsWith(`..${sep}`) && !isAbsolute(child);
}

function snapshotTime(value) {
  const match = typeof value === "string" &&
    /^(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}(?:\.(\d+))?(?:Z|[+-]\d{2}:\d{2})$/.exec(value);
  const milliseconds = Date.parse(value);
  if (!match || !Number.isFinite(milliseconds) ||
      new Date(`${match[1]}T00:00:00Z`).toISOString().slice(0, 10) !== match[1]) {
    throw new Error("Snapshot must be a timezone-aware ISO timestamp.");
  }
  // Date alone loses the microseconds published by the Python collector.
  return BigInt(Math.floor(milliseconds / 1000)) * 1000000n +
    BigInt((match[2] || "").slice(0, 6).padEnd(6, "0"));
}

async function* summaryPaths(directory) {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return;
    throw error;
  }
  for (const entry of entries) {
    if (entry.name.startsWith(".triage-stage-")) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      yield* summaryPaths(path);
    } else if (entry.name === "run-summary.json" || entry.name === "run-summary.partial.json") {
      yield path;
    }
  }
}

async function findLatestExport(directories) {
  let latest;
  for (const directory of new Set(directories.map(path => resolve(path)))) {
    let root;
    try {
      root = await realpath(directory);
    } catch (error) {
      if (error.code === "ENOENT") continue;
      throw error;
    }
    for await (const candidate of summaryPaths(root)) {
      const path = await realpath(candidate);
      if (!isWithin(root, path)) continue;
      const contents = await readFile(path);
      const summary = JSON.parse(contents.toString("utf8"));
      const snapshot = snapshotTime(summary.snapshot_time);
      if (!latest || snapshot > latest.snapshot || (snapshot === latest.snapshot && path > latest.path)) {
        latest = { path, contents, summary, snapshot };
      }
    }
  }
  if (!latest) throw new ExportNotFoundError("No published exports found.");
  return latest;
}

async function isPublishing(directory) {
  try {
    await stat(join(directory, ".triage.lock"));
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

async function readReview(directory, issues, snapshot) {
  let path;
  try {
    path = await realpath(join(directory, "review-summary.json"));
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
  if (dirname(path) !== directory) throw new Error("Review summary must remain inside its export directory.");
  const contents = await readFile(path);
  const summary = JSON.parse(contents.toString("utf8"));
  if (summary.status !== "complete" || snapshotTime(summary.snapshot_time) < snapshotTime(snapshot)) {
    throw new Error("Review is incomplete or predates the collection.");
  }
  const filename = "issue-review.csv";
  const csvPath = await realpath(join(directory, filename));
  if (dirname(csvPath) !== directory) throw new Error("Review CSV must remain inside its export directory.");
  const data = await readFile(csvPath);
  if (createHash("sha256").update(data).digest("hex") !== summary.artifact_sha256?.csv) {
    throw new Error("Review CSV hash does not match its summary.");
  }
  const records = parseIssueRecords(new TextDecoder("utf-8", { fatal: true }).decode(data));
  const reviewed = new Map(records.map(record => [record["Issue link"], record]));
  if (records.length !== summary.issue_count || reviewed.size !== records.length ||
      records.length !== issues.length || issues.some(issue => !reviewed.has(issue["Issue link"])) ||
      records.some(record => REVIEW_COLUMNS.some(column => typeof record[column] !== "string"))) {
    throw new Error("Review must cover the collection's issues exactly once.");
  }
  if (!(await readFile(path)).equals(contents)) throw new Error("Review changed while being read.");
  return {
    issues: issues.map(issue => ({
      ...issue,
      ...Object.fromEntries(REVIEW_FIELDS.filter(field => Object.hasOwn(reviewed.get(issue["Issue link"]), field))
        .map(field => [field, reviewed.get(issue["Issue link"])[field]])),
    })),
    summary: { filename, snapshot_time: summary.snapshot_time, issue_count: records.length },
  };
}

async function readExport({ path, contents, summary }) {
  const directory = dirname(path);
  const partial = path.endsWith("run-summary.partial.json");
  if (summary.status !== (partial ? "partial" : "complete")) {
    throw new Error("Export status does not match its summary filename.");
  }
  if (await isPublishing(directory)) throw new Error("Export is being published.");
  const filename = partial ? "issues.partial.csv" : "issues.csv";
  // Read only siblings, even when output_paths contains stale or external absolute paths.
  const csvPath = await realpath(join(directory, filename));
  if (dirname(csvPath) !== directory) throw new Error("CSV must remain inside its published export directory.");
  const data = await readFile(csvPath);
  if (createHash("sha256").update(data).digest("hex") !== summary.artifact_sha256?.csv) {
    throw new Error("CSV hash does not match the published summary.");
  }
  const issues = parseIssueRecords(new TextDecoder("utf-8", { fatal: true }).decode(data));
  if (issues.length !== summary.issue_count) throw new Error("CSV issue count does not match the published summary.");
  const review = await readReview(directory, issues, summary.snapshot_time);
  if (!(await readFile(path)).equals(contents) || await isPublishing(directory)) {
    throw new Error("Export changed while being read.");
  }
  const keys = [
    "status", "snapshot_time", "issue_count", "priority_counts",
    "date_range", "parameters", "warnings", "failures",
  ];
  return {
    filename, issues: review ? review.issues : issues,
    summary: {
      ...Object.fromEntries(keys.filter(key => Object.hasOwn(summary, key)).map(key => [key, summary[key]])),
      ...(review ? { review: review.summary } : {}),
    },
  };
}

async function latestExport(directories) {
  return readExport(await findLatestExport(directories));
}

module.exports = { ExportNotFoundError, findLatestExport, readExport, latestExport };
