# Model Card: Liquidity (Shortfall) Model

All data is **simulated**. No real upay user, transaction, balance or fee data was used.

## What it predicts
At the end of day 20 of a month, the model gives the chance that the user's simulated wallet balance falls below 500 BDT (`SHORTFALL_FLOOR_BDT`) on any day from 21 to 30. If that chance is at or above the alert threshold, the user gets an alert.

A second, helper model predicts the lowest balance on days 21-30 in BDT. It is only used to size a suggested buffer in the app. The alert always comes from the first model.

## Features (days 1-20 only)
| Feature | Meaning |
|---|---|
| balance_day20 | Balance at the end of day 20 |
| min_balance_d1_20 | Lowest balance on days 1-20 |
| avg_daily_spend_d1_20 | Merchant, bill, recharge and family-send spending per day |
| total_inflow_d1_20 | Money received (income and top-ups) |
| total_outflow_d1_20 | All money out, including cash-out fees |
| cashout_count_d1_20 | Number of agent cash-outs |
| cashout_amount_d1_20 | Amount cashed out |
| days_since_last_inflow | Days since money last came in (20 if none this month) |
| bill_payments_d1_20 | Number of bill payments |
| prev_month_shortfall | 1 if last month had a shortfall, blank for the first month |
| inflow_vs_prev_month | Days 1-20 inflow divided by last month's full inflow (blank if unknown) |

`income_band`, `region` and `age_band` are **never** model inputs. They are only used to check fairness.

**Leakage test:** we delete every row after day 20 of the month being predicted, rebuild the features and confirm they are identical. Result: PASS.

## Split and validation
- **Train:** months 0-3 (4,000 user-months). **Test:** months 4-5 (2,000 user-months). The split is by time, never random.
- **Choosing settings (training months only):** month 2 is predicted by a model trained on months 0-1, and month 3 by a model trained on months 0-2. On those pooled 2,000 predictions we pick, by best F1, the model's alert threshold (**0.2775**) and the rule's cut-off X (**2,151 BDT**).
- The final model is then trained on all of months 0-3 with the same fixed settings: 300 trees, depth 4, learning rate 0.05. The test months were never used to choose anything.
- **Monotone constraint:** the model is forced so that a higher `balance_day20` can never raise the risk. Every other feature is unconstrained. We added it because, in the first run without it, 15.2% of test rows got a *higher* risk when 1,000 BDT was added to their balance, which makes no sense to a user. The constraint was added once, after that first run, as a domain-knowledge decision (a higher balance should never raise risk). There was no further tuning.

## Baselines
- **Rule:** alert if balance on day 20 < 2,151 BDT.
- **Persistence:** alert if the user had a shortfall last month.

## Results (test months 4-5)
**View 1: all user-months** (2,000 rows, 464 shortfalls)

| Method | ROC-AUC | PR-AUC | Precision | Recall | F1 |
|---|---|---|---|---|---|
| Rule | 0.843 | 0.736 | 0.731 | 0.610 | 0.665 |
| Persistence | 0.620 | 0.302 | 0.378 | 0.478 | 0.422 |
| Model | 0.853 | 0.761 | 0.681 | 0.653 | 0.667 |

At equal alert volume (387 alerts each): rule recall 0.610, precision 0.731; model recall 0.623, precision 0.747.

**View 2 (headline): user-months not already below 500 BDT on day 20** (1,783 rows, 259 shortfalls)

| Method | ROC-AUC | PR-AUC | Precision | Recall | F1 |
|---|---|---|---|---|---|
| Rule | 0.727 | 0.392 | 0.459 | 0.301 | 0.364 |
| Persistence | 0.601 | 0.187 | 0.240 | 0.436 | 0.310 |
| Model | 0.745 | 0.422 | 0.430 | 0.378 | 0.403 |

At equal alert volume (170 alerts each): rule recall 0.301, precision 0.459; model recall 0.324, precision 0.494.

**Who caught what (View 1):** 464 shortfalls. The rule caught 283 and the model caught 303. 29 were caught only by the model and 9 only by the rule.

**Lead time:** for the 303 shortfalls the model caught, the first dip came a mean of 2.05 days (median 1 day) after day 20.

**Uncertainty (bootstrap over users, 200 resamples, View 2), model minus rule:**
- PR-AUC: mean +0.031, 95% interval [-0.002, +0.069]
- Recall at equal alert volume: mean +0.025, 95% interval [-0.010, +0.061]

**Honest summary:** the model's lead over the simple day-20 balance rule is **small**. Both 95% intervals include zero, so we cannot claim a clear win. On this simulated data, most of the signal is in the day-20 balance. The model catches 29 shortfalls the rule misses (against 9 the other way), but part of that is volume. With its learned threshold, the model raises more alerts than the rule: 445 against 387 on the test months (from `artifacts/test_predictions.csv`). At equal alert volume, the View 2 recall gain is only +0.025 (bootstrap mean), with a 95% interval of [-0.010, +0.061]. In View 1, the model's precision (0.681) is lower than the rule's (0.731). Its other practical extra is that it gives reasons for each alert.

**Calibration:** Brier score 0.102. Predicted risk tracks the actual rate at the low end. From 0.2 upwards the model is somewhat over-confident. For example, the 0.5-0.6 bin has a mean prediction of 0.544 but an actual rate of 0.355 (only 31 rows).

**Sanity checks**
- A model trained on shuffled labels scores test ROC-AUC 0.520, close to chance as expected.
- Adding 1,000 BDT to the day-20 balance lowers the risk for 62.6% of rows, raises it for 0.0% and leaves it unchanged for 37.4% (rows already far from risk). The monotone constraint works.
- Trained on 70% of users and tested on the other 30% (users the model has never seen), View 2 PR-AUC is 0.433, against 0.429 for the main model on the same users. So the model does not depend on having seen a user before.

**Helper model (minimum balance):** mean absolute error is 2,153 BDT (2,241 BDT on shortfall rows). The naive guess "minimum = day-20 balance" has an error of 3,040 BDT (3,245 BDT on shortfall rows).

**What drives predictions (mean absolute SHAP, TreeExplainer):** balance_day20 (1.742) is by far the strongest. Next come avg_daily_spend_d1_20 (0.351), total_inflow_d1_20 (0.310), bill_payments_d1_20 (0.248) and min_balance_d1_20 (0.173). cashout_count_d1_20 (0.059) and prev_month_shortfall (0.018) matter least.

## Fairness findings (test months, model alerts)
| Column | Largest recall gap | Largest false-alarm gap | Note |
|---|---|---|---|
| income_band | 0.050 | 0.038 | mid band has the lowest false-alarm rate (0.075) |
| region | 0.088 | 0.032 | Rajshahi lowest recall (0.615), Khulna highest (0.703) |
| age_band | 0.149 | 0.045 | 51+ highest recall (0.766), 18-25 lowest (0.617); 36-50 highest false alarms (0.123) |

No group is below 150 rows, so none is marked LOW SAMPLE. The groups only differ through income-band shares and a small city shift in the simulation. So these gaps are most likely sampling noise: the 51+ group has 240 rows and about 47 shortfalls. We did not tune anything to close the gaps. They should be re-checked on real data.

## Limitations
- **Simulated data.** All behaviour comes from the assumptions in `docs/data_assumptions.md`. Real users may be more or less predictable.
- **Festival month is in training only.** Month 3, the festival month, has the highest shortfall rate (0.339). The test months 4-5 are ordinary months, so we have not tested how the model does in a festival month.
- **Same users in training and test.** The test months use the same 1,000 users seen in training. The 70/30 user check suggests this does not inflate results much, but it is not a test on a new population.
- **Sweep cash-outs.** On day 1, balances above one month of income are cashed out. There are 318 such cash-outs, carrying 2.3% of all cash-out fees. They are counted in the cash-out features as normal cash-outs, though they are really savings moves.
- **Short lead time.** Most caught shortfalls happen within 1-2 days of day 20, which leaves little time to act.
- **Small lead over the rule.** See the honest summary above.
- **Calibration** is weaker at high risk, so the probability should be shown as a rough level, not an exact number.

## Human oversight
- The model only makes **suggestions**. Nothing moves money automatically. The user decides and taps to accept.
- A user predicted to run short is offered a buffer suggestion, never a savings suggestion.
- The alert threshold can be changed in one place (`ALERT_THRESHOLD_OVERRIDE` in `src/config.py`). Any change should be reviewed by a person, together with the fairness numbers.
