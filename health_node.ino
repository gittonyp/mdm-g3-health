/*
  MDM G3 - Health node (ESP32)

  Just press Upload. Everything is already configured:
    - WiFi + HiveMQ public broker (see CONFIG below)
    - Topic root mdm-g3-pcce/health  -> server device "esp32" -> patient PT-0003

  Sensors : MPU6050 (0x68), MAX30102 (0x57), OLED SSD1306 (0x3C)  -> I2C SDA D21 / SCL D22
            LM35 temperature sensor                                -> Vout to D33 (ADC1)
  Outputs : Buzzer D27, Green LED D14, Red LED D26
  Inputs  : Recalibrate button D25 (to GND)

  LM35 wiring: VCC -> 5V (VIN pin), GND -> GND, Vout -> D33, 0.1 uF capacitor across VCC/GND.
               Tape the LM35 next to the MAX30102 so the same finger touches both.

  MQTT topics (all JSON, QoS 0):
    TOPIC_ROOT/vitals  2 Hz    {"t","hr","spo2","hrv","temp","finger","state"}
    TOPIC_ROOT/motion  10 Hz   {"t","ax","ay","az","gx","gy","gz","act"}
    TOPIC_ROOT/event   on fall {"type":"fall"}
    TOPIC_ROOT/status  retained "online"/"offline" (last-will)
    TOPIC_ROOT/cmd     send "recalibrate" to recalibrate remotely

  "temp" is null whenever there is no trustworthy reading (no finger, sensor still warming
  up, or LM35 unplugged). The server treats null as "no data" and never alerts on it.

  Libraries: PubSubClient, Adafruit SSD1306, Adafruit GFX,
             SparkFun MAX3010x (only needed when SIM_MODE 0)
  Board    : ESP32 Dev Module (Espressif ESP32 core 2.x or 3.x)
*/

// ======================= CONFIG =======================
#define SIM_MODE 0   // 1 = Wokwi (pots D34/D35/D32 + button D13 fake the MAX30102)
                     // 0 = real hardware

#define MQTT_HOST   "broker.hivemq.com"   // PUBLIC TEST BROKER - fake/test data only!
#define MQTT_PORT   1883                  // 8883 when MQTT_TLS 1
#define MQTT_USER   ""                    // empty = anonymous
#define MQTT_PASS   ""
#define MQTT_TLS         0                // 1 = encrypted
#define MQTT_TLS_VERIFY  0                // 0 = encrypted but UNVERIFIED (testing only)

#define TOPIC_ROOT  "mdm-g3-pcce/health"

#define WIFI_SSID   "pratik098"           // 2.4 GHz only
#define WIFI_PASS   "pratik098"

// ---------- publish rates ----------
#define MOTION_MS   100     // 10 Hz
#define VITALS_MS   500     // 2 Hz

// ---------- temperature (LM35, 10 mV per degC) ----------
#define PIN_TEMP            33       // ADC1 channel 5 (ADC2 pins do not work with WiFi)
#define TEMP_OFFSET_C       3.0f     // fingertip skin reads ~2-4 degC below body temperature;
                                     // set to 0 for raw sensor readings, or tune against a thermometer
#define TEMP_SETTLE_MS      30000    // finger must be on the sensor this long before temp is trusted
#define TEMP_SKIN_MIN_C     25.0f    // below / above this the LM35 is considered unplugged or faulty
#define TEMP_SKIN_MAX_C     42.0f

// ---------- pins ----------
#define PIN_BUZZ    27
#define PIN_GREEN   14
#define PIN_RED     26
#define PIN_RECAL   25
#define PIN_FINGER  13      // sim only
#define PIN_POT_HR  34      // sim only
#define PIN_POT_SPO 35      // sim only
#define PIN_POT_HRV 32      // sim only

#define MPU_ADDR    0x68
#define OLED_ADDR   0x3C
#define FINGER_IR   50000   // real sensor: IR above this = finger present

#include <Arduino.h>
#include <WiFi.h>
#if MQTT_TLS
  #include <WiFiClientSecure.h>
#endif
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#if !SIM_MODE
  #include "MAX30105.h"
  #include "heartRate.h"
#endif

// ======================= globals =======================
Adafruit_SSD1306 oled(128, 64, &Wire, -1);

#if MQTT_TLS
  WiFiClientSecure net;
#else
  WiFiClient net;
#endif
PubSubClient mqtt(net);

#if !SIM_MODE
  MAX30105 pox;
#endif

char clientId[32];
char tVitals[64], tMotion[64], tEvent[64], tStatus[64], tCmd[64];

// vitals
float hr = 0, spo2 = 0, hrv = 0;
bool  finger = false, vitalsValid = false;

// temperature
float    tempSkinC = NAN;          // smoothed LM35 reading
bool     fingerPrev = false;
uint32_t fingerOnAt = 0;

// motion
float ax, ay, az, gx, gy, gz;
float gOffX = 0, gOffY = 0, gOffZ = 0;
const int WIN = 50;                 // 1 s of magnitude at 50 Hz
float magBuf[WIN]; int magIdx = 0, magCnt = 0;
int actState = 0, candAct = 0, candCount = 0;   // 0 rest, 1 walk, 2 run
const char* ACT_NAME[] = {"rest", "walk", "run"};
uint32_t freefallAt = 0, fallUntil = 0;
bool fallEventPending = false;

// status
int  alertLevel = 0;                // hysteresis counter 0..4
bool alertOn = false;
bool recalRequested = false;

// timers
uint32_t tMpu = 0, tAct = 0, tStat = 0, tPubM = 0, tPubV = 0, tOled = 0;
uint32_t tWifi = 0, tMqtt = 0, tBuzz = 0, tBtn = 0, tSim = 0, tTemp = 0, tLog = 0;
bool wifiWasUp = false, mqttWasUp = false;

// ======================= buzzer =======================
void buzzInit() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_BUZZ, 2000, 8);
#else
  ledcSetup(0, 2000, 8); ledcAttachPin(PIN_BUZZ, 0);
#endif
}
void buzz(bool on) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWriteTone(PIN_BUZZ, on ? 2500 : 0);
#else
  ledcWriteTone(0, on ? 2500 : 0);
#endif
}

// ======================= MPU6050 (raw registers, no library) =======================
void mpuInit() {
  Wire.beginTransmission(MPU_ADDR); Wire.write(0x6B); Wire.write(0x00); Wire.endTransmission(); // wake
  Wire.beginTransmission(MPU_ADDR); Wire.write(0x1C); Wire.write(0x08); Wire.endTransmission(); // +-4 g
  Wire.beginTransmission(MPU_ADDR); Wire.write(0x1A); Wire.write(0x03); Wire.endTransmission(); // DLPF ~44 Hz
}

bool mpuRead() {
  Wire.beginTransmission(MPU_ADDR); Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)14) != 14) return false;
  int16_t r[7];
  for (int i = 0; i < 7; i++) {
    uint8_t hi = Wire.read();
    uint8_t lo = Wire.read();
    r[i] = (int16_t)((hi << 8) | lo);
  }
  ax = r[0] / 8192.0f; ay = r[1] / 8192.0f; az = r[2] / 8192.0f;
  gx = r[4] / 131.0f - gOffX; gy = r[5] / 131.0f - gOffY; gz = r[6] / 131.0f - gOffZ;
  return true;
}

void calibrateGyro() {
  float sx = 0, sy = 0, sz = 0; int n = 0;
  gOffX = gOffY = gOffZ = 0;
  for (int i = 0; i < 100; i++) {
    if (mpuRead()) { sx += gx; sy += gy; sz += gz; n++; }
    delay(5);
  }
  if (n) { gOffX = sx / n; gOffY = sy / n; gOffZ = sz / n; }
  magCnt = 0; magIdx = 0; actState = candAct = 0; candCount = 0;
  fallUntil = 0;
}

// ======================= motion logic =======================
void motionSample() {
  if (!mpuRead()) return;
  float mag = sqrtf(ax * ax + ay * ay + az * az);
  magBuf[magIdx] = mag; magIdx = (magIdx + 1) % WIN; if (magCnt < WIN) magCnt++;

  // fall = free-fall (<0.4 g) followed within 600 ms by impact (>2.5 g)
  uint32_t now = millis();
  if (mag < 0.4f) freefallAt = now;
  if (mag > 2.5f && freefallAt && now - freefallAt < 600) {
    if (now > fallUntil) fallEventPending = true;
    fallUntil = now + 5000;
    freefallAt = 0;
  }
}

// every 500 ms: std-dev of |a| over last 1 s, must agree 3 times in a row (1.5 s) to switch
void evalActivity() {
  if (magCnt < WIN) return;
  float m = 0, v = 0;
  for (int i = 0; i < WIN; i++) m += magBuf[i];
  m /= WIN;
  for (int i = 0; i < WIN; i++) v += (magBuf[i] - m) * (magBuf[i] - m);
  float sd = sqrtf(v / WIN);
  int cand = (sd < 0.08f) ? 0 : (sd < 0.45f) ? 1 : 2;
  if (cand == candAct) candCount++; else { candAct = cand; candCount = 1; }
  if (candCount >= 3) actState = candAct;
}

const char* activityName() { return (millis() < fallUntil) ? "fall" : ACT_NAME[actState]; }

// ======================= temperature (LM35) =======================
void tempInit() {
#if !SIM_MODE
  pinMode(PIN_TEMP, INPUT);
  analogSetPinAttenuation(PIN_TEMP, ADC_0db);   // ~0.1-0.95 V range, best accuracy for 0.25-0.42 V
#endif
}

// every 200 ms: average 16 ADC reads, then low-pass filter
void tempSample() {
#if SIM_MODE
  float c = 33.5f + (random(-20, 21) / 100.0f);
#else
  uint32_t mv = 0;
  for (int i = 0; i < 16; i++) mv += analogReadMilliVolts(PIN_TEMP);
  float c = (mv / 16.0f) / 10.0f;               // LM35: 10 mV per degC
#endif
  tempSkinC = isnan(tempSkinC) ? c : tempSkinC + (c - tempSkinC) * 0.1f;
}

// true only when the number is worth sending: finger on, sensor warmed up, plausible reading
bool tempPublishable() {
  if (!finger || isnan(tempSkinC)) return false;
  if (millis() - fingerOnAt < TEMP_SETTLE_MS) return false;
  return tempSkinC >= TEMP_SKIN_MIN_C && tempSkinC <= TEMP_SKIN_MAX_C;
}

float tempBodyC() { return tempSkinC + TEMP_OFFSET_C; }

// ======================= vitals =======================
#if SIM_MODE
// Wokwi: pots set the values, button D13 = finger on sensor
void simUpdate() {
  finger = (digitalRead(PIN_FINGER) == LOW);
  float h = 40 + analogRead(PIN_POT_HR)  * (140.0f / 4095);
  float s = 85 + analogRead(PIN_POT_SPO) * (15.0f  / 4095);
  float v = 10 + analogRead(PIN_POT_HRV) * (110.0f / 4095);
  if (!vitalsValid) { hr = h; spo2 = s; hrv = v; }
  hr   += (h - hr)   * 0.3f;
  spo2 += (s - spo2) * 0.3f;
  hrv  += (v - hrv)  * 0.3f;
  vitalsValid = finger;
}
void resetVitals() { vitalsValid = false; }
#else
// Real MAX30102: beat detection -> median IBI -> HR, RMSSD -> HRV, ratio-of-ratios -> SpO2
const int IBI_N = 8;
float ibi[IBI_N]; int ibiCount = 0, ibiIdx = 0;
uint32_t lastBeat = 0;
float dcR = 0, dcI = 0, sumR = 0, sumI = 0; int nS = 0;
uint32_t fingerSince = 0;

void resetVitals() {
  ibiCount = 0; ibiIdx = 0; lastBeat = 0;
  dcR = dcI = sumR = sumI = 0; nS = 0;
  vitalsValid = false; hr = spo2 = hrv = 0; fingerSince = 0;
}

float medianIbi() {
  float t[IBI_N]; int n = min(ibiCount, IBI_N);
  for (int i = 0; i < n; i++) t[i] = ibi[i];
  for (int i = 1; i < n; i++) { float k = t[i]; int j = i - 1; while (j >= 0 && t[j] > k) { t[j + 1] = t[j]; j--; } t[j + 1] = k; }
  return t[n / 2];
}

float rmssd() {
  int n = min(ibiCount, IBI_N);
  if (n < 4) return 0;
  // IBIs are stored circularly; order matters, so rebuild oldest -> newest
  float seq[IBI_N]; int start = (ibiCount >= IBI_N) ? ibiIdx : 0;
  for (int i = 0; i < n; i++) seq[i] = ibi[(start + i) % IBI_N];
  float s = 0;
  for (int i = 1; i < n; i++) { float d = seq[i] - seq[i - 1]; s += d * d; }
  return sqrtf(s / (n - 1));
}

void processSample(uint32_t red, uint32_t ir) {
  if (ir < FINGER_IR) { if (finger) resetVitals(); finger = false; return; }
  if (!finger) { finger = true; resetVitals(); fingerSince = millis(); }

  // heart rate / HRV
  if (checkForBeat(ir)) {
    uint32_t now = millis();
    if (lastBeat) {
      float d = now - lastBeat;
      if (d > 300 && d < 1500) {                 // 40..200 bpm only
        ibi[ibiIdx] = d; ibiIdx = (ibiIdx + 1) % IBI_N; ibiCount++;
        if (ibiCount >= 4) {
          float h = 60000.0f / medianIbi();
          float v = rmssd();
          if (!vitalsValid) { hr = h; hrv = v; } else { hr += (h - hr) * 0.3f; hrv += (v - hrv) * 0.2f; }
          if (spo2 > 0) vitalsValid = true;
        }
      }
    }
    lastBeat = now;
  }

  // SpO2 (uncalibrated, good enough for demo)
  if (dcR == 0) { dcR = red; dcI = ir; }
  dcR += (red - dcR) * 0.005f; dcI += (ir - dcI) * 0.005f;
  float r = red - dcR, i = ir - dcI;
  sumR += r * r; sumI += i * i; nS++;
  if (nS >= 100) {                                // ~1 s at 100 Hz
    float acR = sqrtf(sumR / nS), acI = sqrtf(sumI / nS);
    if (acI > 1 && dcR > 1 && dcI > 1) {
      float R = (acR / dcR) / (acI / dcI);
      float s = constrain(110.0f - 25.0f * R, 85.0f, 100.0f);
      spo2 = (spo2 == 0) ? s : spo2 + (s - spo2) * 0.2f;
    }
    sumR = sumI = 0; nS = 0;
  }
}

void pollMax() {
  pox.check();
  while (pox.available()) {
    uint32_t red = pox.getFIFORed();
    uint32_t ir  = pox.getFIFOIR();
    pox.nextSample();
    processSample(red, ir);
  }
}
#endif

// every 1 s: alert if vitals out of range (needs ~4 s of agreement to flip = stable)
void evalStatus() {
  bool bad = vitalsValid && (spo2 < 92 || hr > 120 || hr < 50);
  if (bad) { if (alertLevel < 4) alertLevel++; } else { if (alertLevel > 0) alertLevel--; }
  if (alertLevel >= 4) alertOn = true;
  if (alertLevel == 0) alertOn = false;
}

const char* stateName() {
  if (millis() < fallUntil) return "fall";
  if (!finger) return "no_finger";
  if (!vitalsValid) return "measuring";
  return alertOn ? "alert" : "normal";
}

// ======================= outputs =======================
void updateOutputs(uint32_t now) {
  bool danger = alertOn || (now < fallUntil);
  digitalWrite(PIN_RED,   danger ? HIGH : LOW);
  digitalWrite(PIN_GREEN, (!danger && finger && vitalsValid) ? HIGH : LOW);
  // beep 200 ms every 1 s while in danger
  buzz(danger && (now % 1000) < 200);
}

void drawOled() {
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(1);
  oled.setCursor(0, 0);
  oled.printf("MDM-G3  W:%s M:%s", WiFi.status() == WL_CONNECTED ? "ok" : "--", mqtt.connected() ? "ok" : "--");
  oled.setTextSize(2);
  oled.setCursor(0, 14);
  if (vitalsValid) oled.printf("HR %d", (int)(hr + 0.5f)); else oled.print("HR --");
  oled.setTextSize(1);
  oled.setCursor(78, 14);
  if (tempPublishable()) oled.printf("T %.1fC", tempBodyC()); else oled.print("T --.-");
  oled.setCursor(0, 34);
  if (vitalsValid) oled.printf("SpO2 %d%%  HRV %d", (int)(spo2 + 0.5f), (int)(hrv + 0.5f));
  else oled.print(finger ? "Measuring..." : "Place finger");
  oled.setCursor(0, 46);  oled.printf("Motion: %s", activityName());
  oled.setCursor(0, 56);  oled.printf("State : %s", stateName());
  oled.display();
}

// ======================= network =======================
void onMsg(char* topic, byte* payload, unsigned int len) {
  String s; for (unsigned int i = 0; i < len; i++) s += (char)payload[i];
  s.trim(); s.toLowerCase();
  if (s == "recalibrate") recalRequested = true;
}

void netService(uint32_t now) {
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiWasUp) { wifiWasUp = false; Serial.println("WiFi lost"); }
    if (now - tWifi > 5000) { tWifi = now; WiFi.disconnect(); WiFi.begin(WIFI_SSID, WIFI_PASS); }
    return;
  }
  if (!wifiWasUp) {
    wifiWasUp = true;
    Serial.print("WiFi connected, IP "); Serial.println(WiFi.localIP());
  }
  if (!mqtt.connected() && now - tMqtt > 3000) {
    tMqtt = now;
    bool ok;
    if (strlen(MQTT_USER)) ok = mqtt.connect(clientId, MQTT_USER, MQTT_PASS, tStatus, 0, true, "offline");
    else                   ok = mqtt.connect(clientId, tStatus, 0, true, "offline");
    if (ok) {
      mqtt.publish(tStatus, "online", true);
      mqtt.subscribe(tCmd);
      Serial.printf("MQTT connected to %s, publishing under %s\n", MQTT_HOST, TOPIC_ROOT);
    } else {
      Serial.printf("MQTT connect failed, state %d\n", mqtt.state());
    }
  }
}

void publishMotion() {
  char b[200];
  snprintf(b, sizeof(b),
    "{\"t\":%lu,\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,\"gx\":%.1f,\"gy\":%.1f,\"gz\":%.1f,\"act\":\"%s\"}",
    millis(), ax, ay, az, gx, gy, gz, activityName());
  mqtt.publish(tMotion, b);
}

void publishVitals() {
  char b[220], tf[12];
  // "null" (valid JSON) instead of a number whenever the reading isn't trustworthy.
  // Never print NaN/inf: "nan" is not JSON and the server would drop the whole message.
  if (tempPublishable() && isfinite(tempBodyC())) snprintf(tf, sizeof(tf), "%.1f", tempBodyC());
  else strcpy(tf, "null");

  if (vitalsValid)
    snprintf(b, sizeof(b), "{\"t\":%lu,\"hr\":%d,\"spo2\":%d,\"hrv\":%d,\"temp\":%s,\"finger\":1,\"state\":\"%s\"}",
             millis(), (int)(hr + 0.5f), (int)(spo2 + 0.5f), (int)(hrv + 0.5f), tf, stateName());
  else
    snprintf(b, sizeof(b), "{\"t\":%lu,\"hr\":null,\"spo2\":null,\"hrv\":null,\"temp\":%s,\"finger\":%d,\"state\":\"%s\"}",
             millis(), tf, finger ? 1 : 0, stateName());
  mqtt.publish(tVitals, b);
}

// ======================= setup / loop =======================
void setup() {
  Serial.begin(115200);
  Serial.println("\nMDM G3 health node starting");
  pinMode(PIN_GREEN, OUTPUT); pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_RECAL, INPUT_PULLUP);
  buzzInit();
#if SIM_MODE
  pinMode(PIN_FINGER, INPUT_PULLUP);
#endif
  tempInit();

  Wire.begin(21, 22);
  Wire.setClock(400000);
  oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
  oled.clearDisplay(); oled.setTextColor(SSD1306_WHITE); oled.setCursor(0, 0);
  oled.println("Starting..."); oled.display();

  mpuInit();
  oled.println("Calibrating - hold still"); oled.display();
  calibrateGyro();

#if !SIM_MODE
  if (!pox.begin(Wire, I2C_SPEED_FAST)) { oled.println("MAX30102 not found!"); oled.display(); Serial.println("MAX30102 not found"); }
  pox.setup(0x3F, 1, 2, 100, 411, 16384);   // LED current, avg 1, red+IR, 100 Hz, 411us, range
#endif

  snprintf(tVitals, 64, "%s/vitals", TOPIC_ROOT);
  snprintf(tMotion, 64, "%s/motion", TOPIC_ROOT);
  snprintf(tEvent,  64, "%s/event",  TOPIC_ROOT);
  snprintf(tStatus, 64, "%s/status", TOPIC_ROOT);
  snprintf(tCmd,    64, "%s/cmd",    TOPIC_ROOT);
  snprintf(clientId, 32, "g3-esp32-%04X", (uint16_t)(ESP.getEfuseMac() >> 32));

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                       // steadier MQTT stream
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(250);

#if MQTT_TLS
  net.setInsecure();   // MQTT_TLS_VERIFY 1: replace with net.setCACert(ROOT_CA)
#endif
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(15);
  mqtt.setCallback(onMsg);
}

void loop() {
  uint32_t now = millis();

  netService(now);
  if (mqtt.connected()) mqtt.loop();

#if !SIM_MODE
  pollMax();                                   // keep FIFO drained every pass
#else
  if (now - tSim >= 100) { tSim = now; simUpdate(); }
#endif

  // temperature: sample at 5 Hz, remember when the finger was placed
  if (now - tTemp >= 200) { tTemp = now; tempSample(); }
  if (finger && !fingerPrev) fingerOnAt = now;
  fingerPrev = finger;

  // recalibrate button (or MQTT cmd)
  if (now - tBtn >= 50) {
    tBtn = now;
    static bool last = HIGH;
    bool cur = digitalRead(PIN_RECAL);
    if (last == HIGH && cur == LOW) recalRequested = true;
    last = cur;
  }
  if (recalRequested) {
    recalRequested = false;
    oled.clearDisplay(); oled.setCursor(0, 20); oled.setTextSize(1);
    oled.println("Recalibrating..."); oled.display();
    calibrateGyro(); resetVitals(); alertLevel = 0; alertOn = false;
    buzz(true); delay(80); buzz(false);
  }

  if (now - tMpu >= 20)  { tMpu = now;  motionSample(); }     // 50 Hz
  if (now - tAct >= 500) { tAct = now;  evalActivity(); }
  if (now - tStat >= 1000) { tStat = now; evalStatus(); }

  updateOutputs(now);

  if (mqtt.connected()) {
    if (fallEventPending) { fallEventPending = false; mqtt.publish(tEvent, "{\"type\":\"fall\"}"); }
    if (now - tPubM >= MOTION_MS) { tPubM = now; publishMotion(); }
    if (now - tPubV >= VITALS_MS) { tPubV = now; publishVitals(); }
  }

  if (now - tOled >= 333) { tOled = now; drawOled(); }

  // one status line every 5 s on the serial monitor (115200 baud)
  if (now - tLog >= 5000) {
    tLog = now;
    Serial.printf("wifi:%s mqtt:%s finger:%d state:%s hr:%d spo2:%d skinT:%.1fC temp:%s\n",
                  WiFi.status() == WL_CONNECTED ? "ok" : "--", mqtt.connected() ? "ok" : "--",
                  finger ? 1 : 0, stateName(), (int)(hr + 0.5f), (int)(spo2 + 0.5f),
                  isnan(tempSkinC) ? 0.0f : tempSkinC, tempPublishable() ? "sent" : "null");
  }
}
