import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PackagingCompatibilityTests(unittest.TestCase):
    def test_pyproject_exposes_both_entrypoints(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('gemini-agent-bridge = "gemini_web2api.__main__:main"', text)
        self.assertIn('gemini-web2api = "gemini_web2api.__main__:main"', text)
        self.assertIn('requires-python = ">=3.11"', text)

    def test_historical_launcher_delegates_to_package(self):
        text = (ROOT / "gemini_web2api.py").read_text(encoding="utf-8")
        self.assertIn("from gemini_web2api.__main__ import main", text)
        self.assertNotIn("StreamGenerate", text)

    def test_module_version_entrypoint_is_available(self):
        proc = subprocess.run(
            [sys.executable, "-m", "gemini_web2api", "--version"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("gemini-agent-bridge", proc.stdout)


if __name__ == "__main__":
    unittest.main()
