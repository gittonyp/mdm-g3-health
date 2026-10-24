import { describe, expect, it } from "vitest";
import { filterPatients } from "./filters.js";

const rows = [
  { patient_id: "a", program: "hospice", tier: "stable", overdue: false },
  { patient_id: "b", program: "telehealth", tier: "emergency", overdue: true },
  { patient_id: "c", program: "hospice", tier: "watch", overdue: true },
];

describe("filterPatients", () => {
  it("filters by program and status together", () => {
    expect(filterPatients(rows, { program: "hospice", status: "" }).map((r) => r.patient_id)).toEqual(["a", "c"]);
    expect(filterPatients(rows, { program: "", status: "action" }).map((r) => r.patient_id)).toEqual(["b"]);
    expect(filterPatients(rows, { program: "", status: "overdue" }).map((r) => r.patient_id)).toEqual(["b", "c"]);
  });
});
