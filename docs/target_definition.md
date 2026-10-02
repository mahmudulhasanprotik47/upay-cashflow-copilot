# Target Definition

A user is flagged if their simulated balance drops below 500 BDT on any day from 21 to 30, predicted at the end of day 20 using days 1-20 only.

All data in this project is simulated. Every number below is a setting in `src/config.py`, so it can be changed in one place.

## 1. Prediction moment

We make one prediction per user per month, at the end of day 20 (`PREDICTION_DAY`). At that moment we only know what happened on days 1 to 20.

## 2. Target

- The target is **1** if the user's simulated balance falls below `SHORTFALL_FLOOR_BDT` (500 BDT) on any day from 21 to 30. Otherwise it is **0**.
- The label is worked out from the simulated daily balance. The data generator never sets the label directly.

## 3. Features (to be finalized in Phase 1)

These are proposed names only. Each one uses days 1-20 only.

- `balance_day20`: balance at the end of day 20
- `min_balance_d1_20`: lowest balance on days 1-20
- `avg_daily_spend_d1_20`: average spending per day on days 1-20
- `total_inflow_d1_20`: total money received on days 1-20
- `total_outflow_d1_20`: total money spent or sent on days 1-20
- `cashout_count_d1_20`: number of cash-outs on days 1-20
- `cashout_amount_d1_20`: total amount cashed out on days 1-20
- `days_since_last_inflow`: days since money last came in, counted at day 20
- `bill_payments_d1_20`: number of bill payments on days 1-20
- `prev_month_shortfall`: whether the user was flagged last month (a complete past month only)

## 4. Leakage rules

- No feature may use anything from day 21 onward.
- No feature may be built from the target, or from anything used to calculate the target.
- `prev_month_shortfall` may only use months that ended before the current one.

## 5. Split

- Train on earlier months. Test on the latest `TEST_MONTHS` (2) months.
- The split is always by time, never random. This copies real use, where we predict the future from the past.

## 6. Baseline rule

- The simple rule is "flag the user if their balance on day 20 is below X". X is tuned on the training months only.
- The model is only worth using if it beats this rule on the test months.

## 7. Fairness

- We compare results across `FAIRNESS_COLUMNS`: `income_band`, `region` and `age_band`. Results include the share of users flagged, missed shortfalls and false alarms.
- These columns are never model inputs. They are only used to check fairness.

## 8. Suggestion rules

- Every suggestion is optional. The user taps to accept it. Nothing moves money automatically.
- A user predicted to run short never gets a savings suggestion. We suggest keeping a buffer instead.
- A savings suggestion is never more than `SAVINGS_CAP_FRACTION` (half) of the user's predicted safe surplus.
- Fees and savings amounts are shown as plain numbers, in BDT.
- No urgency or pressure wording, such as "act now" or "last chance".
