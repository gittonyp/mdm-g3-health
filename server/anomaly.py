from . import config

LEVEL_ORDER = {"normal": 0, "watch": 1, "alert": 2}


def _raise(level, candidate):
    if LEVEL_ORDER[candidate] > LEVEL_ORDER[level]:
        return candidate
    return level


def evaluate_vitals(hr, spo2, temp):
    score = 0.0
    level = "normal"
    reasons = []

    if hr is not None:
        if hr < config.ACTIONABLE_HR_LOW or hr > config.ACTIONABLE_HR_HIGH:
            score = max(score, 0.95)
            level = _raise(level, "alert")
            reasons.append(f"heart rate {hr:.0f} bpm")
        elif hr < config.WATCH_HR_LOW or hr > config.WATCH_HR_HIGH:
            score = max(score, 0.45)
            level = _raise(level, "watch")
            reasons.append(f"heart rate {hr:.0f} bpm")

    if spo2 is not None:
        if spo2 < config.ACTIONABLE_SPO2:
            score = max(score, 0.95)
            level = _raise(level, "alert")
            reasons.append(f"SpO2 {spo2:.0f}%")
        elif spo2 < config.WATCH_SPO2:
            score = max(score, 0.45)
            level = _raise(level, "watch")
            reasons.append(f"SpO2 {spo2:.0f}%")

    if temp is not None:
        if temp < config.ACTIONABLE_TEMP_LOW or temp >= config.ACTIONABLE_TEMP_HIGH:
            score = max(score, 0.9)
            level = _raise(level, "alert")
            reasons.append(f"temperature {temp:.1f} C")
        elif temp < config.WATCH_TEMP_LOW or temp > config.WATCH_TEMP_HIGH:
            score = max(score, 0.4)
            level = _raise(level, "watch")
            reasons.append(f"temperature {temp:.1f} C")

    return {
        "score": round(score, 2),
        "level": level,
        "reason": "; ".join(reasons) if reasons else "vitals within range",
        "source": "rule",
    }
