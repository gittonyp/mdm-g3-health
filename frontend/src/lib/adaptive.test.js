import { describe, expect, it } from "vitest";
import { STATES, VITALS, sparkRange, stateInfo, vitalChip } from "./adaptive.js";

describe("adaptive display", () => {
  it("never exposes fixed clinical ranges", () => {
    const text = JSON.stringify(VITALS);
    expect(text).not.toMatch(/Normal \d/);
    expect(text).not.toMatch(/\d+–\d+ (bpm|%|ms|°C)/);
    expect(VITALS.map((v) => v.hint)).toEqual([
      "Adaptive · personal baseline",
      "Adaptive · personal baseline",
      "Adaptive · rest-only",
      "Estimated body temperature",
    ]);
  });
  it("recognises every firmware state", () => {
    for (const s of ["normal", "measuring", "no_finger", "learning", "watch", "alert", "emergency", "stress", "fall", "offline"]) {
      expect(stateInfo(s).title).toBeTruthy();
      expect(STATES[s]).toBeTruthy();
    }
  });
  it("uses device state for chips and hides missing values", () => {
    expect(vitalChip(null, "alert")).toEqual({ text: "—", cls: "" });
    expect(vitalChip(72, "learning").text).toBe("Learning");
    expect(vitalChip(72, "emergency").cls).toBe("bad");
  });
  it("scales sparklines from observed values only", () => {
    expect(sparkRange("hr", [70, 80])).toEqual([68, 82]);
    expect(sparkRange("hr", [])).toEqual([50, 120]);
  });
});
