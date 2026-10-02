# Phase 1: synthetic data generator for the upay Smart Cash-Flow Copilot.
# Everything here is SIMULATED. No real user, transaction or fee data is used.
# Run with:  python -m src.data.generator
#
# Stress (running short of money) is never stamped as a label. It only happens
# because of the mechanisms below: late salary, irregular gig income, bill
# shocks, family emergencies and a festival month.

import time  # Used to time the whole run.

import numpy as np  # Random numbers and fast maths.
import pandas as pd  # Tables and CSV files.

from src import config as C  # All settings live in config.py.

DAYS = C.DAYS_IN_MONTH  # Short name for the number of days in a month.


# ---------------------------------------------------------------------------
# 1. Users
# ---------------------------------------------------------------------------

def pick_income_band(rng, region):
    """Pick low/mid/high income. Big cities have slightly more high earners."""
    shares = list(C.INCOME_BAND_SHARES)  # Start from the national shares.
    if region in ("Dhaka", "Chattogram"):  # Big cities get a small shift...
        shares[0] -= C.CITY_HIGH_INCOME_SHIFT  # ...fewer low earners...
        shares[2] += C.CITY_HIGH_INCOME_SHIFT  # ...more high earners.
    return rng.choice(C.INCOME_BANDS, p=shares)  # Draw one band.


def make_user(rng, user_id):
    """Create one simulated user: visible attributes plus hidden habits."""
    region = rng.choice(C.REGIONS, p=C.REGION_SHARES)  # Where they live.
    age_band = rng.choice(C.AGE_BANDS, p=C.AGE_BAND_SHARES)  # How old they are.
    income_band = pick_income_band(rng, region)  # Low / mid / high.
    income_type = rng.choice(C.INCOME_TYPES, p=C.INCOME_TYPE_SHARES)  # Salaried / gig / business.
    lo, hi = C.INCOME_BAND_RANGES_BDT[income_band]  # Income range for that band.
    base_income = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))  # Usual monthly income (log-uniform in range).
    # Salaried users have a fixed payday; others have no single payday.
    income_day = int(rng.integers(C.SALARY_DAY_RANGE[0], C.SALARY_DAY_RANGE[1] + 1)) if income_type == "salaried" else None
    opening = int(base_income * rng.uniform(*C.OPENING_BALANCE_SHARE_RANGE))  # Starting wallet balance, whole BDT.
    return {
        # Visible columns (written to users.csv).
        "user_id": user_id,
        "income_type": income_type,
        "income_band": income_band,
        "region": region,
        "age_band": age_band,
        "income_day": income_day,
        "opening_balance": opening,
        # Hidden habits (used by the simulation only, never written to any file).
        "_base_income": base_income,
        "_bill_load": rng.uniform(*C.BILL_LOAD_RANGE),
        "_cashout_habit": rng.uniform(*C.CASHOUT_HABIT_RANGE),
        "_family_share": rng.uniform(*C.FAMILY_SEND_SHARE_RANGE),
        "_bill_days": sorted(rng.choice(np.arange(3, 29), size=2, replace=False).tolist()),  # Two fixed bill days.
    }


# ---------------------------------------------------------------------------
# 2. Planned events for one user-month (before checking the balance)
# ---------------------------------------------------------------------------

def income_payments(rng, u):
    """Return a list of (day, amount, channel) income payments for one month."""
    base = u["_base_income"]  # Usual monthly income.
    kind = u["income_type"]  # Salaried / gig / business.
    actual = base * max(0.2, rng.normal(1.0, C.INCOME_NOISE_SD[kind]))  # This month's real income, with wobble.
    if kind == "salaried":
        day = u["income_day"]  # Normal payday.
        if rng.random() < C.LATE_SALARY_PROB:  # STRESS: salary is late this month.
            day = min(DAYS, day + int(rng.integers(C.LATE_SALARY_DELAY_DAYS[0], C.LATE_SALARY_DELAY_DAYS[1] + 1)))
        return [(day, actual, "app")]  # One salary payment, paid into the app.
    if kind == "gig":
        if rng.random() < C.GIG_THIN_MONTH_PROB:  # STRESS: a thin month for gig work.
            actual *= C.GIG_THIN_MONTH_FACTOR
        n = int(rng.integers(C.GIG_PAYMENTS_RANGE[0], C.GIG_PAYMENTS_RANGE[1] + 1))  # How many gig payments.
        days = rng.integers(1, DAYS + 1, size=n)  # STRESS: they land on random days.
        sizes = rng.dirichlet(np.ones(n)) * actual  # Random split of the month's income.
    else:  # Small business: money comes in roughly weekly.
        n = C.BUSINESS_RECEIPTS_PER_MONTH
        spacing = DAYS // n  # Gap between receipts.
        days = np.clip(np.arange(n) * spacing + 3 + rng.integers(-2, 3, size=n), 1, DAYS)  # Roughly weekly days.
        sizes = rng.dirichlet(np.full(n, 5.0)) * actual  # Fairly even split.
    channels = np.where(rng.random(n) < C.AGENT_CHANNEL_PROB, "agent", "app")  # Some cash comes in at an agent.
    return list(zip(days.tolist(), sizes.tolist(), channels.tolist()))


def spread_over_days(rng, total, prob):
    """Split a total amount over random days (each day used with chance prob)."""
    active = np.flatnonzero(rng.random(DAYS) < prob) + 1  # Days with a payment.
    if len(active) == 0 or total <= 0:  # Nothing to spread.
        return []
    weights = rng.exponential(1.0, size=len(active))  # Some days bigger than others.
    return list(zip(active.tolist(), (total * weights / weights.sum()).tolist()))


def plan_month(rng, u, month):
    """Build all planned events for one user-month.

    Each event is (day, order, type, direction, planned_amount, channel).
    order 0 = money in (handled first in the day), 1 = money out.
    """
    base = u["_base_income"]  # Usual monthly income.
    festival = month == C.FESTIVAL_MONTH_INDEX  # STRESS: is this the festival month?
    family_mult = C.FESTIVAL_FAMILY_MULT if festival else 1.0  # Bigger family sends at festival time.
    shop_mult = C.FESTIVAL_SHOPPING_MULT if festival else 1.0  # More shopping at festival time.
    ev = []  # Collected events.

    # Income, plus family send and cash-out shortly after each payment arrives.
    for day, amount, channel in income_payments(rng, u):
        ev.append((day, 0, "salary_or_income", "in", amount, channel))
        fam_day = min(DAYS, day + int(rng.integers(0, 4)))  # Family send 0-3 days after income.
        ev.append((fam_day, 1, "send_money_family", "out", amount * u["_family_share"] * family_mult, "app"))
        co_day = min(DAYS, day + int(rng.integers(0, 4)))  # Cash-out 0-3 days after income.
        ev.append((co_day, 1, "cash_out", "out", amount * u["_cashout_habit"], "agent"))

    # Occasional top-up from a bank or card.
    if rng.random() < C.ADD_MONEY_PROB:
        ev.append((int(rng.integers(1, DAYS + 1)), 0, "add_money", "in", base * C.ADD_MONEY_SHARE, "app"))

    # Regular bills on the user's two fixed bill days.
    for d in u["_bill_days"]:
        ev.append((d, 1, "bill_payment", "out", base * u["_bill_load"] / 2 * rng.uniform(0.9, 1.1), "app"))

    # STRESS: one-off bill shock on a random day.
    if rng.random() < C.BILL_SHOCK_PROB:
        ev.append((int(rng.integers(1, DAYS + 1)), 1, "bill_payment", "out", base * u["_bill_load"] * C.BILL_SHOCK_MULT, "app"))

    # STRESS: family emergency send on a random day.
    if rng.random() < C.FAMILY_EMERGENCY_PROB:
        ev.append((int(rng.integers(1, DAYS + 1)), 1, "send_money_family", "out", base * C.FAMILY_EMERGENCY_SHARE, "app"))

    # Mobile recharge, about 4 times a month.
    for d in rng.integers(1, DAYS + 1, size=4).tolist():
        ev.append((d, 1, "mobile_recharge", "out", base * C.RECHARGE_SHARE / 4, "app"))

    # Merchant payments: whatever is left of this month's spending plan.
    spend_ratio = rng.normal(C.SPEND_RATIO_MEAN, C.SPEND_RATIO_SD)  # How much the user plans to spend this month.
    fixed = u["_bill_load"] + C.RECHARGE_SHARE + u["_cashout_habit"] + u["_family_share"]  # Already-planned shares.
    merchant_total = max(spend_ratio - fixed, 0.05) * base * shop_mult  # Never less than 5% of income.
    for d, amount in spread_over_days(rng, merchant_total, C.MERCHANT_DAY_PROB):
        ev.append((d, 1, "merchant_payment", "out", amount, "app"))

    ev.sort(key=lambda e: (e[0], e[1]))  # Order by day, money-in before money-out (stable for ties).
    return ev


# ---------------------------------------------------------------------------
# 3. Applying events to the wallet balance
# ---------------------------------------------------------------------------

def cashout_fee(amount):
    """Fee for a cash-out, in whole BDT (rounded half up)."""
    return int(amount * C.CASHOUT_FEE_RATE + 0.5)


def affordable_outflow(planned, balance, has_fee):
    """Return (amount, fee) so that amount + fee never exceeds the balance."""
    amount = min(int(planned), balance)  # Cannot pay more than what is in the wallet.
    if not has_fee:
        return amount, 0
    amount = min(amount, int(balance / (1 + C.CASHOUT_FEE_RATE)))  # Leave room for the fee.
    fee = cashout_fee(amount)
    while amount > 0 and amount + fee > balance:  # Rounding safety: shrink until it fits.
        amount -= 1
        fee = cashout_fee(amount)
    return amount, fee


def simulate_user(rng, u, tx_rows, bal_rows):
    """Run one user day by day through all months, appending rows to the lists."""
    balance = u["opening_balance"]  # Start from the opening balance (whole BDT).
    uid = u["user_id"]
    cap = int(C.SWEEP_BALANCE_MONTHS * u["_base_income"])  # Balance above this gets moved out on day 1.
    for month in range(C.N_MONTHS):
        events = plan_month(rng, u, month)  # Planned events for this month.
        if balance > cap:  # Day 1 sweep: extra savings are cashed out and kept elsewhere.
            amount, fee = affordable_outflow(balance - cap, balance, has_fee=True)
            if amount > 0:
                balance -= amount + fee
                tx_rows.append((uid, month, 1, "cash_out", "out", amount, fee, "agent"))
        i = 0  # Pointer into the sorted event list.
        for day in range(1, DAYS + 1):
            while i < len(events) and events[i][0] == day:  # All events on this day.
                _, _, kind, direction, planned, channel = events[i]
                i += 1
                if direction == "in":  # Money coming in.
                    amount, fee = int(planned), 0
                    balance += amount
                else:  # Money going out, capped by what is available.
                    amount, fee = affordable_outflow(planned, balance, has_fee=(kind == "cash_out"))
                    balance -= amount + fee
                if amount > 0:  # Skip empty events (e.g. wallet was already empty).
                    tx_rows.append((uid, month, day, kind, direction, amount, fee, channel))
            bal_rows.append((uid, month, day, balance))  # End-of-day balance.


def generate():
    """Create users, simulate them, and return the three tables."""
    rng = np.random.default_rng(C.SEED)  # One seeded generator => same data every run.
    users = [make_user(rng, uid) for uid in range(1, C.N_USERS + 1)]  # All users.
    tx_rows, bal_rows = [], []  # Collected rows.
    for u in users:
        simulate_user(rng, u, tx_rows, bal_rows)
    visible = ["user_id", "income_type", "income_band", "region", "age_band", "income_day", "opening_balance"]
    users_df = pd.DataFrame(users)[visible]  # Drop every hidden habit before saving.
    users_df["income_day"] = users_df["income_day"].astype("Int64")  # Whole numbers, blank for non-salaried.
    tx_df = pd.DataFrame(tx_rows, columns=["user_id", "month", "day", "type", "direction", "amount", "fee", "channel"])
    bal_df = pd.DataFrame(bal_rows, columns=["user_id", "month", "day", "end_of_day_balance"])
    return users_df, tx_df, bal_df


# ---------------------------------------------------------------------------
# 4. Built-in checks
# ---------------------------------------------------------------------------

def check_no_negative(bal_df):
    """Check 1: the balance is never negative."""
    n_neg = int((bal_df["end_of_day_balance"] < 0).sum())
    print(f"[1] Negative balances: {n_neg}  ->  {'PASS' if n_neg == 0 else 'FAIL'}")


def check_rebuild(users_df, tx_df, bal_df):
    """Check 2: rebuild every daily balance from opening balance + transactions (incl. fees)."""
    signed = np.where(tx_df["direction"] == "in", tx_df["amount"], -(tx_df["amount"] + tx_df["fee"]))  # Net effect of each row.
    net = pd.Series(signed, index=pd.MultiIndex.from_frame(tx_df[["user_id", "month", "day"]])).groupby(level=[0, 1, 2]).sum()
    grid = bal_df[["user_id", "month", "day"]].copy()  # Every user-day.
    grid["net"] = net.reindex(pd.MultiIndex.from_frame(grid)).fillna(0).to_numpy()  # Days with no transactions = 0.
    grid = grid.sort_values(["user_id", "month", "day"])  # Time order inside each user.
    opening = users_df.set_index("user_id")["opening_balance"]
    rebuilt = grid.groupby("user_id")["net"].cumsum() + grid["user_id"].map(opening)  # Running total from opening.
    actual = bal_df.loc[grid.index, "end_of_day_balance"]
    n_bad = int((rebuilt.astype("int64") != actual).sum())
    print(f"[2] Rebuilt balances that differ from daily_balance.csv: {n_bad}  ->  {'PASS' if n_bad == 0 else 'FAIL'}")


def user_month_outcomes(users_df, bal_df):
    """For checks only: day-20 balance and whether balance dips below the floor on days 21-30.

    This is computed in memory and is NEVER written to any file.
    """
    after = bal_df[bal_df["day"] > C.PREDICTION_DAY]  # Days 21-30.
    short = (after.groupby(["user_id", "month"])["end_of_day_balance"].min() < C.SHORTFALL_FLOOR_BDT).rename("short")
    d20 = bal_df[bal_df["day"] == C.PREDICTION_DAY].set_index(["user_id", "month"])["end_of_day_balance"].rename("bal20")
    out = pd.concat([short, d20], axis=1).reset_index()
    return out.merge(users_df[["user_id"] + C.FAIRNESS_COLUMNS], on="user_id")


def check_shortfall_rate(um):
    """Check 3: share of user-months with a day 21-30 shortfall (target 15%-30%)."""
    rate = um["short"].mean()
    ok = 0.15 <= rate <= 0.30
    print(f"[3] Shortfall share (day 21-30 below {C.SHORTFALL_FLOOR_BDT} BDT): {rate:.1%}  ->  {'IN TARGET' if ok else 'OUT OF TARGET'} (15%-30%)")


def check_by_group(um):
    """Check 4: shortfall share per fairness group."""
    print("[4] Shortfall share by group:")
    for col in C.FAIRNESS_COLUMNS:
        shares = um.groupby(col)["short"].mean().sort_index()
        print(f"    {col}: " + ", ".join(f"{k}={v:.1%}" for k, v in shares.items()))


def roc_auc(y, score):
    """ROC-AUC with numpy/pandas only (rank formula; ties get average rank)."""
    y = np.asarray(y, dtype=bool)
    ranks = pd.Series(score).rank(method="average").to_numpy()  # Rank of each score.
    n_pos, n_neg = y.sum(), (~y).sum()
    return (ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def check_baseline_auc(um):
    """Check 5: how well the day-20 balance alone predicts the shortfall (target 0.65-0.85)."""
    auc = roc_auc(um["short"], -um["bal20"])  # Lower balance = higher risk, so negate.
    ok = 0.65 <= auc <= 0.85
    print(f"[5] Baseline ROC-AUC (day-20 balance only): {auc:.3f}  ->  {'IN TARGET' if ok else 'OUT OF TARGET'} (0.65-0.85)")


def check_row_counts(users_df, tx_df, bal_df):
    """Check 6: number of rows in each file."""
    print(f"[6] Rows: users.csv={len(users_df):,}  transactions.csv={len(tx_df):,}  daily_balance.csv={len(bal_df):,}")


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def main():
    """Generate the data, save the CSVs, and print all checks."""
    start = time.time()
    users_df, tx_df, bal_df = generate()
    C.DATA_DIR.mkdir(exist_ok=True)  # Make sure data/ exists.
    users_df.to_csv(C.DATA_DIR / "users.csv", index=False)
    tx_df.to_csv(C.DATA_DIR / "transactions.csv", index=False)
    bal_df.to_csv(C.DATA_DIR / "daily_balance.csv", index=False)
    print(f"Saved simulated data to {C.DATA_DIR}")
    # Re-read the saved files so the checks test exactly what is on disk.
    users_df = pd.read_csv(C.DATA_DIR / "users.csv")
    tx_df = pd.read_csv(C.DATA_DIR / "transactions.csv")
    bal_df = pd.read_csv(C.DATA_DIR / "daily_balance.csv")
    check_no_negative(bal_df)
    check_rebuild(users_df, tx_df, bal_df)
    um = user_month_outcomes(users_df, bal_df)
    check_shortfall_rate(um)
    check_by_group(um)
    check_baseline_auc(um)
    check_row_counts(users_df, tx_df, bal_df)
    print(f"Finished in {time.time() - start:.1f} s")


if __name__ == "__main__":
    main()
