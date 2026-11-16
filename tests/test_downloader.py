import importlib.util
import unittest
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "download_autosar_standards.py"
spec = importlib.util.spec_from_file_location("autosar_downloader", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

class DownloaderHelpersTest(unittest.TestCase):
    def test_normalize_official_url(self):
        self.assertEqual(mod.normalize_url("https://autosar.org/standards#x"), "https://www.autosar.org/standards")
        self.assertIsNone(mod.normalize_url("https://example.com/standards"))

    def test_document_detection(self):
        self.assertTrue(mod.is_document_url("https://www.autosar.org/fileadmin/standards/R25-11/CP/AUTOSAR_CP_SWS_COM.pdf"))
        self.assertTrue(mod.is_document_url("https://www.autosar.org/fileadmin/standards/R25-11/CP/schema.zip"))
        self.assertFalse(mod.is_document_url("https://www.autosar.org/fileadmin/standards/style.css"))

    def test_release_and_platform(self):
        url = "https://www.autosar.org/fileadmin/standards/R25-11/AP/AUTOSAR_AP_SWS_Manifest.pdf"
        self.assertEqual(mod.infer_release(url), "R25-11")
        self.assertEqual(mod.infer_platform(url), "Adaptive_Platform")
        self.assertEqual(mod.infer_platform("https://www.autosar.org/fileadmin/standards/R24-11/FO/AUTOSAR_FO_TR_ReleaseOverview.pdf"), "Foundation")

    def test_categories(self):
        self.assertEqual(mod.file_category("https://www.autosar.org/fileadmin/standards/a.xlsx"), "Spreadsheets")
        self.assertEqual(mod.file_category("https://www.autosar.org/fileadmin/standards/b.arxml"), "XML_XSD_ARXML")
        self.assertEqual(mod.file_category("https://www.autosar.org/fileadmin/standards/c.zip"), "Archives")

    def test_tls_context_keeps_verification_enabled(self):
        context, backend = mod.AutosarDownloader.make_ssl_context("openssl", None)
        self.assertTrue(context.verify_mode == mod.ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertTrue(backend)

    def test_certificate_error_detection(self):
        self.assertTrue(mod.AutosarDownloader.is_certificate_verification_error(
            Exception("urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate")
        ))
        self.assertFalse(mod.AutosarDownloader.is_certificate_verification_error(Exception("HTTP 404")))

if __name__ == "__main__":
    unittest.main()
