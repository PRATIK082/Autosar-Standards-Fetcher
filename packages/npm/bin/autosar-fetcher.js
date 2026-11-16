#!/usr/bin/env node
const { spawn } = require("child_process");
const path = require("path");

const python = process.env.PYTHON || "python";
const script = path.resolve(__dirname, "..", "..", "..", "download_autosar_standards.py");
const child = spawn(python, [script, ...process.argv.slice(2)], { stdio: "inherit" });
child.on("exit", (code) => process.exit(code || 0));