import os
import tempfile
import unittest

from gemini_web2api.backend_selection import cookie_auth_kind, effective_backend
from gemini_web2api.config import CONFIG
from gemini_web2api.models import resolve_model


class BackendSelectionTests(unittest.TestCase):

    def _cookie(self, content):
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        handle.write(content)
        handle.close()
        self.addCleanup(lambda: os.unlink(handle.name))
        return handle.name

    def _with_config(self, backend, cookie):
        old_backend = CONFIG.get("upstream_backend")
        old_cookie = CONFIG.get("cookie_file")
        CONFIG["upstream_backend"] = backend
        CONFIG["cookie_file"] = cookie
        self.addCleanup(lambda: CONFIG.update(upstream_backend=old_backend, cookie_file=old_cookie))

    def test_missing_cookie_is_unknown(self):
        self.assertEqual(cookie_auth_kind("/definitely/missing/gab-cookie"), "unknown")

    def test_sid_cookie_is_legacy(self):
        path = self._cookie("SID=redacted; SAPISID=redacted")
        self.assertEqual(cookie_auth_kind(path), "legacy")

    def test_secure_psid_cookie_is_modern(self):
        path = self._cookie("__Secure-1PSID=redacted; __Secure-1PSIDTS=redacted")
        self.assertEqual(cookie_auth_kind(path), "modern")

    def test_json_cookie_export_is_modern(self):
        path = self._cookie('{"__Secure-1PSID":"redacted","__Secure-1PSIDTS":"redacted"}')
        self.assertEqual(cookie_auth_kind(path), "modern")

    def test_browser_array_cookie_export_is_modern(self):
        path = self._cookie('[{"name":"__Secure-1PSID","value":"redacted"},{"name":"__Secure-1PSIDTS","value":"redacted"}]')
        self.assertEqual(cookie_auth_kind(path), "modern")

    def test_netscape_cookie_export_is_modern(self):
        path = self._cookie(
            "# Netscape HTTP Cookie File\n"
            ".google.com\tTRUE\t/\tTRUE\t0\t__Secure-1PSID\tredacted\n"
            ".google.com\tTRUE\t/\tTRUE\t0\t__Secure-1PSIDTS\tredacted\n"
        )
        self.assertEqual(cookie_auth_kind(path), "modern")

    def test_unrelated_cookie_is_unknown(self):
        path = self._cookie("unrelated_cookie=redacted")
        self.assertEqual(cookie_auth_kind(path), "unknown")

    def test_mixed_modern_and_legacy_prefers_modern(self):
        path = self._cookie("SID=redacted; __Secure-1PSID=redacted")
        self.assertEqual(cookie_auth_kind(path), "modern")

    def test_explicit_backend_never_depends_on_cookie(self):
        self.assertEqual(effective_backend("modern", None), "modern")
        self.assertEqual(effective_backend("legacy", None), "legacy")

    def test_auto_selects_legacy_from_sid(self):
        path = self._cookie("SID=redacted")
        self.assertEqual(effective_backend("auto", path), "legacy")

    def test_auto_selects_modern_from_secure_psid(self):
        path = self._cookie("__Secure-1PSID=redacted")
        self.assertEqual(effective_backend("auto", path), "modern")

    def test_auto_preserves_original_zero_config_flow(self):
        self.assertEqual(effective_backend("auto", None), "legacy")

    def test_auto_model_resolution_uses_legacy_mode(self):
        self._with_config("auto", self._cookie("SID=redacted"))
        _, resolved, think, error, extra = resolve_model("gemini-3.6-flash")
        self.assertIsNone(error)
        self.assertEqual(resolved, 1)
        self.assertEqual(think, 4)
        self.assertIsNone(extra)

    def test_auto_model_resolution_maps_pro_to_account_alias(self):
        self._with_config("auto", self._cookie("__Secure-1PSID=redacted; __Secure-1PSIDTS=redacted"))
        _, resolved, think, error, extra = resolve_model("gemini-3.1-pro")
        self.assertIsNone(error)
        self.assertEqual(resolved, "pro")
        self.assertIsNone(think)
        self.assertIsNone(extra)

    def test_auto_model_resolution_maps_flash_to_account_alias(self):
        self._with_config("auto", self._cookie("__Secure-1PSID=redacted"))
        _, resolved, think, error, extra = resolve_model("gemini-3.6-flash")
        self.assertIsNone(error)
        self.assertEqual(resolved, "flash")
        self.assertIsNone(think)
        self.assertIsNone(extra)

    def test_modern_rejects_legacy_only_thinking_alias(self):
        self._with_config("modern", self._cookie("__Secure-1PSID=redacted"))
        _, resolved, think, error, extra = resolve_model("gemini-3.5-flash-thinking")
        self.assertIsNone(resolved)
        self.assertIsNotNone(error)
        self.assertIsNone(think)
        self.assertIsNone(extra)

    def test_auto_unknown_modern_model_passes_through(self):
        self._with_config("auto", self._cookie("__Secure-1PSID=redacted"))
        _, resolved, think, error, extra = resolve_model("gemini-account-model")
        self.assertIsNone(error)
        self.assertEqual(resolved, "gemini-account-model")
        self.assertIsNone(think)
        self.assertIsNone(extra)


if __name__ == "__main__":
    unittest.main()
