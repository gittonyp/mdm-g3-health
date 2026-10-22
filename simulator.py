import argparse
import json
import os
import random
import time

import paho.mqtt.client as mqtt

SCENARIOS = ("normal", "stress", "fall", "no_finger", "offline")


class Simulator:
    def __init__(self, args):
        self.args = args
        self.fall_sent = False
        self.start = time.time()
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"sim-{args.device}-{random.randint(1000, 9999)}",
        )
        self.client.on_connect = self._on_connect
        self.client.will_set(
            self.topic("status"),
            "offline",
            qos=0,
            retain=True,
        )

    def topic(self, kind):
        if self.args.device == "default":
            return f"{self.args.root}/{kind}"
        return f"{self.args.root}/{self.args.device}/{kind}"

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if getattr(reason_code, "value", reason_code) == 0:
            client.publish(
                self.topic("status"),
                "online",
                qos=0,
                retain=True,
            )
            print(f"publishing to {self.topic('vitals')}")

    def publish(self, kind, payload):
        self.client.publish(
            self.topic(kind),
            json.dumps(payload),
            qos=0,
        )

    def vitals(self, t):
        scenario = self.args.scenario
        if scenario == "no_finger":
            return {
                "t": t,
                "hr": None,
                "spo2": None,
                "hrv": None,
                "finger": 0,
                "state": "no_finger",
                "temp": round(random.gauss(36.7, 0.1), 1),
            }
        if scenario == "stress":
            hr = random.gauss(112, 6)
            spo2 = random.gauss(96, 0.8)
            hrv = random.gauss(24, 3)
            temp = random.gauss(37.4, 0.15)
            state = "alert"
        elif scenario == "fall":
            hr = random.gauss(88, 5)
            spo2 = random.gauss(97, 0.8)
            hrv = random.gauss(35, 4)
            temp = random.gauss(36.8, 0.1)
            state = "fall" if self.fall_sent else "normal"
        else:
            hr = random.gauss(74, 4)
            spo2 = random.gauss(98, 0.7)
            hrv = random.gauss(44, 4)
            temp = random.gauss(36.7, 0.1)
            state = "normal"
        return {
            "t": t,
            "hr": round(hr, 0),
            "spo2": round(spo2, 0),
            "hrv": round(hrv, 0),
            "finger": 1,
            "state": state,
            "temp": round(temp, 1),
        }

    def motion(self, t):
        scenario = self.args.scenario
        if scenario == "fall" and self.fall_sent:
            ax = random.gauss(0, 1.2)
            ay = random.gauss(0, 1.2)
            az = random.gauss(2.5, 0.8)
            act = "fall"
        elif scenario == "stress":
            ax = random.gauss(0, 0.15)
            ay = random.gauss(0, 0.15)
            az = random.gauss(1.0, 0.05)
            act = "walk"
        else:
            ax = random.gauss(0, 0.03)
            ay = random.gauss(0, 0.03)
            az = random.gauss(1.0, 0.01)
            act = "rest"
        return {
            "t": t,
            "ax": round(ax, 3),
            "ay": round(ay, 3),
            "az": round(az, 3),
            "gx": round(random.gauss(0, 2), 1),
            "gy": round(random.gauss(0, 2), 1),
            "gz": round(random.gauss(0, 2), 1),
            "act": act,
        }

    def run(self):
        self.client.connect(
            self.args.host,
            self.args.port,
            keepalive=30,
        )
        self.client.loop_start()
        deadline = time.time() + self.args.duration
        fall_at = time.time() + max(1, self.args.duration / 3)
        last_vitals = 0.0
        last_motion = 0.0
        while time.time() < deadline:
            now = time.time()
            t = int((now - self.start) * 1000)
            if (
                self.args.scenario == "fall"
                and not self.fall_sent
                and now >= fall_at
            ):
                self.fall_sent = True
                self.publish("event", {"type": "fall"})
            if now - last_vitals >= 0.5:
                last_vitals = now
                self.publish("vitals", self.vitals(t))
            if now - last_motion >= 0.1:
                last_motion = now
                self.publish("motion", self.motion(t))
            time.sleep(0.02)
        self.client.publish(
            self.topic("status"),
            "offline",
            qos=0,
            retain=True,
        )
        time.sleep(0.3)
        self.client.loop_stop()
        self.client.disconnect()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="sim01")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument(
        "--host",
        default=os.getenv("MQTT_HOST", "broker.hivemq.com"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MQTT_PORT", "1883")),
    )
    parser.add_argument(
        "--root",
        default=os.getenv("MQTT_ROOT", "mdm-g3-pcce/health"),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    sim = Simulator(args)
    try:
        sim.run()
    except KeyboardInterrupt:
        sim.client.publish(
            sim.topic("status"),
            "offline",
            qos=0,
            retain=True,
        )
        sim.client.loop_stop()
        sim.client.disconnect()


if __name__ == "__main__":
    main()
