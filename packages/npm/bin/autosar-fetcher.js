#!/usr/bin/env node
// Robust launcher for the classic bulk-download CLI.
const { spawnSync, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const python = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");

function repoScript() {
  const p = path.resolve(__dirname, "..", "..", "..", "download_autosar_standards.py");
  return fs.existsSync(p) ? p : null;
}

function pipHasModule() {
  try {
    const r = spawnSync(python, ["-c", "import download_autosar_standards"], { stdio: "ignore" });
    return r.status === 0;
  } catch {
    return false;
  }
}

let child;
if (pipHasModule()) {
  child = spawn(python, ["-m", "download_autosar_standards", ...process.argv.slice(2)], { stdio: "inherit" });
} else {
  const script = repoScript();
  if (!script) {
    console.error("download_autosar_standards.py not found. Install the pip package first: pip install autosar-standards-fetcher");
    process.exit(1);
  }
  const py = process.platform === "win32" && python === "python" ? "py" : python;
  const args = py === "py" ? ["-3", script, ...process.argv.slice(2)] : [script, ...process.argv.slice(2)];
  child = spawn(py, args, { stdio: "inherit" });
}
child.on("exit", (code) => process.exit(code || 0));
