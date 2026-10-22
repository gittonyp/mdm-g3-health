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
        if hr < 50 or hr > 120:
            score = max(score, 0.95)
            level = _raise(level, "alert")
            reasons.append(f"heart rate {hr:.0f} bpm")
        elif hr < 60 or hr > 100:
            score = max(score, 0.45)
            level = _raise(level, "watch")
            reasons.append(f"heart rate {hr:.0f} bpm")

    if spo2 is not None:
        if spo2 < 92:
            score = max(score, 0.95)
            level = _raise(level, "alert")
            reasons.append(f"SpO2 {spo2:.0f}%")
        elif spo2 < 95:
            score = max(score, 0.45)
            level = _raise(level, "watch")
            reasons.append(f"SpO2 {spo2:.0f}%")

    if temp is not None:
        if temp < 35.5 or temp >= 38.0:
            score = max(score, 0.9)
            level = _raise(level, "alert")
            reasons.append(f"temperature {temp:.1f} C")
        elif temp < 36.1 or temp > 37.2:
            score = max(score, 0.4)
            level = _raise(level, "watch")
            reasons.append(f"temperature {temp:.1f} C")

    return {
        "score": round(score, 2),
        "level": level,
        "reason": "; ".join(reasons) if reasons else "vitals within range",
        "source": "rule",
    }
