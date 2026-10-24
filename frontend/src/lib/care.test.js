import { describe, expect, it } from "vitest";
import { careAnswer, careHeadline } from "./care.js";

describe("care labels", () => {
  it("maps tiers and answers", () => {
    expect(careHeadline("emergency")).toBe("Urgent - check now");
    expect(careHeadline("unknown")).toBe("No data");
    expect(careAnswer("contact_doctor")).toBe("Asked for the doctor");
  });
});
