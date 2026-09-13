import unittest
from pathlib import Path

from scripts.phase13_release_candidate import PHASE_COMMITS, REQUIRED_FILES

ROOT = Path(__file__).resolve().parents[1]


class Phase13ReleaseCandidateTests(unittest.TestCase):
    def test_required_release_files_exist(self):
        missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
        self.assertEqual(missing, [])

    def test_phase_commits_are_full_sha_values(self):
        self.assertEqual(len(PHASE_COMMITS), 5)
        for sha in PHASE_COMMITS.values():
            self.assertEqual(len(sha), 40)
            self.assertRegex(sha, r"^[0-9a-f]{40}$")

    def test_release_verifier_is_agent_independent(self):
        text = (ROOT / "scripts/phase13_release_candidate.py").read_text(encoding="utf-8")
        self.assertIn("agent_claims_used_as_verification", text)
        self.assertIn('"merge-base"', text)
        self.assertIn('"--is-ancestor"', text)
        self.assertIn("working_tree_clean", text)
        self.assertIn("real_client_execution", text)


if __name__ == "__main__":
    unittest.main()
