# Builds one feature row per user per month from simulated data, plus the targets.
# Features use days 1-20 only (and complete earlier months). All data is simulated.
# Run: python -m src.features.build_features

import sys  # Used to stop the program with a clear message.

import numpy as np  # Number tools (NaN for blank values).
import pandas as pd  # Table tools for reading and grouping the CSV files.

from src import config as cfg  # Central settings (prediction day, floor, folders).

# The 10 agreed features plus approved extra (a). These are the ONLY model inputs.
FEATURES = [
    "balance_day20",
    "min_balance_d1_20",
    "avg_daily_spend_d1_20",
    "total_inflow_d1_20",
    "total_outflow_d1_20",
    "cashout_count_d1_20",
    "cashout_amount_d1_20",
    "days_since_last_inflow",
    "bill_payments_d1_20",
    "prev_month_shortfall",
    "inflow_vs_prev_month",
]
# Features that are allowed to be blank (no complete previous month exists).
BLANK_ALLOWED = ["prev_month_shortfall", "inflow_vs_prev_month"]
# Target columns: worked out from days 21-30 balances. Never model inputs.
TARGETS = ["label", "min_balance_d21_30", "first_dip_day"]
# Transaction types that count as everyday spending.
SPEND_TYPES = ["merchant_payment", "bill_payment", "mobile_recharge", "send_money_family"]


def load_data():
    """Read the three simulated CSV files, or stop if they are missing."""
    paths = [cfg.DATA_DIR / f for f in ("users.csv", "transactions.csv", "daily_balance.csv")]
    # If any file is missing, tell the user how to create the data and stop.
    if not all(p.exists() for p in paths):
        print("Run python -m src.data.generator first")
        sys.exit(1)
    # Read each file into a table.
    return tuple(pd.read_csv(p) for p in paths)


def current_month_features(tx, bal):
    """Features from days 1 to PREDICTION_DAY of the same month."""
    day = cfg.PREDICTION_DAY  # The last day we are allowed to look at.
    bal_early = bal[bal["day"] <= day]  # Balances on days 1-20 only.
    tx_early = tx[tx["day"] <= day]  # Transactions on days 1-20 only.
    keys = ["user_id", "month"]  # One row per user per month.

    # Balance-based features: end of day 20 and lowest balance on days 1-20.
    out = bal_early[bal_early["day"] == day].set_index(keys)[["end_of_day_balance"]]
    out = out.rename(columns={"end_of_day_balance": "balance_day20"})
    out["min_balance_d1_20"] = bal_early.groupby(keys)["end_of_day_balance"].min()

    # Helper: sum a column over rows matching a condition, per user-month.
    def total(mask, col="amount"):
        return tx_early[mask].groupby(keys)[col].sum()

    is_out = tx_early["direction"] == "out"  # Money leaving the wallet.
    is_in = tx_early["direction"] == "in"  # Money coming into the wallet.
    is_cashout = tx_early["type"] == "cash_out"  # Agent cash-outs.

    # Everyday spending (merchant, bills, recharge, family) averaged per day.
    out["avg_daily_spend_d1_20"] = total(tx_early["type"].isin(SPEND_TYPES)) / day
    out["total_inflow_d1_20"] = total(is_in)  # All money received.
    # All money leaving the wallet, including cash-out fees.
    out["total_outflow_d1_20"] = total(is_out) + total(is_out, "fee")
    out["cashout_count_d1_20"] = tx_early[is_cashout].groupby(keys).size()  # Number of cash-outs.
    out["cashout_amount_d1_20"] = total(is_cashout)  # Amount cashed out (fees not included).
    # Days since money last came in; if nothing came in on days 1-20, count all 20 days.
    last_in_day = tx_early[is_in].groupby(keys)["day"].max()
    out["days_since_last_inflow"] = day - last_in_day
    out["bill_payments_d1_20"] = tx_early[tx_early["type"] == "bill_payment"].groupby(keys).size()

    # User-months with no matching transactions get 0 (or 20 days since last inflow).
    out["days_since_last_inflow"] = out["days_since_last_inflow"].fillna(day)
    return out.fillna(0)


def month_targets(bal):
    """Targets from days 21-30: label, lowest balance, first day below the floor."""
    late = bal[bal["day"] > cfg.PREDICTION_DAY]  # Only the days after the prediction.
    keys = ["user_id", "month"]
    out = late.groupby(keys)["end_of_day_balance"].min().to_frame("min_balance_d21_30")
    # Label is 1 if the balance was below the floor on any day 21-30.
    out["label"] = (out["min_balance_d21_30"] < cfg.SHORTFALL_FLOOR_BDT).astype(int)
    # First day 21-30 below the floor (blank when there was no dip).
    below = late[late["end_of_day_balance"] < cfg.SHORTFALL_FLOOR_BDT]
    out["first_dip_day"] = below.groupby(keys)["day"].min()
    return out


def previous_month_features(tx, bal):
    """Features from the previous COMPLETE month, moved forward one month."""
    keys = ["user_id", "month"]
    prev = month_targets(bal)[["label"]].rename(columns={"label": "prev_month_shortfall"})
    # Full-month inflow of the previous month (all 30 days).
    prev["prev_inflow"] = tx[tx["direction"] == "in"].groupby(keys)["amount"].sum()
    prev = prev.reset_index()
    prev["month"] += 1  # Last month's facts become this month's features.
    return prev.set_index(keys)


def build_features(users, tx, bal):
    """One row per user-month: features, targets and fairness columns."""
    df = current_month_features(tx, bal)  # Days 1-20 features.
    df = df.join(previous_month_features(tx, bal), how="left")  # Blank for month 0.
    # Approved extra (a): this month's days 1-20 inflow vs last month's full inflow.
    # Blank if there is no previous month or it had no inflow.
    df["inflow_vs_prev_month"] = df["total_inflow_d1_20"] / df["prev_inflow"].replace(0, np.nan)
    df = df.join(month_targets(bal), how="left")  # Targets (days 21-30), never inputs.
    df = df.reset_index()
    # All features as decimal numbers, so the column types never depend on the data present.
    df[FEATURES] = df[FEATURES].astype(float)
    # Attach fairness columns for evaluation only.
    df = df.merge(users[["user_id"] + cfg.FAIRNESS_COLUMNS], on="user_id", how="left")
    # Fixed column order so every build is identical.
    cols = ["user_id", "month"] + FEATURES + TARGETS + cfg.FAIRNESS_COLUMNS
    return df[cols].sort_values(["user_id", "month"]).reset_index(drop=True)


def leakage_test(users, tx, bal, full):
    """Rebuild each month with every row after day 20 (of that month) deleted."""
    for m in sorted(full["month"].unique()):
        # Keep complete earlier months, and only days 1-20 of month m.
        keep_tx = (tx["month"] < m) | ((tx["month"] == m) & (tx["day"] <= cfg.PREDICTION_DAY))
        keep_bal = (bal["month"] < m) | ((bal["month"] == m) & (bal["day"] <= cfg.PREDICTION_DAY))
        cut = build_features(users, tx[keep_tx], bal[keep_bal])
        # Compare the feature columns for month m: they must be exactly identical.
        a = full[full["month"] == m][["user_id"] + FEATURES].reset_index(drop=True)
        b = cut[cut["month"] == m][["user_id"] + FEATURES].reset_index(drop=True)
        if not a.equals(b):
            return False
    return True


def summary_lines(df, tx, leak_ok):
    """Plain-text lines describing the feature table."""
    lines = [f"Feature rows: {len(df)} (users x months)"]
    # Shortfall rate for each month.
    for m, rate in df.groupby("month")["label"].mean().items():
        lines.append(f"Month {m}: shortfall rate {rate:.3f}")
    # Day-1 cash-outs are likely balance sweeps (savings kept outside the wallet).
    co = tx[tx["type"] == "cash_out"]
    day1 = co[co["day"] == 1]
    share = day1["fee"].sum() / co["fee"].sum()
    lines.append(f"Day-1 cash-outs (likely sweeps): {len(day1)}, {share:.1%} of all cash-out fees")
    lines.append(f"Leakage test (rebuild without days > {cfg.PREDICTION_DAY}): "
                 + ("PASS, identical" if leak_ok else "FAIL, features differ"))
    return lines


def main():
    """Build features, run the leakage test and print a summary."""
    users, tx, bal = load_data()
    df = build_features(users, tx, bal)
    for line in summary_lines(df, tx, leakage_test(users, tx, bal, df)):
        print(line)


if __name__ == "__main__":
    main()
