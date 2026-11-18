import importlib.util
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("das_fix", ROOT / "download_autosar_standards.py")
das = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = das
spec.loader.exec_module(das)


class MissingFilesFixTest(unittest.TestCase):
    def test_sha256_discovered_and_categorized(self):
        self.assertIn(".sha256", das.DOCUMENT_EXTS)
        url = "https://www.autosar.org/fileadmin/standards/R25-11/CP/AUTOSAR_CP_TR_SpecificationHashes.sha256"
        self.assertTrue(das.is_document_url(url))
        self.assertEqual(das.file_category(url), "Text_and_Data")

    def test_sitemap_not_an_artifact(self):
        self.assertFalse(das.is_document_url("https://www.autosar.org/sitemap.xml?tx_seo%5Bsitemap%5D=pages&cHash=abc"))
        self.assertFalse(das.is_document_url("https://www.autosar.org/sitemap.xml"))

    def test_combined_release_tokens(self):
        url = "https://www.autosar.org/fileadmin/standards/R18-10_R4.4.0_R1.5.0/AP/AdaptiveFoundation.zip"
        self.assertEqual(das.infer_all_releases(url), ["R18-10", "R4_4_0", "R1_5_0"])
        self.assertEqual(das.infer_release(url), "R18-10")
        url2 = "https://www.autosar.org/fileadmin/standards/R25-11/CP/AUTOSAR_CP_SWS_COM.pdf"
        self.assertEqual(das.infer_all_releases(url2), ["R25-11"])

    def test_release_filter_matches_combined_token(self):
        selected = {"R4_4_0"}
        url = "https://www.autosar.org/fileadmin/standards/R18-10_R4.4.0_R1.5.0/AP/AdaptiveFoundation.zip"
        primary = das.infer_release(url)
        matched = primary in selected or any(r in selected for r in das.infer_all_releases(url))
        self.assertTrue(matched)


if __name__ == "__main__":
    unittest.main()
