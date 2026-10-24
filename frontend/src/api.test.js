import { describe, expect, it } from "vitest";
import { fmtAge, fmtValue, tierLabel, qualityLabel } from "./api.js";

describe("formatting", () => {
  it("formats ages", () => {
    expect(fmtAge(null)).toBe("—");
    expect(fmtAge(3)).toBe("just now");
    expect(fmtAge(42)).toBe("42s ago");
    expect(fmtAge(120)).toBe("2m ago");
  });
  it("formats missing values", () => {
    expect(fmtValue(null)).toBe("—");
    expect(fmtValue(36.84, 1)).toBe("36.8");
  });
  it("labels tiers and quality", () => {
    expect(tierLabel("emergency")).toBe("Emergency");
    expect(tierLabel("nope")).toBe("No data");
    expect(qualityLabel("missing")).toBe("No device linked");
  });
});
