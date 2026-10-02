# Data Assumptions

## Synthetic data statement
All data in this project is **simulated** by `src/data/generator.py` (run `python -m src.data.generator`). No real upay user, transaction, balance or fee data is used. The simulation is deterministic: the same `SEED` in `src/config.py` always gives the same files. Every number below is an **ASSUMPTION** and is a named constant in `src/config.py`.

Output files (in `data/`, not committed to git):
- `users.csv`: user_id, income_type, income_band, region, age_band, income_day (blank for non-salaried users), opening_balance
- `transactions.csv`: user_id, month, day, type, direction (in/out), amount, fee, channel (app/agent)
- `daily_balance.csv`: user_id, month, day, end_of_day_balance

All amounts are whole BDT. There is **no label or shortfall column** in any file. The target is worked out later from `daily_balance.csv` (see `target_definition.md`). Hidden simulation habits (bill load, cash-out habit, family send share, bill days, shock probabilities) are never written to any file.

## Population
- ASSUMPTION: 1,000 users (`N_USERS`), 6 months (`N_MONTHS`) of 30 days (`DAYS_IN_MONTH`).
- ASSUMPTION: Regions: Dhaka 35%, Chattogram 20%, Khulna 15%, Rajshahi 15%, Sylhet 15%.
- ASSUMPTION: Age bands: 18-25 25%, 26-35 35%, 36-50 28%, 51+ 12%.
- ASSUMPTION: Income bands: low 45%, mid 40%, high 15%. In Dhaka and Chattogram, 5 points move from low to high.
- ASSUMPTION: Income types: salaried 55%, gig/irregular 30%, small business 15%.
- ASSUMPTION: Opening wallet balance is 10%-50% of the user's monthly income.

## Income patterns
- ASSUMPTION: Usual monthly income is drawn log-uniformly within the band: low 8,000-15,000 BDT, mid 15,000-35,000 BDT, high 35,000-80,000 BDT.
- ASSUMPTION: Month-to-month income wobble (standard deviation): salaried 3%, gig 30%, business 20%.
- ASSUMPTION: Salaried users are paid once a month on a fixed day between day 1 and day 7, into the app.
- ASSUMPTION: Gig users get 4-10 payments a month on random days, in random sizes.
- ASSUMPTION: Small-business users get about 4 roughly weekly receipts.
- ASSUMPTION: 40% of gig and business income payments come in through an agent, the rest through the app.
- ASSUMPTION: 30% of user-months include one top-up (add_money) of 5% of monthly income.

## Spending and bills
- ASSUMPTION: Regular bills are 8%-20% of monthly income, paid on two fixed days per user (between day 3 and day 28).
- ASSUMPTION: Mobile recharge is 3% of monthly income, in 4 recharges on random days.
- ASSUMPTION: 5%-15% of each income payment is sent to family 0-3 days after it arrives.
- ASSUMPTION: The planned total outflow each month is on average 85% of usual income (standard deviation 6%). What is left after bills, recharge, family and cash-out goes on merchant payments (never less than 5% of income), spread over random days (each day has a 60% chance).
- ASSUMPTION: An outflow can never exceed the available balance (amount = min(planned, balance)), so the balance is never negative. Spending that the user cannot afford simply does not happen.
- ASSUMPTION: On day 1, any balance above 1 month of income is cashed out (savings kept outside the wallet). This stops balances from growing without limit.

## Cash-out behaviour
- ASSUMPTION: Each user cashes out 20%-60% of each income payment at an agent, 0-3 days after it arrives.
- ASSUMPTION: Every cash-out pays a fee of `CASHOUT_FEE_RATE` × amount, rounded to whole BDT. Amount + fee together never exceed the balance.
- Fees are recorded in the `fee` column. Only cash-outs have fees.

## Stress mechanisms
Stress (a low balance) comes only from these mechanisms. It is never stamped on as a label.
- **Late salary.** ASSUMPTION: 12% chance per month that a salaried user is paid 3-22 days late, so sometimes after day 20.
- **Irregular gig income.** ASSUMPTION: gig payments land on random days, and there is a 20% chance per month of a thin month where income is 60% of usual.
- **Bill shock.** ASSUMPTION: 20% chance per month of a one-off bill of 4 × the user's normal monthly bill load, on a random day.
- **Family emergency.** ASSUMPTION: 15% chance per month of an extra send to family of 50% of monthly income, on a random day.
- **Festival month.** ASSUMPTION: month index 3 (the 4th month) has family sends × 2.0 and merchant spending × 1.4.

Results of the generator's built-in checks at the current settings: 23.3% of user-months dip below 500 BDT on days 21-30. The ROC-AUC of the day-20 balance alone is 0.851.

## Fee source (TO BE SOURCED)
TO BE SOURCED by researcher. `CASHOUT_FEE_RATE` (currently 1.5%) is a placeholder ASSUMPTION and must be replaced with a figure sourced from upay's official site.

## Known limitations
- Every month has exactly 30 days, and there are no weekends or public holidays.
- Users are independent. There are no transfers between simulated users.
- Spending does not react to a low balance. It is only capped at what is available.
- Shock probabilities and sizes are ASSUMPTIONS that were tuned to give a 15%-30% shortfall rate. They are not measured from real data.
- Differences between income_band, region and age_band groups come only from the income-band shares and the small city shift. Real groups may differ in other ways.
- Unpredictable shocks are what keep the problem from being trivial. Real-world predictability could be higher or lower.
