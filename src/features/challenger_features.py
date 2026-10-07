# Extra candidate features for the CHALLENGER experiment only (the shipped model never sees them).
# Days 1-20 of the month and complete earlier months only. All data is simulated.
# "Lowest balance days 1-20" and "days since last inflow" are already shipped features, so they are not repeated.

import numpy as np  # Number tools.
import pandas as pd  # Table tools.

from src import config as cfg  # Prediction day, months, types.
from src.features.build_features import month_targets  # Shortfall labels of complete months (reused).

DAY = cfg.PREDICTION_DAY
KEYS = ["user_id", "month"]
NEW_FEATURES = (["bal_trend_d11_20", "balance_swing_d1_20", "spend_last5_vs_avg", "earlier_shortfalls"]
                + [f"share_{t}" for t in cfg.BUDGET_TYPES])


def challenger_features(tx, bal):
    """One row per user-month (index user_id, month) with the NEW_FEATURES columns."""
    bal_early = bal[bal["day"] <= DAY].sort_values(KEYS + ["day"])
    by_um = bal_early.groupby(KEYS)["end_of_day_balance"]
    out = pd.DataFrame(index=by_um.size().index)
    # Balance trend over days 11-20: change per day from day 11 to day 20.
    wide = bal_early.pivot_table(index=KEYS, columns="day", values="end_of_day_balance")
    out["bal_trend_d11_20"] = (wide[DAY] - wide[11]) / (DAY - 11)
    # Day-to-day balance swings on days 1-20 (standard deviation of the daily change).
    out["balance_swing_d1_20"] = wide.diff(axis=1).std(axis=1)
    # Spending in the last 5 days (16-20) against the month's average so far, per day.
    tx_early = tx[(tx["day"] <= DAY) & (tx["direction"] == "out")]
    spend = (tx_early["amount"] + tx_early["fee"]).groupby([tx_early["user_id"], tx_early["month"]]).sum()
    last5 = tx_early[tx_early["day"] > DAY - 5]
    spend5 = (last5["amount"] + last5["fee"]).groupby([last5["user_id"], last5["month"]]).sum()
    out["spend_last5_vs_avg"] = (spend5.reindex(out.index, fill_value=0) / 5) / (spend.reindex(out.index) / DAY)
    # Share of money out per spending type on days 1-20 (0 when nothing went out).
    for t in cfg.BUDGET_TYPES:
        part = tx_early[tx_early["type"] == t]
        by_type = (part["amount"] + part["fee"]).groupby([part["user_id"], part["month"]]).sum()
        out[f"share_{t}"] = (by_type.reindex(out.index, fill_value=0) / spend.reindex(out.index)).fillna(0)
    # Number of the user's earlier complete months that ended in a shortfall.
    labels = month_targets(bal)["label"].unstack("month").reindex(columns=range(cfg.N_MONTHS)).fillna(0)
    earlier = labels.cumsum(axis=1).shift(1, axis=1).fillna(0).stack().rename("earlier_shortfalls")
    out["earlier_shortfalls"] = earlier.reindex(out.index).fillna(0)
    return out[NEW_FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)


def leakage_by_feature(tx, bal, full):
    """Rebuild each month with every row after day 20 of that month deleted; return {feature: identical?}."""
    same = {f: True for f in NEW_FEATURES}
    for m in sorted(full.index.get_level_values("month").unique()):
        keep_tx = (tx["month"] < m) | ((tx["month"] == m) & (tx["day"] <= DAY))
        keep_bal = (bal["month"] < m) | ((bal["month"] == m) & (bal["day"] <= DAY))
        cut = challenger_features(tx[keep_tx], bal[keep_bal])
        a = full.xs(m, level="month")
        b = cut.xs(m, level="month").reindex(a.index)
        for f in NEW_FEATURES:
            same[f] &= bool(a[f].equals(b[f]))
    return same
