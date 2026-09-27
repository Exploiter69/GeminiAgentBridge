import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExtensionContractTests(unittest.TestCase):
    def test_manifest_is_mv3_and_declares_explicit_extension_csp(self):
        manifest = json.loads((ROOT / "gemini-cookie-sync-extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["content_security_policy"]["extension_pages"], "script-src 'self'; object-src 'self'")
        self.assertIn("cookies", manifest["permissions"])
        self.assertIn("downloads", manifest["permissions"])

    def test_popup_does_not_contain_network_fetch_or_xhr(self):
        popup = (ROOT / "gemini-cookie-sync-extension" / "popup.js").read_text(encoding="utf-8")
        self.assertNotIn("fetch(", popup)
        self.assertNotIn("XMLHttpRequest", popup)
        self.assertIn("chrome.cookies.getAll", popup)
        self.assertIn("chrome.downloads.download", popup)

    def test_extension_docs_warn_about_exported_session_material(self):
        text = (ROOT / "gemini-cookie-sync-extension" / "SETUP.md").read_text(encoding="utf-8")
        self.assertRegex(text.lower(), r"(sensitive|secret|cookie|session)")
        self.assertRegex(text.lower(), r"(do not|don't).*?(share|commit)")


if __name__ == "__main__":
    unittest.main()
