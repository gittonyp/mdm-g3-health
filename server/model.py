import json
import math
import statistics
from pathlib import Path

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
SIGNAL_OF = {name: name.split("_", 1)[0] for name in FEATURES}
MIN_SAMPLES = 5
MIN_CALIBRATION_ROWS = 4


def _finite(value):
    return value is not None and math.isfinite(value)


def _slope(times, values):
    if len(times) < 2:
        return 0.0
    mean_t = sum(times) / len(times)
    mean_v = sum(values) / len(values)
    denominator = sum((t - mean_t) ** 2 for t in times)
    if denominator <= 0:
        return 0.0
    return sum((t - mean_t) * (v - mean_v) for t, v in zip(times, values)) / denominator


def _stats(values):
    return {
        "mean": sum(values) / len(values),
        "std": statistics.pstdev(values),
        "min": min(values),
        "max": max(values),
    }


def compute_features(vitals, motion, end_ts, window_seconds=30.0, features=None):
    """Compute window features; only the signals needed by `features` must have data."""
    wanted = list(features) if features is not None else FEATURES
    needed = {SIGNAL_OF[name] for name in wanted}
    start_ts = end_ts - window_seconds
    vital_rows = [row for row in vitals if start_ts <= row[0] <= end_ts]
    motion_rows = [row for row in motion if start_ts <= row[0] <= end_ts]

    hr = [(row[0], row[1]) for row in vital_rows if _finite(row[1])]
    spo2 = [(row[0], row[2]) for row in vital_rows if _finite(row[2])]
    temp = [(row[0], row[3]) for row in vital_rows if _finite(row[3])]
    acc = [
        (row[0], math.sqrt(row[1] ** 2 + row[2] ** 2 + row[3] ** 2))
        for row in motion_rows
        if _finite(row[1]) and _finite(row[2]) and _finite(row[3])
    ]

    series = {"hr": hr, "spo2": spo2, "temp": temp, "acc": acc}
    for signal in needed:
        if len(series[signal]) < MIN_SAMPLES:
            return None

    hr_values = [value for _, value in hr]
    spo2_values = [value for _, value in spo2]
    temp_values = [value for _, value in temp]
    acc_values = [value for _, value in acc]

    def stats_of(values):
        return _stats(values) if len(values) >= MIN_SAMPLES else None

    hr_stats = stats_of(hr_values)
    spo2_stats = stats_of(spo2_values)
    temp_stats = stats_of(temp_values)
    acc_stats = stats_of(acc_values)

    builders = {
        "hr_mean": lambda: hr_stats["mean"],
        "hr_std": lambda: hr_stats["std"],
        "hr_min": lambda: hr_stats["min"],
        "hr_max": lambda: hr_stats["max"],
        "hr_slope": lambda: _slope([t for t, _ in hr], hr_values),
        "spo2_mean": lambda: spo2_stats["mean"],
        "spo2_std": lambda: spo2_stats["std"],
        "spo2_min": lambda: spo2_stats["min"],
        "temp_mean": lambda: temp_stats["mean"],
        "temp_std": lambda: temp_stats["std"],
        "temp_slope": lambda: _slope([t for t, _ in temp], temp_values),
        "acc_mean": lambda: acc_stats["mean"],
        "acc_std": lambda: acc_stats["std"],
        "acc_max": lambda: acc_stats["max"],
        "acc_energy": lambda: sum(value ** 2 for value in acc_values) / len(acc_values),
    }
    return {name: builders[name]() for name in wanted}


class PersonalizedModel:
    def __init__(self, artifact):
        features = artifact.get("features")
        # Retrained models may use any non-empty subset of the known features (for example
        # without the temperature features); the artifact's own order is authoritative.
        if (
            not isinstance(features, list)
            or not features
            or len(set(features)) != len(features)
            or any(name not in SIGNAL_OF for name in features)
        ):
            raise ValueError("model artifact uses unknown, duplicate, or no features")
        if len(artifact.get("coefficients", [])) != len(features):
            raise ValueError("model artifact coefficients do not match its features")
        self.features = list(features)
        self.window_seconds = float(artifact.get("window_seconds", 30))
        self.step_seconds = float(artifact.get("step_seconds", 15))
        self.calibration_seconds = float(artifact.get("calibration_seconds", 120))
        self.coefficients = [float(value) for value in artifact["coefficients"]]
        self.intercept = float(artifact["intercept"])
        self.decision_threshold = float(artifact.get("decision_threshold", 0.5))
        self.alert_threshold = float(artifact.get("alert_threshold", 0.8))
        normalization = artifact.get("normalization", {})
        self.min_scale = float(normalization.get("min_scale", 1e-6))
        self.center = None
        self.scale = None

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))

    @property
    def ready(self):
        return self.center is not None and self.scale is not None

    @property
    def status(self):
        return {
            "ready": self.ready,
            "model_type": "personal_logreg",
            "window_seconds": self.window_seconds,
            "step_seconds": self.step_seconds,
            "calibration_seconds": self.calibration_seconds,
            "decision_threshold": self.decision_threshold,
            "alert_threshold": self.alert_threshold,
        }

    def calibrate(self, rows):
        if len(rows) < MIN_CALIBRATION_ROWS:
            raise ValueError("not enough calibration windows")
        center = []
        scale = []
        for feature in self.features:
            values = [row[feature] for row in rows]
            midpoint = statistics.median(values)
            mad = statistics.median(abs(value - midpoint) for value in values) * 1.4826
            center.append(midpoint)
            # Must match the training notebook: a (near-)constant feature gets scale 1.0,
            # not min_scale, otherwise tiny deviations become enormous z-scores.
            scale.append(mad if mad > self.min_scale else 1.0)
        self.center = center
        self.scale = scale

    def evaluate(self, features):
        if not self.ready:
            return None
        logit = self.intercept
        for index, feature in enumerate(self.features):
            normalized = (features[feature] - self.center[index]) / self.scale[index]
            logit += self.coefficients[index] * normalized
        if logit >= 0:
            probability = 1.0 / (1.0 + math.exp(-logit))
        else:
            exponential = math.exp(logit)
            probability = exponential / (1.0 + exponential)

        if probability >= self.alert_threshold:
            level = "alert"
        elif probability >= self.decision_threshold:
            level = "watch"
        else:
            level = "normal"
        return {
            "score": round(probability, 3),
            "level": level,
            "reason": f"personal model stress probability {probability:.2f}",
            "source": "model",
        }


class DeviceBuffer:
    def __init__(self, model, window_seconds=None, step_seconds=None, calibration_seconds=None):
        self.model = model
        self.window_seconds = float(window_seconds if window_seconds is not None else model.window_seconds)
        self.step_seconds = float(step_seconds if step_seconds is not None else model.step_seconds)
        self.calibration_seconds = float(
            calibration_seconds if calibration_seconds is not None else model.calibration_seconds
        )
        self.vitals = []
        self.motion = []
        self.calibration_rows = []
        self.first_ts = None
        self.last_window_ts = None
        self.last_result = None

    def _touch(self, ts):
        if self.first_ts is None:
            self.first_ts = ts

    def _prune(self, now):
        cutoff = now - self.window_seconds - 5.0
        self.vitals = [row for row in self.vitals if row[0] >= cutoff]
        self.motion = [row for row in self.motion if row[0] >= cutoff]

    def add_vitals(self, ts, data):
        self._touch(ts)
        self.vitals.append((ts, data.get("hr"), data.get("spo2"), data.get("temp")))
        self._prune(ts)

    def add_motion(self, ts, data):
        self._touch(ts)
        self.motion.append((ts, data.get("ax"), data.get("ay"), data.get("az")))
        self._prune(ts)

    def update(self, now, rule_level="normal"):
        if self.first_ts is None:
            return None
        if self.last_window_ts is not None and now - self.last_window_ts < self.step_seconds:
            return None

        features = compute_features(
            self.vitals, self.motion, now, self.window_seconds, self.model.features
        )
        if features is None:
            if not self.model.ready and not self.calibration_rows:
                # No usable data yet (e.g. firmware without temperature): restart the
                # calibration clock so it begins once complete data actually arrives.
                self.first_ts = None
            return None
        self.last_window_ts = now

        if self.model.ready:
            self.last_result = self.model.evaluate(features)
            return self.last_result

        calibration_end = self.first_ts + self.calibration_seconds
        if rule_level == "normal" and now <= calibration_end + self.window_seconds:
            self.calibration_rows.append(features)

        if now >= calibration_end and len(self.calibration_rows) >= MIN_CALIBRATION_ROWS:
            self.model.calibrate(self.calibration_rows)
        return None

    def status(self):
        return {
            **self.model.status,
            "calibration_windows": len(self.calibration_rows),
            "calibration_complete": self.model.ready,
            "calibration_seconds_override": self.calibration_seconds,
            "last_result": self.last_result,
        }
