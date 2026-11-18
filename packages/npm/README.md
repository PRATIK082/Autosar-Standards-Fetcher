# autosar-standards-fetcher (npm wrapper)

Node wrapper around the Python AUTOSAR Standards Fetcher.
Requires Python 3.10+ on PATH.

```bash
# 1. Install the Python package (ships the real logic + MCP server)
pip install autosar-standards-fetcher

# 2. Install this wrapper (local or global)
npm install autosar-standards-fetcher
# or: npm install -g autosar-standards-fetcher

# 3. Run
autosar-fetcher --help
autosar-fetcher-mcp --help
```

Set a custom interpreter with `PYTHON`:

```bash
PYTHON=/usr/bin/python3 autosar-fetcher-mcp
```

JS usage:

```js
const { mcpConfig } = require('autosar-standards-fetcher');
// mcpConfig() returns { command, args, env } for MCP clients
```
