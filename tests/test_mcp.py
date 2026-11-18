import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name, fname in (("autosar_mcp_server", "autosar_mcp_server.py"), ("das", "download_autosar_standards.py")):
    spec = importlib.util.spec_from_file_location(name, ROOT / fname)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    import sys
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    globals()[name] = mod


class McpHelperTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(autosar_mcp_server._normalize_platform("cp"), "Classic_Platform")
        self.assertEqual(autosar_mcp_server._normalize_platform("AP"), "Adaptive_Platform")
        self.assertEqual(autosar_mcp_server._normalize_release("r4.4.0"), "R4_4_0")

    def test_search_and_versions(self):
        cache = {"assets": [
            {"url": "https://www.autosar.org/fileadmin/standards/R25-11/CP/AUTOSAR_CP_SWS_COM.pdf",
             "platform": "Classic_Platform", "release": "R25-11", "category": "PDF",
             "filename": "AUTOSAR_CP_SWS_COM.pdf", "referrer": ""},
            {"url": "https://www.autosar.org/fileadmin/standards/R24-11/AP/AUTOSAR_AP_SWS_MANIFEST.pdf",
             "platform": "Adaptive_Platform", "release": "R24-11", "category": "PDF",
             "filename": "AUTOSAR_AP_SWS_MANIFEST.pdf", "referrer": ""},
        ]}
        self.assertEqual(autosar_mcp_server.list_versions(cache), ["R24-11", "R25-11"])
        self.assertEqual(len(autosar_mcp_server.search_assets(cache, query="COM")), 1)
        self.assertEqual(len(autosar_mcp_server.search_assets(cache, platform="CP")), 1)
        self.assertEqual(len(autosar_mcp_server.search_assets(cache, filename="manifest")), 1)

    def test_tool_defs(self):
        names = {t["name"] for t in autosar_mcp_server.TOOLS}
        self.assertEqual(names, {"autosar_versions", "autosar_search", "autosar_download", "autosar_status"})


if __name__ == "__main__":
    unittest.main()
