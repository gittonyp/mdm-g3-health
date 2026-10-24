import { describe, expect, it } from "vitest";
import { baselineText, evidenceText, worstTier } from "./patient.js";

describe("patient helpers", () => {
  it("reports the worst open tier", () => {
    expect(worstTier([{ tier: "watch" }, { tier: "emergency" }], {})).toBe("emergency");
    expect(worstTier([], {})).toBe("stable");
    expect(worstTier([], null)).toBe("unknown");
  });
  it("describes baselines", () => {
    expect(baselineText(null)).toBe("Baseline: not started");
    expect(baselineText({ ready: false, windows_collected: 2, windows_required: 6 }))
      .toBe("Baseline: learning (2/6 windows)");
    expect(baselineText({ ready: true, stale: true })).toBe("Baseline: calibrated (needs refresh)");
  });
  it("summarises evidence", () => {
    expect(evidenceText({ evidence: { value: 130, threshold: 100, baseline: 72 }, score: 3 }))
      .toBe("value 130 · threshold 100 · baseline 72 · score 3");
  });
});
