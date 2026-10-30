"use strict";

const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { readFile } = require("node:fs/promises");
const { join, resolve } = require("node:path");
const { parseArgs } = require("node:util");
const { parseDocument } = require("yaml");
const { createViewerServer } = require("./http.cjs");

const ROOT = resolve(__dirname, "..", "..");
const HELP = `Usage: node ui\\server\\cli.cjs [--port 8000] [--output-dir path] [--open]

Serve the triage viewer and saved results on loopback; never collect issues.

  --port         Local port (default: 8000)
  --output-dir   Scan this export directory instead of defaults
  --open         Open the viewer in the default browser
  -h, --help     Show this help
`;

function parseOptions(args) {
  const { values } = parseArgs({
    args,
    options: {
      port: { type: "string", default: "8000" },
      "output-dir": { type: "string" },
      open: { type: "boolean", default: false },
      help: { type: "boolean", short: "h", default: false },
    },
  });
  if (!/^\d+$/.test(values.port) || Number(values.port) > 65535) {
    throw new Error("Port must be an integer from 0 to 65535.");
  }
  if (values["output-dir"] !== undefined && !values["output-dir"].trim()) {
    throw new Error("Output directory must not be empty.");
  }
  return { port: Number(values.port), outputDir: values["output-dir"], open: values.open, help: values.help };
}

async function resolveDirectories(outputDir, root = ROOT, cwd = process.env.INIT_CWD || process.cwd()) {
  if (outputDir !== undefined) return [resolve(cwd, outputDir)];
  let contents;
  try {
    contents = await readFile(join(root, "defaults.yml"), "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    contents = await readFile(join(root, "defaults.example.yml"), "utf8");
  }
  const document = parseDocument(contents, { uniqueKeys: true });
  if (document.errors.length) throw new Error(`Invalid defaults YAML: ${document.errors[0].message}`);
  const defaults = document.toJS();
  if (typeof defaults?.output_dir !== "string" || !defaults.output_dir.trim()) {
    throw new Error("Defaults output_dir must be a nonempty path string.");
  }
  return [...new Set([resolve(root, "output"), resolve(cwd, defaults.output_dir)])];
}

function openBrowser(url) {
  const [command, args] = process.platform === "win32" ? ["rundll32.exe", ["url.dll,FileProtocolHandler", url]]
    : process.platform === "darwin" ? ["open", [url]] : ["xdg-open", [url]];
  const child = spawn(command, args, { stdio: "ignore" });
  child.on("error", error => console.error(`Could not open browser: ${error.message}. Open ${url} manually.`));
}

async function main(args = process.argv.slice(2)) {
  const options = parseOptions(args);
  if (options.help) {
    console.log(HELP);
    return;
  }
  const directories = await resolveDirectories(options.outputDir);
  const server = createViewerServer(directories);
  server.listen(options.port, "127.0.0.1");
  await once(server, "listening");
  const url = `http://127.0.0.1:${server.address().port}/`;
  console.log(`Viewer: ${url}\nReading saved exports only. Press Ctrl+C to stop.`);
  for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => server.close());
  if (options.open) openBrowser(url);
  return server;
}

if (require.main === module) {
  main().catch(error => {
    console.error(`Cannot start viewer: ${error.message}`);
    process.exitCode = 2;
  });
}

module.exports = { parseOptions, resolveDirectories, main };
