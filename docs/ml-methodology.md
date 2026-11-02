# Machine learning methodology

QueuePilot predicts **how many minutes a customer will wait before service starts**. This document states
exactly what is predicted, from what, how models are compared, and what the results do and do not mean.

## 1. Target and prediction moment

* **Target:** `waiting_time` = `service_start_time - join_time`, in minutes (measured by the server when staff start service).
* **Prediction moment:** when a customer joins (stored on the ticket and logged), and again, without logging, each
  time the ticket is viewed while waiting (the *live estimate*). Accuracy is always evaluated against the
  **original join-time prediction**, because that is what the customer was told.

## 2. Inputs (features)

All inputs are known at the prediction moment and are derived on the server from the database, never from the client.

| Feature | Meaning |
|---|---|
| `service_type` | service prefix (GEN, PAY, ...) - categorical, one-hot encoded |
| `people_ahead` | WAITING tickets of the same service in front of the customer |
| `queue_length` | WAITING tickets of that service, including the customer |
| `active_counters`, `busy_counters` | OPEN counters for the service; how many hold a customer |
| `average_service_duration` | mean of the last 20 completed services for that service (service default if none) |
| `staff_count` | distinct staff assigned to OPEN counters of the service |
| `hour`, `day_of_week`, `peak_hour` | local time; peak hours are 9, 10, 11, 14, 15 (an adjustable assumption in `ml/features.py`) |
| engineered: `available_counters`, `load_ratio`, `workload_minutes` | deterministic functions of the above (`active - busy`, `people_ahead / active`, `load_ratio x average_service_duration`) |

Not included (and why): *recent arrival rate* and *historical waiting times* are left for the Phase 8 recommendation engine;
`available_counters` is exactly `active - busy`, so it is engineered rather than separate.

## 3. Leakage prevention

* `waiting_time` (target) and `service_duration` (known only after service ends) are never inputs. `date` is used only to split.
* `FeatureBuilder`, the first step of every pipeline, selects only the allowed columns, so an extra column cannot slip in
  (verified by a test that tampers with the target and checks the features are unchanged).
* Scaling and encoding are steps **inside the sklearn Pipeline** and are fitted on training rows only (verified by a test
  comparing the fitted scaler's means with the training-set means).
* Historical rows use the feature snapshot saved **at prediction time**, not values recomputed later.

## 4. Data

* **Synthetic (default for development).** `flask ml-generate-data` / `ml-train`. Reproducible from a seed. Generated from
  assumed relationships: more people ahead, fewer free counters, longer service times and peak hours all lengthen waits;
  services differ in duration; noise is multiplicative (growing with the line) plus additive. Each assumption is checked by a test.
  **It is not real data.** Its scores demonstrate that the pipeline works, not how accurate it would be at a real organisation.
* **Historical.** Completed tickets that have a logged prediction (features snapshot + measured wait). Needs at least 200 usable
  rows over at least 5 days; otherwise training refuses with a clear message.
* **Mixed.** Synthetic rows followed by historical rows. Useful for bootstrapping; treat results with care.
* **Cleaning.** Rows with missing/non-numeric values, impossible values (negative counts or waits, busy > active, people ahead
  >= queue length, hour or weekday out of range) are dropped and counted in the run's `cleaning` report.

## 5. Evaluation strategy

1. **Chronological split by whole days:** first 60% of days train, next 20% validation, last 20% test. A model never trains on days later than the days it is scored on.
2. All three models are fitted on the training days only.
3. **Selection** uses validation MAE (ties: lower RMSE, then name). Metrics are compared at 4 decimals.
4. **Reporting** uses the test days, which played no part in fitting or selection: MAE and RMSE (minutes) and R^2.
5. **Eligibility:** a model can be activated only if its metrics are finite and test R^2 > 0 (it must beat predicting the mean).
6. A **rule-based baseline** (the fallback formula) is scored on the same splits for context. It is not a trained model.

Models: Linear Regression; Random Forest (150 trees, min leaf 3); Gradient Boosting (200 trees, learning rate 0.05, depth 3).
No hyperparameter search was performed. Models are not refit on train+validation after selection.

## 6. Results on the default synthetic run (seed 42, 6000 rows)

Measured by `flask ml-train`; reproducible, but **synthetic**.

| Model | Validation MAE | Test MAE (min) | Test RMSE (min) | Test R^2 |
|---|---|---|---|---|
| Linear Regression (selected) | 5.761 | 5.584 | 9.098 | 0.920 |
| Random Forest | 5.887 | 5.524 | 9.451 | 0.913 |
| Gradient Boosting | 5.761 | 5.386 | 9.338 | 0.915 |
| Rule-based baseline | 9.063 | 8.265 | 13.561 | 0.822 |

How to read this honestly:
* The three models are close. The engineered `workload_minutes` feature already captures most of the structure of the synthetic process, so a linear model competes.
* Linear Regression and Gradient Boosting tie on validation MAE to four decimals (5.76143117 vs 5.76143036 unrounded; their predictions differ by up to 37 minutes). The tie is decided by RMSE. Gradient Boosting has the lowest *test* MAE, which is not used for selection by design.
* All three beat the baseline, but this only shows the learned models fit this generator, not that they would beat the rule in a real queue.
* Other seeds (6000 rows each, measured, not assumed):

  | Seed | Selected on validation MAE | Test MAE LR / RF / GB | Lowest test MAE |
  |---|---|---|---|
  | 1 | Gradient Boosting | 5.98 / 5.82 / 5.73 | Gradient Boosting |
  | 2 | Gradient Boosting | 5.50 / 5.44 / 5.21 | Gradient Boosting |
  | 3 | Gradient Boosting | 5.31 / 5.42 / 5.30 | Gradient Boosting |
  | 4 | Linear Regression | 5.35 / 5.42 / 5.17 | Gradient Boosting |
  | 5 | Linear Regression | 5.75 / 5.47 / 5.42 | Gradient Boosting |

  The validation-based choice is unstable because the models are so close (it picked Linear Regression for seeds 4, 5 and 42),
  while Gradient Boosting has the lowest test MAE in all six runs. Differences are small (a few tenths of a minute), so do not
  treat any single run as a definitive ranking; a more robust protocol (several seeds or time-series cross-validation) is future work.

## 7. Serving, fallback and logging

* The active model is loaded from `ML_ARTIFACT_DIR` (path checked to stay inside that folder) and cached in memory.
* No active model, or a load/predict error: the documented **fallback** is used and labelled `fallback` with a `reason`.
* No open counter for the service: no estimate (`unavailable`). The model was never trained on zero-counter situations.
* Every ticket-time prediction is stored in `prediction_logs` with features, source and model version; the measured wait and signed error (`prediction - actual`) are added when service starts. Cancelled, skipped and absent tickets never receive an outcome.

## 8. Limitations

* Results are only as good as the data. Synthetic scores prove nothing about a real organisation; collect real tickets, then train on `historical` or `mixed` data.
* The live estimate reuses the join-time model with the current line; it assumes the remaining wait depends on people ahead, not on how long the customer already waited.
* Counters serve one service; staff breaks, no-shows beyond "absent", and arrival bursts are not modelled.
* Model files depend on the scikit-learn version used to train them; retrain after upgrading it (the version is stored with each model).
* Time-of-day features use the configured `APP_TIMEZONE`.
