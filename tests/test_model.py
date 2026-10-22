import json
import tempfile
import unittest
from pathlib import Path

from server import model


FEATURES = [
    "hr_mean",
    "hr_std",
    "hr_min",
    "hr_max",
    "hr_slope",
    "spo2_mean",
    "spo2_std",
    "spo2_min",
    "temp_mean",
    "temp_std",
    "temp_slope",
    "acc_mean",
    "acc_std",
    "acc_max",
    "acc_energy",
]


def feature_row(value=0.0):
    return {name: value for name in FEATURES}


class ComputeFeaturesTest(unittest.TestCase):
    def test_rejects_short_window(self):
        vitals = [(0.0, 70.0, 98.0, 36.5), (1.0, 71.0, 98.0, 36.5)]
        motion = [(0.0, 0.0, 0.0, 1.0)]
        self.assertIsNone(model.compute_features(vitals, motion, end_ts=1.0, window_seconds=30.0))

    def test_computes_expected_feature_values(self):
        vitals = [(float(t), 70.0, 98.0, 36.5) for t in range(31)]
        motion = [(float(t) / 10.0, 0.0, 0.0, 1.0) for t in range(301)]
        values = model.compute_features(vitals, motion, end_ts=30.0, window_seconds=30.0)
        self.assertIsNotNone(values)
        self.assertEqual(list(values), FEATURES)
        self.assertAlmostEqual(values["hr_mean"], 70.0)
        self.assertAlmostEqual(values["hr_std"], 0.0)
        self.assertAlmostEqual(values["hr_slope"], 0.0)
        self.assertAlmostEqual(values["spo2_mean"], 98.0)
        self.assertAlmostEqual(values["temp_mean"], 36.5)
        self.assertAlmostEqual(values["acc_mean"], 1.0)
        self.assertAlmostEqual(values["acc_energy"], 1.0)


class PersonalizedModelTest(unittest.TestCase):
    def _artifact(self):
        coefficients = [0.0] * len(FEATURES)
        coefficients[FEATURES.index("hr_mean")] = 1.0
        return {
            "model_type": "personal_logreg",
            "features": FEATURES,
            "window_seconds": 30,
            "step_seconds": 15,
            "calibration_seconds": 120,
            "normalization": {"method": "median_mad", "mad_scale": 1.4826, "min_scale": 1e-06},
            "coefficients": coefficients,
            "intercept": -3.0,
            "decision_threshold": 0.5,
        }

    def test_calibrate_then_score_stress(self):
        scorer = model.PersonalizedModel(self._artifact())
        calibration = [feature_row(0.0) for _ in range(4)]
        for row in calibration:
            row["hr_mean"] = 70.0
        scorer.calibrate(calibration)
        self.assertTrue(scorer.ready)

        normal = feature_row(0.0)
        normal["hr_mean"] = 70.0
        self.assertEqual(scorer.evaluate(normal)["level"], "normal")

        stress = feature_row(0.0)
        stress["hr_mean"] = 80.0
        result = scorer.evaluate(stress)
        self.assertGreater(result["score"], 0.9)
        self.assertEqual(result["level"], "alert")

    def test_loads_artifact_from_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(self._artifact()))
            scorer = model.PersonalizedModel.from_file(path)
            self.assertEqual(scorer.features, FEATURES)


class DeviceBufferTest(unittest.TestCase):
    def _artifact(self):
        coefficients = [0.0] * len(FEATURES)
        coefficients[FEATURES.index("hr_mean")] = 1.0
        return {
            "model_type": "personal_logreg",
            "features": FEATURES,
            "window_seconds": 4,
            "step_seconds": 1,
            "calibration_seconds": 4,
            "normalization": {"method": "median_mad", "mad_scale": 1.4826, "min_scale": 1e-06},
            "coefficients": coefficients,
            "intercept": -3.0,
            "decision_threshold": 0.5,
        }

    def test_calibrates_then_scores_new_window(self):
        buffer = model.DeviceBuffer(
            model.PersonalizedModel(self._artifact()),
            window_seconds=4,
            step_seconds=1,
            calibration_seconds=8,
        )
        for t in range(10):
            buffer.add_vitals(float(t), {"hr": 70.0, "spo2": 98.0, "temp": 36.5})
            for i in range(10):
                buffer.add_motion(t + i / 10.0, {"ax": 0.0, "ay": 0.0, "az": 1.0})
            if t >= 4:
                buffer.update(float(t), rule_level="normal")
        self.assertTrue(buffer.model.ready)

        for t in range(10, 16):
            buffer.add_vitals(float(t), {"hr": 90.0, "spo2": 98.0, "temp": 36.5})
            for i in range(10):
                buffer.add_motion(t + i / 10.0, {"ax": 0.0, "ay": 0.0, "az": 1.0})
            result = buffer.update(float(t), rule_level="normal")
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "alert")
        self.assertEqual(result["source"], "model")
        self.assertEqual(buffer.status()["last_result"]["level"], "alert")


if __name__ == "__main__":
    unittest.main()
