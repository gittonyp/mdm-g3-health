# Hardware and Firmware

This document describes the ESP32 node, its wiring, the firmware configuration, and the planned LM35 temperature addition. The firmware file is `health_node.ino`.

Current state: the firmware reads heart rate, SpO2, HRV, and motion; it detects falls and raises local alerts. It does **not** read temperature and does **not** run a model.

## Bill of materials

| Part | Role | Interface |
|---|---|---|
| ESP32 DevKit (ESP32-WROOM class) | MCU, WiFi, MQTT | - |
| MAX30102 | Pulse oximeter (HR, SpO2) | I2C, address `0x57` |
| MPU6050 | 3-axis accelerometer + gyroscope | I2C, address `0x68` |
| SSD1306 OLED 128x64 | Local status display | I2C, address `0x3C` |
| Buzzer | Audible alert | GPIO `D27` |
| Green LED | Normal status | GPIO `D14` |
| Red LED | Alert status | GPIO `D26` |
| Push button | Local recalibration | GPIO `D25` to GND |
| LM35 (planned) | Analog temperature | GPIO `D33` (ADC1) |
| 0.1 uF capacitor (LM35) | Supply decoupling | Across LM35 VIN/GND |

## Wiring

I2C bus:

| Signal | ESP32 pin |
|---|---|
| SDA | `D21` (GPIO21) |
| SCL | `D22` (GPIO22) |
| Power | 3.3 V |
| Ground | GND |

All three I2C devices share the bus. The firmware starts it at 400 kHz (`Wire.begin(21, 22)`), then initializes the OLED, MPU6050, and MAX30102.

Other connections:

| Function | ESP32 pin | Notes |
|---|---|---|
| Buzzer | `D27` | PWM tone via LEDC |
| Green LED | `D14` | Current-limited |
| Red LED | `D26` | Current-limited |
| Recalibrate button | `D25` | `INPUT_PULLUP`, press to GND |
| Finger simulation button | `D13` | Only used when `SIM_MODE 1` |
| HR potentiometer | `D34` | Only used when `SIM_MODE 1` |
| SpO2 potentiometer | `D35` | Only used when `SIM_MODE 1` |
| HRV potentiometer | `D32` | Only used when `SIM_MODE 1` |

### LM35 plan (not yet implemented)

- Supply the LM35 from 3.3 V and ground.
- Connect `Vout` to `D33` (GPIO33, ADC1 channel 5).
- Add a 0.1 uF capacitor between VIN and GND close to the sensor.
- Use ADC1: ADC2 pins conflict with WiFi on the ESP32.
- LM35 output is 10 mV per degree Celsius. A nominal conversion is:

```text
voltage_mv = raw * 3300 / 4095
temp_c     = voltage_mv / 10.0
```

The ESP32 ADC is not perfectly linear; calibrate the offset/scale against a reference thermometer if accuracy matters. For the dashboard and ML pipeline, a stable value in the 36-38 C range is sufficient.

The dashboard already accepts an incoming `temp` field and stops simulating when it arrives. The server already stores and scores temperature.

## Firmware configuration

Configuration is at the top of `health_node.ino`:

| Setting | Default | Meaning |
|---|---|---|
| `SIM_MODE` | `0` | `0` = real hardware; `1` = Wokwi simulation using pots and a button |
| `MQTT_HOST` | `broker.hivemq.com` | Public test broker |
| `MQTT_PORT` | `1883` | `8883` when TLS is enabled |
| `MQTT_TLS` | `0` | `1` enables TLS |
| `MQTT_TLS_VERIFY` | `0` | `1` requires a CA certificate |
| `TOPIC_ROOT` | `mdm-g3-pcce/health` | Base topic |
| `MOTION_MS` | `100` | Motion publish period (10 Hz) |
| `VITALS_MS` | `500` | Vitals publish period (2 Hz) |
| `WIFI_SSID`, `WIFI_PASS` | project values | WiFi credentials, set directly in the sketch |

WiFi credentials are intentionally kept in the sketch for this demo. Do not treat that as a production pattern; move them to an untracked header or provisioning flow for anything real.

### Sensor behavior

- **Heart rate**: beat detection on the IR channel, median inter-beat interval over the last 8 beats. Valid only for 40-200 bpm.
- **HRV**: RMSSD over the same inter-beat interval buffer.
- **SpO2**: ratio-of-ratios from red/IR DC and AC components. Uncalibrated; adequate for the demo.
- **Finger detection**: IR threshold (`FINGER_IR 50000`). When no finger is present, vitals are published as `null` and `finger: 0`.
- **Motion**: sampled at 50 Hz internally. Activity is classified as `rest`, `walk`, or `run`; a free-fall plus impact pattern raises a fall event.
- **Local alert**: hysteresis on HR/SpO2 drives the buzzer and red LED. Status is also sent in the vitals `state` field.
- **Recalibration**: local button or MQTT `recalibrate` command resets gyro calibration, vital-sign buffers, and alert state.

### Publish behavior

| Topic | Rate | Payload |
|---|---|---|
| `{root}/vitals` | 2 Hz | `{"t","hr","spo2","hrv","finger","state"}` |
| `{root}/motion` | 10 Hz | `{"t","ax","ay","az","gx","gy","gz","act"}` |
| `{root}/event` | on fall | `{"type":"fall"}` |
| `{root}/status` | on change / last will | `online` or `offline`, retained |
| `{root}/cmd` | subscribed | `recalibrate` |

The firmware uses the flat topic form, so the server maps it to `DEFAULT_DEVICE_ID` (`esp32` by default). The dashboard patient channel for the real board is therefore `mdm-g3-pcce/health`.

QoS is 0: delivery is best-effort. Messages can be lost on a poor WiFi link.

## Build and flash

1. Install the Espressif ESP32 board package in the Arduino IDE.
2. Install these libraries:
   - `PubSubClient`
   - `Adafruit SSD1306`
   - `Adafruit GFX Library`
   - `SparkFun MAX3010x Pulse and Proximity Sensor Library` (for `MAX30105.h`, real mode only)
3. Select the ESP32 board and the correct serial port.
4. Set `SIM_MODE` to `0` for hardware or `1` for Wokwi.
5. Set WiFi and MQTT values if needed.
6. Compile and upload.
7. Open the serial monitor at 115200 baud to see sensor and connection status.

For Wokwi, use `SIM_MODE 1`; the potentiometers at `D34`, `D35`, and `D32` simulate HR, SpO2, and HRV, and the `D13` button simulates finger contact.

## Verification checklist

- OLED shows startup, gyro calibration, and then live values.
- Serial prints WiFi and MQTT connection state.
- The device appears on the dashboard when the patient channel is `mdm-g3-pcce/health`.
- Removing the finger produces `--` values and a `no_finger` state.
- Pressing the recalibrate button clears vitals and alert state.
- A fall event appears in the dashboard event log.
- The server sees the device in `/api/devices` and `/history`.

## Known gaps

- No temperature reading; `temp` is absent from the vitals payload.
- No on-device feature extraction, calibration, or inference.
- No device authentication; any client can publish to the topic root.
- No OTA update path.
- TLS is off by default.
- The fall detector is a heuristic and is not validated against a labelled fall dataset.
