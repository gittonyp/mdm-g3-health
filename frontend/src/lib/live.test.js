import { describe, expect, it } from "vitest";
import { applyTopic, createDevice, restoreDevices, shouldAutoAdd } from "./live.js";

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
  it("restores the last values and trend from the saved log", () => {
    const device = createDevice({ name: "A", channel: "root/a" });
    restoreDevices({ "root/a": device }, [
      [1000, "A", "root/a", 70, 98, 40, 36.7, "rest", "normal", ""],
      [1500, "B", "root/b", 90, 95, 20, 38.0, "walk", "alert", ""],
      [2000, "A", "root/a", null, null, null, null, "rest", "no_finger", ""],
    ]);
    expect(device.last).toEqual({ hr: 70, spo2: 98, hrv: 40, temp: 36.7 });
    expect(device.buf.hr).toEqual([70]);
    expect(device.buf.temp).toEqual([36.7]);
    expect(device.motion.act).toBe("rest");
    expect(device.lastAt).toBe(1000);
    expect(device.state).toBe("offline");
    expect(device.lastVitals).toBe(0);
  });
  it("auto-adds only once and only over http", () => {
    expect(shouldAutoAdd({ patients: [], protocol: "http:", autoadded: null, root: "r" })).toBe(true);
    expect(shouldAutoAdd({ patients: [{ channel: "r" }], protocol: "http:", autoadded: null, root: "r" })).toBe(false);
    expect(shouldAutoAdd({ patients: [], protocol: "file:", autoadded: null, root: "r" })).toBe(false);
    expect(shouldAutoAdd({ patients: [], protocol: "http:", autoadded: "1", root: "r" })).toBe(false);
  });
});
