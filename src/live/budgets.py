# Monthly budget bars per spending type. This is arithmetic (a rule), not AI. All data is simulated.
# Default budget: the user's own median monthly spend on that type over earlier complete months.
# A budget the user sets themselves (stored in the database) replaces the default.

import pandas as pd  # Table tools.

from src import config as cfg  # Budget types, thresholds, days.
from src.api import service  # The user's transactions (live-aware for the current month).
from src.db import database  # Custom budgets.


def spend(tx):
    """Money out per row, fees included (what actually left the wallet)."""
    return tx["amount"] + tx["fee"]


def default_budgets(tx_user, month):
    """{type: median monthly spend over months before `month`} for each budget type; None if no earlier month
    or the median is zero (then the user can set their own)."""
    if month == 0:
        return {t: None for t in cfg.BUDGET_TYPES}
    earlier = tx_user[(tx_user["month"] < month) & tx_user["type"].isin(cfg.BUDGET_TYPES)
                      & (tx_user["direction"] == "out")]
    totals = spend(earlier).groupby([earlier["month"], earlier["type"]]).sum()
    grid = pd.MultiIndex.from_product([range(month), cfg.BUDGET_TYPES], names=["month", "type"])
    medians = totals.reindex(grid, fill_value=0).groupby(level="type").median()  # Months with no spend count as 0.
    return {t: (int(round(medians[t])) if medians[t] > 0 else None) for t in cfg.BUDGET_TYPES}


def custom_budgets(user_id):
    """{type: amount} the user has set themselves."""
    rows = database.get().query("SELECT type, amount_bdt FROM budgets WHERE user_id = ?", (user_id,))
    return {r["type"]: r["amount_bdt"] for r in rows}


def state_of(spent, budget):
    """'no_budget', 'ok', 'close' (at BUDGET_CLOSE_SHARE of the budget) or 'over' (at 100%)."""
    if not budget:
        return "no_budget"
    if spent >= budget:
        return "over"
    return "close" if spent >= cfg.BUDGET_CLOSE_SHARE * budget else "ok"


def budget_bars(user_id, month):
    """One bar per budget type for days 1 to PREDICTION_DAY, with a day-30 pace line. Labelled as a rule."""
    tx_month = service.tx_for(user_id, month)  # Includes live transactions for this month.
    seen = tx_month[(tx_month["day"] <= cfg.PREDICTION_DAY) & (tx_month["direction"] == "out")]
    spent_by_type = spend(seen).groupby(seen["type"]).sum()
    defaults = default_budgets(service.tx_for(user_id), month)  # Earlier months: simulated data only.
    custom = custom_budgets(user_id)
    bars = []
    for t in cfg.BUDGET_TYPES:
        spent = int(spent_by_type.get(t, 0))
        budget = custom.get(t, defaults[t])
        bars.append({"type": t, "spent_bdt": spent, "budget_bdt": budget,
                     "budget_source": "yours" if t in custom else ("median_earlier_months" if budget else None),
                     "pace_day30_bdt": int(round(spent / cfg.PREDICTION_DAY * cfg.DAYS_IN_MONTH)),
                     "state": state_of(spent, budget)})
    return {"enabled": True, "is_rule": True, "simulated": True, "day": cfg.PREDICTION_DAY,
            "close_share": cfg.BUDGET_CLOSE_SHARE, "bars": bars,
            "warnings": sum(b["state"] in ("close", "over") for b in bars)}
