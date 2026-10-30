"use strict";

const { readFile } = require("node:fs/promises");
const { createServer } = require("node:http");
const { join } = require("node:path");
const { ExportNotFoundError, latestExport } = require("./exports.cjs");

const UI = join(__dirname, "..");
const ROOT = join(UI, "..");
const ASSETS = new Map([
  ["/", [join(UI, "public", "index.html"), "text/html"]],
  ["/index.html", [join(UI, "public", "index.html"), "text/html"]],
  ["/app.js", [join(UI, "public", "app.js"), "text/javascript"]],
  ["/shared/issues.js", [join(UI, "shared", "issues.js"), "text/javascript"]],
  ["/styles.css", [join(UI, "public", "styles.css"), "text/css"]],
  ["/priority-rules.yml", [join(ROOT, "priority-rules.yml"), "text/plain"]],
  ["/verdict-rules.yml", [join(ROOT, "verdict-rules.yml"), "text/plain"]],
  ["/docs/policy.md", [join(ROOT, "docs", "policy.md"), "text/plain"]],
]);

function respond(response, status, data, contentType = "application/json") {
  const body = contentType === "application/json" ? Buffer.from(JSON.stringify(data)) : data;
  response.writeHead(status, {
    "Content-Type": `${contentType}; charset=utf-8`,
    "Content-Length": body.length,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
  });
  response.end(body);
}

async function handleRequest(request, response, directories) {
  const host = request.headers.host;
  const port = request.socket.localPort;
  if (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) {
    respond(response, 403, { error: "Only local viewer requests are allowed." });
    return;
  }
  if (request.headers.origin !== undefined && request.headers.origin !== `http://${host}`) {
    respond(response, 403, { error: "Cross-origin requests are not allowed." });
    return;
  }
  if (request.method !== "GET") {
    respond(response, 501, { error: "Only GET requests are supported." });
    return;
  }
  const route = request.url.split("?")[0];
  if (route === "/api/issues/latest") {
    try {
      respond(response, 200, await latestExport(directories));
    } catch (error) {
      const missing = error instanceof ExportNotFoundError || error.code === "ENOENT";
      respond(response, missing ? 404 : 409, {
        error: missing ? "No published export or matching CSV found. Choose a CSV file."
          : "Latest export is invalid, changed, or is still being published. Check its summary and CSV.",
      });
    }
  } else if (ASSETS.has(route)) {
    const [path, contentType] = ASSETS.get(route);
    respond(response, 200, await readFile(path), contentType);
  } else {
    respond(response, 404, { error: "Not found." });
  }
}

function createViewerServer(directories) {
  return createServer((request, response) => {
    handleRequest(request, response, directories).catch(() => {
      if (!response.headersSent) respond(response, 500, { error: "Could not serve viewer." });
      else response.destroy();
    });
  });
}

module.exports = { createViewerServer };
