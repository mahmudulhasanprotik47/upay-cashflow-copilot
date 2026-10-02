# Suggestion rules: risk band, buffer, cash-out fee tip, savings plan, what-if change, spending summary.
# Pure functions: numbers and tables in, plain dicts out. No web code, nothing moves money.
# All data is simulated.

import math  # Rounding up and down.

from src import config as cfg  # Central settings.


def as_suggestion(kind, **data):
    """Wrap a suggestion so it always needs the user's tap and never acts by itself."""
    return {"type": kind, **data,
            "requires_user_confirmation": True,  # The user must accept it.
            "auto_action": False}  # The app never moves money on its own.


def risk_band(alert, probability):
    """Low if no alert; Medium if alert below RISK_BAND_HIGH_PROB; High otherwise."""
    if not alert:
        return "low"
    return "medium" if probability < cfg.RISK_BAND_HIGH_PROB else "high"


def round_up(amount, step):
    """Round up to the next multiple of step (e.g. 1,234 -> 1,500 for step 500)."""
    return int(math.ceil(amount / step) * step)


def round_down(amount, step):
    """Round down to the previous multiple of step (e.g. 1,234 -> 1,000 for step 500)."""
    return int(math.floor(amount / step) * step)


def shown_min_balance(predicted_min_balance):
    """The helper model's minimum balance as shown: rounded to BUFFER_ROUND_BDT, never below 0."""
    return max(0, int(round(predicted_min_balance / cfg.BUFFER_ROUND_BDT) * cfg.BUFFER_ROUND_BDT))


def buffer_amount(avg_daily_spend, balance_day20):
    """Suggested amount to keep unspent until month-end (only called when there is an alert).

    A rule, not a model output: BUFFER_DAYS_OF_SPEND days of the user's own average daily spending
    (an ASSUMPTION), rounded up, at least BUFFER_MIN_BDT, capped by the balance rounded down.
    Returns (amount, capped_by_balance). A cap of 0 means no buffer.
    """
    days_of_spend = cfg.BUFFER_DAYS_OF_SPEND * max(avg_daily_spend or 0, 0)  # A few days of usual spending.
    wanted = max(round_up(days_of_spend, cfg.BUFFER_ROUND_BDT), cfg.BUFFER_MIN_BDT)  # Rounded up, at least the minimum.
    can_keep = round_down(max(balance_day20, 0), cfg.BUFFER_ROUND_BDT)  # Cannot keep more than you have.
    # Never negative, never above the current balance; capped when the balance cannot hold the days of spending.
    return max(0, min(wanted, can_keep)), can_keep < wanted


def counted_cashouts(tx_month):
    """Cash-outs on days 1 to PREDICTION_DAY, leaving out day 1 if CASHOUT_SAVER_EXCLUDE_DAY1."""
    first_day = 2 if cfg.CASHOUT_SAVER_EXCLUDE_DAY1 else 1  # Day 1 cash-outs are mostly balance sweeps.
    mask = ((tx_month["type"] == "cash_out")
            & (tx_month["day"] >= first_day)
            & (tx_month["day"] <= cfg.PREDICTION_DAY))
    return tx_month[mask]


def cashout_saver(tx_month):
    """Fee tip when the user made enough cash-outs; None otherwise. Fees are the ones actually paid."""
    cash = counted_cashouts(tx_month)
    if len(cash) < cfg.CASHOUT_SAVER_MIN_COUNT:
        return None  # Too few cash-outs for a tip to be useful.
    return as_suggestion("cashout_saver",
                         cashout_count=int(len(cash)),  # How many cash-outs we counted.
                         fees_paid_bdt=int(cash["fee"].sum()),  # Fees actually paid on them.
                         fee_rate_pct=round(cfg.CASHOUT_FEE_RATE * 100, 2),  # Placeholder rate, as a percent.
                         fee_rate_label="assumed fee rate (placeholder, not yet sourced)")


def monthly_net(tx_user):
    """Net money per month: money in minus money out, including cash-out fees."""
    signed = tx_user["amount"].where(tx_user["direction"] == "in", -tx_user["amount"])  # In +, out -.
    net = signed - tx_user["fee"]  # Fees are always money out.
    return net.groupby(tx_user["month"]).sum()


def without_day1_cashouts(tx):
    """Drop day-1 cash-outs (and so their fees).

    The generator sweeps balances above one month of income out on day 1, but that limit uses a hidden
    income figure not in the data files, so sweeps cannot be told apart exactly: all day-1 cash-outs go.
    """
    return tx[~((tx["type"] == "cash_out") & (tx["day"] == 1))]


def savings_capacity(tx_user, month):
    """How much the user could save per month, from the months BEFORE `month`.

    Day-1 cash-outs (balance sweeps, a simulation artefact) are left out of the net, for savings only.
    Returns (status, average_net, capacity): status is "no_history" (no earlier month),
    "no_room" (earlier months show nothing left over) or "ok".
    """
    earlier = monthly_net(without_day1_cashouts(tx_user[tx_user["month"] < month]))
    if earlier.empty:
        return "no_history", None, 0  # Month 0 has no earlier months.
    average = max(0, int(earlier.mean()))  # Average net, never below 0.
    capacity = int(math.floor(average * cfg.SAVINGS_CAP_FRACTION))  # Only a share of the surplus.
    if capacity <= 0:
        return "no_room", average, 0
    return "ok", average, capacity


def months_to_reach(goal_bdt, monthly_bdt):
    """Months needed to reach the goal at this monthly amount, and whether it fits SAVINGS_MAX_MONTHS."""
    needed = int(math.ceil(goal_bdt / monthly_bdt))
    return min(needed, cfg.SAVINGS_MAX_MONTHS), needed <= cfg.SAVINGS_MAX_MONTHS


def savings_options(goal_bdt, capacity):
    """Three options: half, three quarters and all of the capacity, with months needed for each."""
    options = []
    for share in (0.5, 0.75, 1.0):  # Shares of the capacity; never more than the capacity itself.
        monthly = int(math.floor(capacity * share))
        if monthly <= 0:
            continue  # Too small to be a real option.
        months, reaches = months_to_reach(goal_bdt, monthly)
        options.append({"monthly_bdt": monthly, "months": months, "reaches_goal": reaches})
    return options


def savings_plan(goal_bdt, months, capacity):
    """Is the goal reachable in `months` within the capacity? If not, the largest feasible plan."""
    needed_monthly = int(math.ceil(goal_bdt / months))  # What the goal asks for per month.
    if needed_monthly <= capacity:
        plan = {"status": "feasible", "monthly_bdt": needed_monthly, "months": months, "reaches_goal": True}
    else:
        plan_months, reaches = months_to_reach(goal_bdt, capacity)  # Save the most we can each month.
        plan = {"status": "not_feasible", "monthly_bdt": capacity, "months": plan_months, "reaches_goal": reaches}
        if not reaches:
            plan["saved_in_max_months_bdt"] = capacity * cfg.SAVINGS_MAX_MONTHS  # What SAVINGS_MAX_MONTHS would give.
    plan["needed_monthly_bdt"] = needed_monthly
    plan["options"] = savings_options(goal_bdt, capacity)
    return plan


def risk_change(old_probability, new_probability):
    """'lower', 'about the same' or 'higher', ignoring changes smaller than WHATIF_SAME_TOLERANCE."""
    diff = new_probability - old_probability
    if diff <= -cfg.WHATIF_SAME_TOLERANCE:
        return "lower"
    if diff >= cfg.WHATIF_SAME_TOLERANCE:
        return "higher"
    return "about the same"


# Transaction types that count as spending, and the category each one is shown under.
SPEND_CATEGORIES = {"merchant_payment": "merchant", "bill_payment": "bills",
                    "mobile_recharge": "recharge", "send_money_family": "family", "cash_out": "cashout"}


def week_ranges():
    """Days 1-7, 8-14, 15-PREDICTION_DAY (weeks of 7 days, the last one cut at PREDICTION_DAY)."""
    return [(start, min(start + 6, cfg.PREDICTION_DAY)) for start in range(1, cfg.PREDICTION_DAY + 1, 7)]


def spending_breakdown(tx_month):
    """Money out on days 1-PREDICTION_DAY by category and by week (cash-out fees included)."""
    spent = tx_month[(tx_month["direction"] == "out") & (tx_month["day"] <= cfg.PREDICTION_DAY)
                     & tx_month["type"].isin(list(SPEND_CATEGORIES))]
    total = spent["amount"] + spent["fee"]  # What actually left the wallet.
    by_type = total.groupby(spent["type"]).sum()
    categories = [{"category": cat, "amount_bdt": int(by_type.get(t, 0))} for t, cat in SPEND_CATEGORIES.items()]
    weeks = [{"start_day": a, "end_day": b,
              "amount_bdt": int(total[(spent["day"] >= a) & (spent["day"] <= b)].sum())}
             for a, b in week_ranges()]
    return categories, weeks
