# Edge AI and the Personalization Pipeline

This document covers the machine-learning side of the project: data, features, calibration, models, measured results, exported artifacts, and what it will take to move inference onto the ESP32.

Current state: the server performs inference. A TFLite model is exported but is not used by the firmware or the server. The ESP32 does not yet read temperature or run a model.

## Research objective

Detect abnormal physiological states from multimodal wearable signals while adapting to each person's normal baseline, and keep the final inference small enough to run at the edge.

The prototype maps that objective to a concrete question:

> Given 30 seconds of heart rate, SpO2, temperature, and accelerometer data, can a model separate `normal` from `stress` windows better than fixed thresholds, and can the model be personalized from a short calibration period?

## Dataset

Primary dataset: **PhysioNet Non-EEG Dataset for Assessment of Neurological Status** (<https://physionet.org/content/noneeg/1.0.0/>).

| Property | Value |
|---|---|
| Subjects | 20 healthy adults |
| HR and SpO2 | 1 Hz |
| Temperature and 3-axis accelerometer | 8 Hz |
| EDA | 8 Hz (deliberately excluded; the prototype hardware does not measure it) |
| Labels | Relaxation plus physical, cognitive, and emotional stress stages |
| Access | Open |

The notebook downloads the official ZIP at runtime inside Colab or Kaggle. The dataset is not committed to the repository.

Label handling:

- `Relax` -> `normal` (0)
- `PhysicalStress`, `CognitiveStress`, `EmotionalStress` -> `stress` (1)
- Annotation symbols and notes are printed during the run. If the mapping is ambiguous, `MANUAL_STAGE_MAP` in the notebook takes precedence.

A window is labelled only if at least 80% of its probe points share one stage; ambiguous boundary windows are dropped.

### Why this dataset

It is the closest open dataset to the hardware modalities (HR, SpO2, temperature, acceleration) and it contains labelled normal and stress periods for every subject, which supports per-subject calibration and leave-one-subject-out evaluation.

### Limitations of the dataset

- HR and SpO2 are computed values, not raw PPG.
- Stress is induced in a lab, not a disease or a clinical outcome.
- There are no fall labels. Falls remain rule-based in firmware and server.
- Twenty subjects is small; per-fold variance is large.
- The dataset has no raw MAX30102 or MPU6050 streams, so sensor-level noise is not reproduced exactly.

## Preprocessing

| Setting | Value |
|---|---|
| Window length | 30 s |
| Step | 15 s (50% overlap) |
| Sampling after alignment | Accelerometer/temperature resampled to the 8 Hz grid; HR/SpO2 interpolated onto it |
| Missing values | Linear interpolation inside the notebook; server skips non-finite samples |
| Calibration period | First 120 s of `normal` windows per subject/device |
| Minimum calibration windows | 4 |

## Features

Fifteen features are computed per window. The same names and order are shared by the notebook, the exported artifacts, and the server.

| Group | Features | Definition |
|---|---|---|
| Heart rate | `hr_mean`, `hr_std`, `hr_min`, `hr_max`, `hr_slope` | Mean, population std, min, max, least-squares slope over the window |
| SpO2 | `spo2_mean`, `spo2_std`, `spo2_min` | Mean, population std, min |
| Temperature | `temp_mean`, `temp_std`, `temp_slope` | Mean, population std, least-squares slope |
| Motion | `acc_mean`, `acc_std`, `acc_max`, `acc_energy` | Magnitude `sqrt(ax^2 + ay^2 + az^2)`: mean, std, max, mean squared value |

Notes:

- True HRV requires beat-to-beat intervals, which this dataset does not provide. `hr_std` and `hr_slope` are used as variability proxies. The dashboard's `hrv` display comes from the firmware, not from the training features.
- EDA is excluded so that the deployed feature set matches the hardware.
- The server receives motion at 10 Hz (firmware publish rate) while training used 8 Hz. Mean/std/max are comparable, but this is a real domain shift and should be validated on hardware.
- Firmware publishes vitals at 2 Hz while training data is 1 Hz. The 30-second window still contains enough samples.

## Models evaluated

The notebook evaluates both global and personalized approaches under leave-one-subject-out (LOSO) cross-validation:

- **Fixed thresholds**: the server's rule engine, used as a reference rather than trained.
- **Logistic regression**: global, standardized features.
- **Linear SVM**: global, standardized features.
- **Random forest**: 300 trees, max depth 8, minimum 5 samples per leaf.
- **Isolation forest**: unsupervised, trained on normal windows.
- **Personal robust z-score**: per-subject median/MAD distance, thresholded.
- **Personal Mahalanobis**: per-subject full covariance distance.
- **Personal logistic regression**: per-subject median/MAD normalization followed by a shared logistic regression.

For personalized models, normalization statistics come from the first 120 seconds of that subject's normal windows. The model is then evaluated on the remaining windows.

## Results

Source: `data/model_artifacts/loso_summary.csv` (20 folds). Metrics are means across held-out subjects.

| Model | Balanced accuracy | ROC AUC | F1 | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| Random forest | **0.781 +/- 0.142** | **0.891** | 0.782 | 0.807 | 0.797 |
| Logistic regression (global) | 0.767 +/- 0.118 | 0.886 | 0.748 | 0.820 | 0.747 |
| Linear SVM | 0.763 +/- 0.128 | 0.890 | 0.745 | 0.820 | 0.734 |
| Personal logistic regression | 0.724 +/- 0.109 | 0.864 | 0.701 | 0.802 | 0.694 |
| Isolation forest | 0.641 +/- 0.079 | 0.742 | 0.534 | 0.763 | 0.434 |
| Personal robust z-score | 0.517 +/- 0.019 | 0.803 | 0.684 | 0.520 | 1.000 |
| Personal Mahalanobis | 0.500 +/- 0.000 | 0.725 | 0.677 | 0.511 | 1.000 |

Observations:

- The random forest has the best mean balanced accuracy, but the margin over logistic regression is about 1.4 points and the per-subject standard deviation is large.
- Global logistic regression and linear SVM are nearly tied with the forest and are much easier to deploy.
- The unsupervised personal baselines (`robust z`, `Mahalanobis`) flag nearly every stress window: recall is 1.000 while precision is near 0.51, so balanced accuracy collapses to chance. They are not usable as deployed detectors with the current threshold.
- The personal logistic regression is the best *personalized* model and is the artifact used by the server. It trades about 4 points of balanced accuracy versus the global logistic regression in exchange for per-device calibration.
- The global models are trained on all subjects and can overfit subject identity; the LOSO numbers are the honest generalization estimate.

## Exported artifacts

All artifacts live in `data/model_artifacts/`.

| File | Purpose |
|---|---|
| `model_personal_logreg.json` | **Deployed on the server**. Shared logistic coefficients plus median/MAD normalization contract; center/scale are computed per device at runtime |
| `model_lr.json` | Global standardized logistic regression reference |
| `model_robust_z.json` | Diagonal per-device baseline (small enough for a MCU, but poor results) |
| `model_mahalanobis_server.json` | Full-covariance baseline for server experiments |
| `model_mlp.tflite` | Quantized 15-24-12-1 MLP, 4,940 bytes, exported for TFLite Micro |
| `model_mlp.h` | C array of the same TFLite model |
| `model_mlp_meta.json` | MLP feature order, standard-scaler mean/scale, threshold, TFLite size |
| `deployment_contract.json` | Feature order, window/step, sampling rates, label map, excluded signals |
| `loso_summary.csv` | Aggregate LOSO metrics per model |
| `loso_folds.csv` | Per-fold metrics |
| `loso_predictions.csv` | Per-window predictions and scores |
| `loso_metrics.png` | Model comparison and confusion matrix |
| `windows.csv` | Extracted feature windows used for training/evaluation |

The server model contract:

```text
normalize: x' = (x - median) / max(1.4826 * MAD, 1e-6)
score:     sigmoid(intercept + sum(coefficient[i] * x'[i]))
levels:    >= 0.8 alert, >= 0.5 watch, else normal
```

The artifact contains the coefficients and intercept, but not the per-device center/scale. Those are learned online from the first 120 seconds of normal windows, which is what makes the model personal.

## Server integration

`server/mqtt_ingest.py` loads `model_personal_logreg.json` at startup when `MODEL_ENABLED=1` (default). `server/model.py` maintains a `DeviceBuffer` per `device_id` and exposes state through `GET /api/model`.

Verified behavior (local run):

- A simulator published 62 seconds of normal data, then 45 seconds of stress.
- The device buffer calibrated with 4 windows (120-second artifact period overridden to 20 seconds for the test).
- The model produced `score 1.0`, `level alert`, `source model` on the stress data.
- The rule engine independently produced alerts for the elevated simulated heart rate.

This confirms the training artifact loads and scores correctly. It does not validate clinical accuracy.

## ESP32 feasibility

Typical ESP32-WROOM class hardware: 240 MHz dual-core, 520 KB SRAM, 4 MB flash, single-precision FPU.

| Model | Runs on ESP32? | Notes |
|---|---|---|
| Robust z-score / Mahalanobis | Yes | A few arrays and dot products |
| Logistic regression | Yes | 15 coefficients plus intercept; trivial |
| Linear SVM | Yes | Coefficients plus bias; trivial |
| Tiny MLP (15-24-12-1) | Yes, via TFLite Micro | Exported model is 4,940 bytes; tensor arena and runtime overhead must be measured |
| Random forest / isolation forest | Gateway or server | 100+ trees are a poor fit for MCU memory |
| Deep learning | No | Beyond memory and compute budget |

The model runs every 15 seconds on a 30-second window. That cadence is well within the ESP32's capability; the difficult part is feature extraction and maintaining calibration buffers, not the inference itself.

### What is missing on-device

1. **Temperature**: the firmware does not read or publish temperature. The planned LM35 on `D33` is documented in [hardware.md](hardware.md).
2. **Feature computation**: the firmware does not accumulate 30-second windows or compute the 15 features.
3. **Calibration**: there is no on-device median/MAD estimation or storage of per-device normalization.
4. **Inference**: TFLite Micro is not linked, and no model bytes are loaded.
5. **Benchmarking**: latency, heap use, and flash size have not been measured.
6. **Anomaly publishing**: the server publishes anomalies; the device does not.

## Proposed on-device integration

Two valid topologies:

**A. Edge inference (target for the "Edge AI" claim)**

```text
ESP32 sensors -> 30 s buffers -> 15 features -> normalize -> logreg or TFLite MLP
             -> local alert (buzzer/LED) + publish anomaly + vitals/motion
```

**B. Gateway/server inference (current)**

```text
ESP32 -> MQTT -> server buffers/features/model -> anomaly -> dashboard
```

Topology B is already working and should remain the fallback. Topology A is the remaining edge work.

### Recommended implementation order

1. Add LM35 on `D33`, convert ADC to Celsius, include `temp` in the vitals payload, and verify against the dashboard and server.
2. Add rolling buffers for vitals and motion at the publish rates (60 vitals samples and 300 motion samples for 30 seconds at 2 Hz and 10 Hz; roughly 5-10 KB of floats depending on layout).
3. Port `compute_features` exactly (same names, same order, same slope definition). Add a unit-style comparison against the Python implementation using a recorded sequence.
4. Choose one of two inference paths:
   - **Logistic regression**: store 15 coefficients, the intercept, and calibration median/MAD arrays. This is the simplest and most explainable option. Calibration still needs a 120-second normal period.
   - **TFLite MLP**: use `model_mlp.h`, add the TensorFlow Lite Micro library, apply `model_mlp_meta.json` mean/scale, and invoke every 15 seconds. This demonstrates "Tiny ML on MCU" but adds flash/RAM overhead.
5. Reuse the existing anomaly payload and publish it with `source: "edge"`. Decide whether the server should skip its own model for devices that publish edge anomalies, to avoid duplicate alerts.
6. Benchmark and record:
   - feature extraction time (microseconds per window),
   - inference time (`micros()` around `Invoke()`),
   - free heap before/after invocation,
   - flash usage from the compiled binary,
   - model bytes (4,940 for the MLP).
7. Compare edge results against the server model on the same recorded replay to catch feature drift.

### Calibration considerations on-device

- The deployed logistic regression expects per-device median/MAD normalization. On a device, statistics must be computed from the first 120 seconds of normal windows and stored in RAM or NVS.
- The MLP uses a fixed global scaler from `model_mlp_meta.json`, so it needs no per-device calibration. That makes the MLP easier to deploy but less personalized.
- The rule engine should gate calibration: only collect calibration windows while rules report `normal`.
- A `recalibrate` command should clear both sensor baselines and model calibration.

## Evaluation gaps

The current results support a model comparison, not the full synopsis experiment matrix. Missing experiments:

- fixed thresholds vs personal/global models on the same test windows,
- single-modality vs multimodal ablation (HR only, HR+SpO2, +temperature, +motion),
- noise and motion-artifact robustness,
- threshold and calibration-length sensitivity,
- edge vs cloud latency, memory, and model-size comparison,
- hardware-in-the-loop validation with the actual MAX30102/MPU6050/LM35.

See [experiments.md](experiments.md) and [roadmap.md](roadmap.md).

## Responsible-use notes

This is a research and demonstration prototype, not a medical device. The dataset labels are induced stress states, not diagnoses. Do not use the output for clinical decisions or with real patient data on the public broker.
