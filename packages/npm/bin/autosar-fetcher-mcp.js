#!/usr/bin/env node
// Robust launcher: prefers pip-installed `autosar-fetcher-mcp`,
// falls back to the Python file bundled next to this repo.
const { spawnSync, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const python = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");

function repoScript() {
  // packages/npm/bin -> repo root
  const p = path.resolve(__dirname, "..", "..", "..", "autosar_mcp_server.py");
  return fs.existsSync(p) ? p : null;
}

function pipHasModule() {
  try {
    const r = spawnSync(python, ["-c", "import autosar_mcp_server"], { stdio: "ignore" });
    return r.status === 0;
  } catch {
    return false;
  }
}

let child;
if (pipHasModule()) {
  child = spawn(python, ["-m", "autosar_mcp_server", ...process.argv.slice(2)], { stdio: "inherit" });
} else {
  const script = repoScript();
  if (!script) {
    console.error("autosar_mcp_server.py not found. Install the pip package first: pip install autosar-standards-fetcher");
    process.exit(1);
  }
  const py = process.platform === "win32" && python === "python" ? "py" : python;
  const args = py === "py" ? ["-3", script, ...process.argv.slice(2)] : [script, ...process.argv.slice(2)];
  child = spawn(py, args, { stdio: "inherit" });
}
child.on("exit", (code) => process.exit(code || 0));
