import { describe, expect, it } from "vitest";
import { applyTopic, createDevice, shouldAutoAdd } from "./live.js";

describe("live reducer", () => {
  it("never fabricates a temperature", () => {
    const d = createDevice({ name: "A", channel: "root/a" });
    applyTopic(d, "vitals", JSON.stringify({ hr: 70, spo2: 98, hrv: 40, temp: null, state: "learning" }), 1000);
    expect(d.last.temp).toBe(null);
    expect(d.state).toBe("learning");
    expect(d.last.hr).toBe(70);
    expect(d.buf.temp).toEqual([]);
  });
  it("stores numeric temperature readings as numbers", () => {
    const d = createDevice({ name: "A", channel: "root/a" });
    applyTopic(d, "vitals", JSON.stringify({ temp: "36.8" }), 1000);
    expect(d.last.temp).toBe(36.8);
    expect(d.buf.temp).toEqual([36.8]);
  });
  it("accepts adaptive states and ignores unknown ones", () => {
    const d = createDevice({ name: "A", channel: "root/a" });
    applyTopic(d, "vitals", JSON.stringify({ hr: 70, state: "emergency" }), 1000);
    expect(d.state).toBe("emergency");
    applyTopic(d, "vitals", JSON.stringify({ hr: 70, state: "made_up" }), 2000);
    expect(d.state).toBe("emergency");
  });
  it("auto-adds only once and only over http", () => {
    expect(shouldAutoAdd({ patients: [], protocol: "http:", autoadded: null, root: "r" })).toBe(true);
    expect(shouldAutoAdd({ patients: [{ channel: "r" }], protocol: "http:", autoadded: null, root: "r" })).toBe(false);
    expect(shouldAutoAdd({ patients: [], protocol: "file:", autoadded: null, root: "r" })).toBe(false);
    expect(shouldAutoAdd({ patients: [], protocol: "http:", autoadded: "1", root: "r" })).toBe(false);
  });
});
