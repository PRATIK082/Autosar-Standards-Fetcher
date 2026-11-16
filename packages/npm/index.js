"""Node entry-point for autosar-standards-fetcher.

JS agents can `require('autosar-standards-fetcher')` to get the MCP
server configuration helpers without spawning anything.
"""
const path = require("path");

function mcpConfig(python = process.env.PYTHON || "python", outputDir) {
  const args = [path.join(__dirname, "bin", "autosar-fetcher-mcp.js")];
  if (outputDir) args.push("--output-dir", outputDir);
  return { command: "node", args, env: { ...process.env, PYTHON: python } };
}

function pythonMcpConfig(python = process.env.PYTHON || "python", outputDir) {
  const args = ["-m", "autosar_mcp_server"];
  if (outputDir) args.push("--output-dir", outputDir);
  return { command: python, args };
}

module.exports = { mcpConfig, pythonMcpConfig };
