# Experiments and Evaluation

This document records the research protocol and the results that exist today, separates measured facts from open work, and explains how to reproduce the run.

## Research questions

1. Can multimodal wearable features separate normal from stress better than fixed thresholds?
2. Does personal calibration improve detection over a global model?
3. Which model is accurate enough and small enough to deploy at the edge?
4. What is the cost of edge inference compared with server/cloud inference?

Only questions 1-3 have partial evidence. Question 4 has no measurements yet.

## Protocol

| Item | Choice |
|---|---|
| Dataset | PhysioNet Non-EEG Dataset for Assessment of Neurological Status, 20 subjects |
| Inputs | HR and SpO2 at 1 Hz; temperature and 3-axis acceleration at 8 Hz |
| Excluded input | EDA (not measured by the prototype hardware) |
| Window | 30 seconds |
| Step | 15 seconds (50% overlap) |
| Label | Relax = normal; physical/cognitive/emotional stress = stress |
| Validation | Leave-one-subject-out across all 20 subjects |
| Calibration | First 120 seconds of each subject's normal windows |
| Metrics | Balanced accuracy, ROC AUC, F1, precision, recall |
| Reference | Server rule engine (fixed thresholds) |

Personalized models normalize each subject's features using the median and scaled MAD from that subject's calibration period, then share a model across subjects. Global models standardize with statistics from the training subjects only.

## Results

The table below is copied from `data/model_artifacts/loso_summary.csv` and rounded. Values are mean +/- standard deviation across the 20 held-out subjects.

| Model | Balanced accuracy | ROC AUC | F1 | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| Random forest | **0.781 +/- 0.142** | **0.891** | 0.782 | 0.807 | 0.797 |
| Logistic regression (global) | 0.767 +/- 0.118 | 0.886 | 0.748 | 0.820 | 0.747 |
| Linear SVM | 0.763 +/- 0.128 | 0.890 | 0.745 | 0.820 | 0.734 |
| Personal logistic regression | 0.724 +/- 0.109 | 0.864 | 0.701 | 0.802 | 0.694 |
| Isolation forest | 0.641 +/- 0.079 | 0.742 | 0.534 | 0.763 | 0.434 |
| Personal robust z-score | 0.517 +/- 0.019 | 0.803 | 0.684 | 0.520 | 1.000 |
| Personal Mahalanobis | 0.500 +/- 0.000 | 0.725 | 0.677 | 0.511 | 1.000 |

Related files:

- `data/model_artifacts/loso_folds.csv` - per-subject metrics for every model.
- `data/model_artifacts/loso_predictions.csv` - per-window truth, prediction, and score.
- `data/model_artifacts/loso_metrics.png` - bar chart and confusion matrix.
- `data/model_artifacts/windows.csv` - feature windows used in evaluation.

## Interpretation

- The random forest is the best mean performer, but its advantage over global logistic regression (1.4 balanced-accuracy points) is small relative to the between-subject standard deviation (about 12-14 points). Reporting only the mean would overstate confidence.
- Global logistic regression and linear SVM are essentially tied with the forest and are far easier to deploy.
- The deployed personal logistic regression reaches 0.724 balanced accuracy. It is not the top model; it is the best model that is both personalized and trivially deployable.
- The personal robust z-score and Mahalanobis baselines are not usable with their current thresholds: they label almost everything as stress (recall 1.0, precision near 0.51). Their AUC is not meaningless, which suggests the distance score carries signal but the threshold does not.
- Isolation forest underperforms the supervised models, as expected for this small, labelled dataset.

## Verification performed

Besides the offline LOSO run, the deployed model path was checked end to end:

1. Started the server with `MODEL_CALIBRATION_SECONDS=20` and a scratch database.
2. Published 62 seconds of normal data from the simulator.
3. Published 45 seconds of stress data.
4. `GET /api/model` reported `ready: true`, `calibration_windows: 4`, and `last_result: {score: 1.0, level: alert, source: model}`.
5. `GET /api/anomalies` contained both rule-based and model-based rows.

This proves the artifact loads, the calibration path works, and the model scores live data. It does not establish clinical validity.

## Reproducing the training run

The notebook refuses to run on a normal workstation and must run in Colab or Kaggle. This is deliberate: TensorFlow/PyTorch are not installed on the project PC.

1. Open `notebooks/noneeg_training.ipynb` in Colab or Kaggle.
2. Run all cells.
   - It downloads the official Non-EEG ZIP (about 3.9 MB) from PhysioNet.
   - It prints annotation labels and the resulting stage mapping.
   - It builds windows, runs LOSO for each model, and writes the metrics plot.
   - It refits deployment artifacts and exports TFLite/header files.
3. Download or copy the generated `noneeg_artifacts.zip`.
4. Extract into `data/model_artifacts/`, replacing the committed copies.
5. Re-run the unit tests and a short simulator check after changing artifacts.

The notebook is self-contained: running it again on the same dataset reproduces the windows and metrics deterministically (fixed random seeds), but library version changes can shift results slightly. Record the Colab/Kaggle environment when reporting final numbers.

## Threats to validity

- **Dataset mismatch**: HR/SpO2 are computed, not raw PPG; the prototype's MAX30102 signal path is not represented.
- **Population**: 20 healthy adults, lab-induced stress; not patients, not disease.
- **No fall labels**: falls are evaluated only as a firmware heuristic.
- **Class balance**: windows are not equally distributed across subjects and stages; class weighting is used but does not remove the issue.
- **Sampling-rate shift**: training acceleration is 8 Hz; the deployed stream is 10 Hz (published from 50 Hz sampling), and vitals are 2 Hz vs 1 Hz in training.
- **Small sample**: 20 folds produce wide confidence intervals; no significance test has been run.
- **Personalization protocol**: calibration uses the held-out subject's first normal windows, which is appropriate for a personalized system but means the evaluation is not "zero-shot" on a new user.
- **No noise injection**: sensor noise, motion artifacts, and packet loss are not part of the current evaluation.
- **Single run**: no repeated seeds or nested hyperparameter search.

## Experiments still required

The synopsis calls for a fuller matrix. These are not yet implemented:

| Experiment | Goal |
|---|---|
| Fixed thresholds vs models | Compare the server rule engine against trained models on identical windows |
| Modality ablation | HR only; HR+SpO2; +temperature; +motion; full set |
| Noise/motion robustness | Add Gaussian noise, dropouts, and motion artifacts; measure degradation |
| Calibration-length sensitivity | 30 s, 60 s, 120 s, 300 s of normal data |
| Threshold sensitivity | Precision/recall trade-off for watch/alert thresholds |
| Edge vs cloud | Latency, heap, flash, and power for on-device vs server inference |
| Hardware-in-the-loop | Record real MAX30102/MPU6050/LM35 sessions and replay them |
| User-level reporting | Show per-subject results, not only aggregate means |

## Reporting guidance

When presenting results:

- State that labels are induced stress, not diagnoses.
- Report per-subject spread, not only means.
- Include the rule-based reference; it is the baseline a clinician-facing system must beat to be worth the complexity.
- Do not claim ESP32 inference has been demonstrated until the firmware integration and benchmarks exist.
