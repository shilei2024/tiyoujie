from django.test import SimpleTestCase

from apps.ocr.benchmark import distance, evaluate, region_matches


class BenchmarkTests(SimpleTestCase):
    def test_edit_distance_and_one_to_one_region_recall(self):
        self.assertEqual(distance("1-2", "1+2"), 1)
        self.assertEqual(region_matches([[0, 0, 10, 10], [0, 0, 10, 10]], [[0, 0, 10, 10]]), 1)

    def test_no_samples_is_blocked_without_fabricated_metrics(self):
        result = evaluate({"samples": []}, {"samples": []})
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["metrics"], {})

    def test_synthetic_metrics_never_prove_quality_and_sign_errors_count(self):
        sample = {
            "id": "synthetic",
            "sha256": "a" * 64,
            "authorized": True,
            "deidentified": True,
            "synthetic": True,
            "authorization_ref": "unit-only",
            "grade_band": "primary",
            "writing": "printed",
            "question_type": "arithmetic",
            "quality": "clear",
            "expected_text": "1-2",
            "formulas": ["1-2"],
            "regions": [[0, 0, 10, 10]],
        }
        predicted = {
            "id": "synthetic",
            "text": "1+2",
            "formulas": ["1+2"],
            "regions": [[0, 0, 10, 10]],
            "correction_seconds": 3,
        }
        result = evaluate({"samples": [sample]}, {"samples": [predicted]})
        self.assertEqual(result["status"], "BLOCKED")
        self.assertAlmostEqual(result["metrics"]["cer"], 1 / 3)
        self.assertAlmostEqual(result["metrics"]["key_symbol_error"], 1 / 3)
        self.assertEqual(result["metrics"]["segmentation_recall"], 1)
        with self.assertRaises(ValueError):
            evaluate({"samples": [sample, sample]}, {"samples": [predicted]})
