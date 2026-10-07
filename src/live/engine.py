# Live transactions: validate one new transaction, store it, merge it with the user's simulated month,
# rebuild the day-20 features with the EXISTING feature function, score with the saved model in this
# process, and say what changed. All data is simulated. Nothing here moves money.
#
# How the running balance stays correct (the base tables are never changed):
#   For user u and month m, take u's simulated transactions and daily balances, keep complete earlier
#   months plus days 1..PREDICTION_DAY of month m (the same cut the leakage test uses), and add the live rows.
#   Each live row has a signed effect: money in = +amount, money out = -(amount + fee), with the cash-out
#   fee from the generator's own cashout_fee. For each day k of month m:
#       balance(k) = simulated balance(k) + sum of signed live effects on days <= k.
#   A money-out row must fit the LOWEST balance from its day to PREDICTION_DAY, so no day goes below zero.
#   Days after PREDICTION_DAY and later months are not re-simulated: live rows only change month m's view.

import threading  # One lock for live writes and view rebuilds.
import time  # Scoring time.

import numpy as np  # Number tools.
import pandas as pd  # Table tools.
from xgboost import DMatrix  # Full SHAP contribution vector.

from src import config as cfg  # Types, limits, prediction day.
from src.api import deps, service  # Consent and switches; forecast and the overlay hook.
from src.data.generator import cashout_fee  # The generator's own fee rule (imported, not copied).
from src.db import database  # Live rows and the prediction log.
from src.features.build_features import FEATURES, build_features  # The existing feature function, unchanged.
from src.i18n.messages import render  # The unusual-activity note.
from src.live import budgets  # Budget bars.
from src.models import anomaly  # Unusual-for-you check.
from src.models.predict import load_artifacts, validate  # The saved model and its input checks.

DAY = cfg.PREDICTION_DAY
# ponytail: one lock serialises live writes and view rebuilds for everyone; per-user locks if it ever queues.
LOCK = threading.RLock()
_views = {}  # (user_id, month) -> live view, or None when that user-month has no live rows.
_daily_balance = None  # The simulated daily balances per user, read once.


class Rejected(Exception):
    """A live transaction that failed validation: HTTP status and error code."""

    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


def daily_balance(user_id):
    """The simulated end-of-day balances of one user (all months, all days)."""
    global _daily_balance
    if _daily_balance is None:
        bal = pd.read_csv(cfg.DATA_DIR / "daily_balance.csv")
        _daily_balance = {int(u): g for u, g in bal.groupby("user_id")}
    return _daily_balance[user_id]


def live_rows(user_id, month):
    """Stored live rows for one user-month, oldest first."""
    return database.get().query("SELECT * FROM live_transactions WHERE user_id = ? AND month = ? ORDER BY day, id",
                                (user_id, month))


def signed_effect(row):
    """Money in adds the amount; money out removes the amount plus its fee."""
    return row["amount"] if row["direction"] == "in" else -(row["amount"] + row["fee"])


def cumulative_effects(rows):
    """{day: sum of signed live effects on days <= day} for days 1..PREDICTION_DAY."""
    per_day = np.zeros(DAY + 1)
    for r in rows:
        per_day[r["day"]] += signed_effect(r)
    return dict(zip(range(1, DAY + 1), np.cumsum(per_day[1:]).astype(int)))


def compute_view(user_id, month, rows):
    """Features, the month's transactions and the day 1-20 balances, with these live rows merged in."""
    tx_u = service.state()["tx_by_user"][user_id]
    bal_u = daily_balance(user_id)
    live = pd.DataFrame([{"user_id": user_id, "month": month, "day": r["day"], "type": r["type"],
                          "direction": r["direction"], "amount": r["amount"], "fee": r["fee"], "channel": "live"}
                         for r in rows], columns=tx_u.columns)
    # Complete earlier months plus days 1..PREDICTION_DAY of this month (the leakage-test cut).
    keep_tx = (tx_u["month"] < month) | ((tx_u["month"] == month) & (tx_u["day"] <= DAY))
    keep_bal = (bal_u["month"] < month) | ((bal_u["month"] == month) & (bal_u["day"] <= DAY))
    # Concatenate only when there are live rows: an empty frame could change the column types.
    tx_cut = pd.concat([tx_u[keep_tx], live], ignore_index=True) if rows else tx_u[keep_tx]
    bal_cut = bal_u[keep_bal].copy()
    this_month = bal_cut["month"] == month
    effects = cumulative_effects(rows)
    bal_cut.loc[this_month, "end_of_day_balance"] += bal_cut.loc[this_month, "day"].map(effects).to_numpy()
    # Fairness columns are blank here: build_features only carries them along, the model never sees them.
    users_stub = pd.DataFrame({"user_id": [user_id], **{c: [None] for c in cfg.FAIRNESS_COLUMNS}})
    row = build_features(users_stub, tx_cut, bal_cut).set_index("month").loc[month]
    month_bal = bal_cut[this_month]
    return {"features": {f: (None if pd.isna(row[f]) else float(row[f])) for f in FEATURES},
            "tx_month": (pd.concat([tx_u[tx_u["month"] == month], live], ignore_index=True) if rows
                         else tx_u[tx_u["month"] == month]),
            "balance_by_day": [{"day": int(d), "balance_bdt": int(b)}
                               for d, b in zip(month_bal["day"], month_bal["end_of_day_balance"])]}


def overlay(user_id, month):
    """The service overlay: the live view of a user-month, or None if it has no live rows (cached)."""
    key = (user_id, month)
    with LOCK:
        if key not in _views:
            rows = live_rows(user_id, month)
            _views[key] = compute_view(user_id, month, rows) if rows else None
        return _views[key]


def install():
    """Switch the live overlay on (called at server start, AFTER service.results() is cached)."""
    anomaly.load()
    daily_balance(1)  # Read the balance table now, so the first live score's time is not a file read.
    service.OVERLAY = overlay


def shap_vector(features):
    """All 11 SHAP contributions (log-odds) for one feature set, plus the bias, from the saved model."""
    clf, _, _ = load_artifacts()
    contribs = clf.get_booster().predict(DMatrix(validate(features)), pred_contribs=True)[0]
    return {f: float(c) for f, c in zip(FEATURES, contribs[:-1])}, float(contribs[-1])


def balances_now(user_id, month):
    """Day 1-20 balances with the live rows stored so far."""
    return service.balance_for(user_id, month)


def unusual_note(user_id, month, day, type_, amount, lang):
    """Is this transaction unusual for this user compared with their own earlier (simulated) months?"""
    if not deps.feature_on("unusual_check", user_id):
        return {"enabled": False}
    bundle = anomaly.load()
    history = service.tx_for(user_id)
    history = history[history["month"] < month]
    if bundle is None or history.empty:  # No model yet, or month 0 has no earlier months.
        return {"enabled": True, "available": False, "text": render("unusual_unavailable", lang)}
    by_type = history[history["type"] == type_]["amount"]
    if day > 1:
        opening = next(b["balance_bdt"] for b in balances_now(user_id, month) if b["day"] == day - 1)
    else:  # Day 1 opens with the previous month's last balance.
        prev = daily_balance(user_id)
        opening = int(prev[(prev["month"] == month - 1)]["end_of_day_balance"].iloc[-1])
    row = pd.DataFrame([{"amount": amount, "type": type_, "day": day, "opening_balance": opening,
                         "usual_type": by_type.median() if len(by_type) else np.nan,
                         "usual_all": history["amount"].median()}])
    flagged = bool(anomaly.is_unusual(bundle, row)[0])
    return {"enabled": True, "available": True, "unusual": flagged,
            "text": render("unusual_yes" if flagged else "unusual_no", lang)}


def log(source, user_id, month, outcome, code=None, band=None, alert=None, unusual=None, warnings=None, ms=None):
    """One row in predictions_log (no probability is ever stored)."""
    database.get().execute(
        "INSERT INTO predictions_log (created_at, user_id, month, source, outcome, error_code, band, alert, "
        "unusual, budget_warnings, ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (database.now(), user_id, month, source, outcome, code, band,
         None if alert is None else int(alert), None if unusual is None else int(unusual), warnings, ms))


def check(user_id, month, day, type_, amount, key):
    """Validation in a fixed order. Returns the fee, or raises Rejected with the first failing code."""
    if not deps.feature_on("live_transactions", user_id):
        raise Rejected(403, "feature_disabled")
    if not deps.consent_ok(user_id):
        raise Rejected(403, "consent_required")
    if type_ not in cfg.LIVE_TYPES:
        raise Rejected(422, "unknown_type")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not float(amount).is_integer() \
            or not 0 < amount <= cfg.LIVE_MAX_AMOUNT_BDT:
        raise Rejected(422, "amount_out_of_range")
    if day < 1:
        raise Rejected(422, "invalid")
    if day > DAY:
        raise Rejected(422, "day_after_prediction_day")
    if database.get().one("SELECT id FROM live_transactions WHERE user_id = ? AND idempotency_key = ?",
                          (user_id, key)):
        raise Rejected(409, "duplicate")
    fee = cashout_fee(int(amount)) if type_ == "cash_out" else 0
    if cfg.LIVE_TYPES[type_] == "out":
        lowest = min(b["balance_bdt"] for b in balances_now(user_id, month) if b["day"] >= day)
        if int(amount) + fee > lowest:
            raise Rejected(422, "insufficient_balance")
    return fee


def submit(user_id, month, day, type_, amount, key, lang="en", source="live", batch_id=None):
    """Validate, store, rescore. Returns the response dict, or raises Rejected (logged) / service.NotFound."""
    service.check_user_month(user_id, month)
    with LOCK:
        try:
            fee = check(user_id, month, day, type_, amount, key)
        except Rejected as e:
            log(source, user_id, month, "rejected", e.code)
            raise
        before = service.forecast(user_id, month, lang)
        before_features = service.features_for(user_id, month)
        started = time.perf_counter()
        cur = database.get().execute(
            "INSERT INTO live_transactions (user_id, month, day, type, direction, amount, fee, idempotency_key, "
            "batch_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, month, day, type_, cfg.LIVE_TYPES[type_], int(amount), fee, key, batch_id, database.now()))
        _views.pop((user_id, month), None)  # Rebuild this user-month's view on the next read.
        after = service.forecast(user_id, month, lang)  # Features rebuilt and scored in this process.
        ms = round((time.perf_counter() - started) * 1000, 1)
    unusual = unusual_note(user_id, month, day, type_, int(amount), lang)
    bars = budgets.budget_bars(user_id, month) if deps.feature_on("budget_warnings", user_id) \
        else {"enabled": False, "bars": [], "warnings": 0}
    log(source, user_id, month, "scored", band=after["risk_band"], alert=after["alert"],
        unusual=unusual.get("unusual"), warnings=bars["warnings"], ms=ms)
    reasons_before = [r["feature"] for r in before["reasons"]]
    reasons_after = [r["feature"] for r in after["reasons"]]
    return {"accepted": True, "simulated": True, "computed_on": "this machine", "ms": ms,
            "transaction": {"id": cur.lastrowid, "user_id": user_id, "month": month, "day": day, "type": type_,
                            "direction": cfg.LIVE_TYPES[type_], "amount_bdt": int(amount), "fee_bdt": fee},
            "assessment": {**after, "data_subject": deps.data_subject(user_id)},
            "changed": {"band_before": before["risk_band"], "band_after": after["risk_band"],
                        "alert_before": before["alert"], "alert_after": after["alert"],
                        "reasons_added": [f for f in reasons_after if f not in reasons_before],
                        "reasons_removed": [f for f in reasons_before if f not in reasons_after],
                        "balance_day20_before": int(before_features["balance_day20"]),
                        "balance_day20_after": int(service.features_for(user_id, month)["balance_day20"])},
            "budgets": bars, "unusual": unusual}


def reset(user_id):
    """Delete the live rows of one user (or of everyone when user_id is None). Returns how many."""
    with LOCK:
        db = database.get()
        if user_id is None:
            n = db.execute("DELETE FROM live_transactions").rowcount
            _views.clear()
        else:
            n = db.execute("DELETE FROM live_transactions WHERE user_id = ?", (user_id,)).rowcount
            for key in [k for k in _views if k[0] == user_id]:
                del _views[key]
    return n
