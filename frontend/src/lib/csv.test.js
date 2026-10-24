import { describe, expect, it } from "vitest";
import { toCsv } from "./csv.js";

describe("toCsv", () => {
  it("writes the header and escapes commas and quotes", () => {
    const csv = toCsv([[Date.UTC(2026, 0, 2, 3, 4, 5), 'A "B", C', "root/a", 70, 98, 40, null, "rest", "normal", "Stable"]]);
    expect(csv.split("\r\n")[0]).toBe("time,patient,mqtt_channel,heart_rate_bpm,spo2_percent,hrv_ms,temperature_c,activity,status,event");
    expect(csv).toContain('"A ""B"", C"');
    expect(csv).toContain("2026-01-02T03:04:05.000Z");
  });
});
