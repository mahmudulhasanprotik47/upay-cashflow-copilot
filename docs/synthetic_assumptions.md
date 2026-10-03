# Synthetic Data Assumptions

All data in this project is **simulated**. This file lists every assumption the data generator makes, where it
lives in the code, and what it does not model. It describes what the simulator does, not what the world does.

## 1. Purpose and scope

- The data exists to build and test a day-20 cash-flow forecast for a mobile wallet: will the balance fall below
  500 BDT on any day from 21 to 30, predicted at the end of day 20 using days 1-20 only.
- It is fully simulated by `src/data/generator.py`. There is no real customer data and no personal information.
  User ids are counters (1 to 1,000), and the attributes are drawn at random from the shares below.
- Shortfalls are never stamped as labels. They only happen through the mechanisms below (`generator.py`,
  header comment).
- Most settings live in src/config.py; a few literals live in generator.py and are marked in the table below.

## 2. How to regenerate

- Command: `python -m src.data.generator`
- Output: `data/users.csv`, `data/transactions.csv` and `data/daily_balance.csv` (`main`, `config.DATA_DIR`).
- Determinism: one random generator seeded with `SEED = 42` (`generate`) creates every user and every event in
  the same order. The code comment says this gives the same simulated data on every run.
- Hidden per-user habits (names starting with `_`) are used inside the simulation only and are never written to
  any file (`make_user`, `generate`).
- Built-in checks run after saving (`main`): no negative balance; every daily balance can be rebuilt from the
  opening balance plus transactions and fees; row counts; shortfall share overall and by group.
- The generator's built-in check aims for a shortfall share between 15% and 30% (`check_shortfall_rate`). This
  is a calibration aim for the simulation, not an observed real-world rate. Per data_assumptions.md, the shock chances and sizes were tuned to land in that range, so the base shortfall rate is a result of tuning, not a measured prevalence.

## 3. Assumptions

Unless stated otherwise, the values are labelled ASSUMPTION in `config.py`, with no rationale recorded.

| Area | What the simulator assumes | Value(s) from the code | Where | Why it matters / limitation |
|---|---|---|---|---|
| Population size | A fixed number of users with a fixed history length | `N_USERS = 1000`, `N_MONTHS = 6` | `config.py`; `generate` | Every user has the same history length. |
| Region | Drawn independently per user | 5 regions (Dhaka, Chattogram, Khulna, Rajshahi, Sylhet), shares 0.35, 0.20, 0.15, 0.15, 0.15 | `make_user` | Region only changes the income-band draw; nothing else depends on it. |
| Age band | Drawn independently per user | 18-25, 26-35, 36-50, 51+; shares 0.25, 0.35, 0.28, 0.12 | `make_user` | Not used by any later step of the simulation. |
| Income band | Drawn per user; cities shift the shares | Shares 0.45, 0.40, 0.15 (low, mid, high); in Dhaka and Chattogram 0.05 moves from low to high | `pick_income_band` | The only link between region and money behaviour. |
| Usual income | Log-uniform within the band's range | low 8000-15000, mid 15000-35000, high 35000-80000 BDT per month | `make_user` | Amounts are BDT per simulated month. |
| Income type | Drawn per user | salaried 0.55, gig 0.30, business 0.15 | `make_user` | Sets the payment pattern below. |
| Month-to-month income wobble | Normal noise around usual income, never below 0.2 of it | SD salaried 0.03, gig 0.30, business 0.20; floor 0.2 | `income_payments` | The 0.2 floor: no rationale recorded in code. |
| Calendar | Every month has the same length; no weekdays or holidays | `DAYS_IN_MONTH = 30`; prediction at `PREDICTION_DAY = 20` | `config.py` | Labelled as a simplification in `config.py`. |
| Salaried pay (date variation) | **Modelled.** One fixed payday per user, sometimes late | Payday drawn from days 1-7; late with chance 0.12, by 3-22 days, never after day 30 | `make_user`, `income_payments` | Late pay can land after day 20, inside the same month only. |
| Gig pay | Several payments on random days, random split | 4-10 payments; thin month with chance 0.20, income x 0.6 | `income_payments` | Equal Dirichlet weights for the split: no rationale recorded in code. |
| Business pay | Roughly weekly receipts | 4 per month, spaced `30 // 4` days apart, starting day 3, moved by -2 to +2 days; Dirichlet weight 5.0 | `income_payments` | The +3 start, the ±2 shift and the 5.0 weight: no rationale recorded in code. |
| Income channel | Some gig and business pay arrives at an agent | Chance 0.4 per payment; salaried pay always in the app | `income_payments` | A channel label only; there are no agent entities. |
| Opening balance | A share of usual income | 0.10-0.50 of monthly income, whole BDT | `make_user` | Sets the first month's starting point. |
| Family sends | A share of each income payment, sent 0-3 days later | Share 0.05-0.15 per user | `make_user`, `plan_month` | The 0-3 day lag: no rationale recorded in code. |
| Cash-outs | A share of each income payment, cashed out at an agent 0-3 days later | Habit 0.20-0.60 per user | `make_user`, `plan_month` | The 0-3 day lag: no rationale recorded in code. |
| Cash-out fee | **Placeholder, not sourced.** Charged on cash-outs only, rounded half up to whole BDT; amount + fee never exceeds the balance | `CASHOUT_FEE_RATE = 0.015` (1.5%) | `cashout_fee`, `affordable_outflow` | `config.py` marks it as a placeholder to be replaced with a sourced figure. |
| Bills | Two fixed bill days per user, each half the user's bill load | Bill load 0.08-0.20 of income; days drawn from 3-28; each bill varies 0.9-1.1 | `make_user`, `plan_month` | The 3-28 day range and the 0.9-1.1 wobble: no rationale recorded in code. |
| Mobile recharge | Four recharges on random days | Total 0.03 of income per month, split into 4 | `plan_month` | The count of 4: no rationale recorded in code. |
| Top-up from bank or card | Occasional money in | Chance 0.30 per month, size 0.05 of income, random day | `plan_month` | The only inflow besides income. |
| Merchant spending | Whatever is left of the month's spending plan, spread over random days | Spend ratio mean 0.85, SD 0.06; each day used with chance 0.6; at least 0.05 of income | `plan_month`, `spread_over_days` | The 0.05 minimum: no rationale recorded in code. |
| Day-1 sweep | A balance above a cap is cashed out (with fee) on day 1 and kept elsewhere | Cap = 1.0 x usual monthly income | `simulate_user` | Stops balances growing without limit; adds day-1 cash-outs. |
| Event order | Money in before money out on the same day | Sort by (day, in/out) | `plan_month` | Same-day income can pay same-day spending. |
| Balance and floor | Outflows are capped by what is in the wallet; the balance never goes negative | Whole BDT | `affordable_outflow`, `simulate_user`, `check_no_negative` | Spending that cannot be paid is dropped; there is no debt or carry-over. |
| Previous-month link | **No explicit link** to last month's shortfall. Only the balance carries from one month to the next | none | `simulate_user` | Any month-to-month pattern comes from the carried balance and fixed per-user habits. |
| Shortfall target | Balance below 500 BDT on any day 21-30, worked out from the daily balance | `SHORTFALL_FLOOR_BDT = 500` | `config.py`; `docs/target_definition.md`; `user_month_outcomes` (checks only) | The generator never writes the target to a file. |
| Train/test split | By time: train months 0-3, test months 4-5 | `TEST_MONTHS = 2` | `config.py`; `docs/target_definition.md` | The generator does not split; the split happens later in the pipeline. |

## 4. Known patterns injected on purpose

The code marks these as STRESS mechanisms (`generator.py`). They are there so shortfalls arise from causes in the
data rather than from a stamped label (header comment). The code records no further rationale.

| Pattern | Value(s) | Where |
|---|---|---|
| Late salary | chance 0.12 per month, 3-22 days late | `income_payments` |
| Thin gig month | chance 0.20, income x 0.6 | `income_payments` |
| Gig pay on random days | 4-10 payments | `income_payments` |
| Bill shock (one-off large bill) | chance 0.20, 4.0 x the monthly bill load | `plan_month` |
| Family emergency send | chance 0.15, 0.50 of monthly income | `plan_month` |
| Festival month | month 3 is a festival month: family sends x 2.0, merchant spending x 1.4 | `plan_month` |

The fixed per-user habits (bill load, cash-out habit, family share, opening balance) also make some users more
likely to run short than others. The code does not mark any user as "at risk".

## 5. What the simulator does NOT model

- Loans, credit, overdrafts or any debt.
- Fraud or disputed transactions.
- Device, location or app-usage data.
- More than one wallet per user, or money held outside the wallet (swept money simply leaves).
- Income sources other than the user's income type and the occasional bank or card top-up.
- Real tariff schedules: the single cash-out rate is a placeholder, and no other transaction type has a fee.
- Weekdays, weekends and holidays other than the single festival month.
- Merchants and agents: **partial**. There are `merchant_payment` transactions and an `agent` channel, but no
  individual merchants or agents.

## 6. How this could mislead

- Results depend on the simulator's own rules. A pattern found in this data may only reflect the rules in
  `plan_month` and `income_payments`.
- Group differences in the fairness check come from the simulator's configured shares, so they show how the model
  behaves on this simulated population, not on real groups. Age band affects nothing in the simulation, and
  region only shifts the income-band draw (`make_user`, `pick_income_band`).
- The cash-out fee rate (`CASHOUT_FEE_RATE`) is a placeholder, not sourced. Every fee amount inherits that
  assumption.
- Unpaid spending is silently dropped (`affordable_outflow`), so a shortfall here means a low balance, not missed
  bills or debt.
- The festival month is month 3, a training month (`FESTIVAL_MONTH_INDEX`). The test months 4-5 contain no
  festival effect.
- Day-1 cash-outs are mostly balance sweeps (`simulate_user`), not ordinary cash-out behaviour.
- Spending does not react to a low balance; it is only capped by what is available. The simulation therefore cannot show whether users would act on a suggestion.
- Users are independent. There are no transfers between simulated users.
- The day-20 balance alone predicts the shortfall very well in this data (ROC-AUC 0.851 as recorded in data_assumptions.md, marginally above the generator's own 0.65-0.85 target band). A simple balance rule is therefore a strong baseline here partly because of how the simulator was built, and real data may differ.

## 7. Path to real data

- Pilot with an opted-in group of users under a data-sharing agreement.
- Re-run the same tests on real history.
- Replace the placeholder fee with the real fee schedule.
- Re-check fairness on real groups.
- Handle consent, data minimisation and security first.
