import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FinalReleaseGateTests(unittest.TestCase):
    def test_gate_has_finite_release_surface(self):
        text = (ROOT / "scripts/final_release_gate.py").read_text(encoding="utf-8")
        for marker in ("unit_full", "package_build", "trajectory_benchmark", "performance_benchmark", "live_gemini_web"):
            self.assertIn(marker, text)
        self.assertIn("fresh_live_evidence", text)
        self.assertIn("hermes", text.lower())
        self.assertIn("opencode", text.lower())

    def test_gate_does_not_print_or_persist_credentials(self):
        text = (ROOT / "scripts/final_release_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("print(args.cookie_file)", text)
        self.assertIn("never printed", text)
        self.assertNotIn("read_text(encoding=\"utf-8\")", text[text.find("args.cookie_file"):])

    def test_credential_gate_checks_git_tracking_not_local_existence(self):
        text = (ROOT / "scripts/final_release_gate.py").read_text(encoding="utf-8")
        self.assertIn('git", "ls-files", "--error-unmatch"', text)
        self.assertNotIn(
            'not any((ROOT / name).exists() for name in ("config.json", ".env", "cookie.txt"))',
            text,
        )

    def test_streamed_tool_calls_use_separate_terminal_finish_chunk(self):
        text = (ROOT / "gemini_web2api/server.py").read_text(encoding="utf-8")
        self.assertIn('emit_stream_chunk({"role": "assistant"})', text)
        self.assertIn('"tool_calls": [{', text)
        self.assertIn('emit_stream_chunk({}, "tool_calls")', text)
        self.assertIn('emit_stream_chunk({}, "stop")', text)

    def test_release_document_exists(self):
        self.assertTrue((ROOT / "docs/RELEASE.md").is_file())
        self.assertIn("--live", (ROOT / "docs/RELEASE.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
