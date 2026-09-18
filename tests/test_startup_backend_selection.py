import unittest
from unittest import mock

from gemini_web2api import __main__ as entrypoint
from gemini_web2api.config import CONFIG, DEFAULT_CONFIG


class StartupBackendSelectionTests(unittest.TestCase):
    def test_default_backend_is_auto(self):
        self.assertEqual(DEFAULT_CONFIG["upstream_backend"], "auto")

    def test_startup_resolves_auto_backend_before_server_creation(self):
        original = dict(CONFIG)
        try:
            CONFIG.update(DEFAULT_CONFIG)
            CONFIG["cookie_file"] = "/tmp/redacted-cookie"
            with mock.patch("sys.argv", ["gemini-agent-bridge"]), \
                 mock.patch.object(entrypoint, "load_config"), \
                 mock.patch.object(entrypoint, "find_config", return_value=None), \
                 mock.patch.object(entrypoint, "validate_bind"), \
                 mock.patch.object(entrypoint, "effective_backend", return_value="legacy") as resolver, \
                 mock.patch.object(entrypoint, "install_phase4_runtime"), \
                 mock.patch.object(entrypoint, "install_observability"), \
                 mock.patch.object(entrypoint, "modern_health"), \
                 mock.patch.object(entrypoint, "modern_shutdown"), \
                 mock.patch.object(entrypoint.HardenedThreadedServer, "serve_forever"), \
                 mock.patch.object(entrypoint.HardenedThreadedServer, "shutdown"):
                entrypoint.main()
                resolver.assert_called_once_with("auto", "/tmp/redacted-cookie")
        finally:
            CONFIG.clear()
            CONFIG.update(original)


if __name__ == "__main__":
    unittest.main()
