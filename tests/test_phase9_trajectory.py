import unittest

from gemini_web2api.trajectory import DIMENSIONS, FAILURE_TAXONOMY, run_benchmark


class Phase9TrajectoryTests(unittest.TestCase):
    def test_benchmark_is_permanent_and_green(self):
        report = run_benchmark(3)
        self.assertEqual(report.attempts, 3)
        self.assertEqual(len(report.cases), 10)
        self.assertTrue(report.all_pass)
        self.assertEqual(report.pass_at_1, 1.0)
        self.assertEqual(report.pass_at_3, 1.0)

    def test_all_reliability_dimensions_are_scored(self):
        report = run_benchmark(3)
        self.assertEqual(set(report.dimension_pass_rates), set(DIMENSIONS))
        self.assertTrue(all(rate == 1.0 for rate in report.dimension_pass_rates.values()))
        self.assertEqual(report.failure_counts, {dimension: 0 for dimension in DIMENSIONS})

    def test_failure_taxonomy_covers_every_dimension(self):
        self.assertEqual(set(FAILURE_TAXONOMY), set(DIMENSIONS))
        self.assertTrue(all(FAILURE_TAXONOMY.values()))

    def test_pass_at_3_requires_three_attempts(self):
        with self.assertRaises(ValueError):
            run_benchmark(2)


if __name__ == "__main__":
    unittest.main()
