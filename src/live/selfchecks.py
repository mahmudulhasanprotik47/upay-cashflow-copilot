# Self-checks 18-20: live validation, the consent gate, and balance consistency after live transactions.
# They run against a temporary in-memory database with the live overlay switched on only while they run,
# so data/copilot.db and checks 1-16 are never affected. ASCII output only.

from src import config as cfg  # Types, limits, consent version.
from src.api import deps, service  # Access rules; base data and the overlay hook.
from src.data.generator import cashout_fee  # Fee rule, to work the balance out by hand.
from src.db import database  # Temporary database.
from src.live import engine  # Code under test.
from src.models.predict import predict_and_explain  # Top reasons, to compare with the full SHAP vector.
from src.security import auth  # Accounts for the consent check.

DAY = cfg.PREDICTION_DAY


def code_of(fn, *args):
    """The Rejected/ApiError code fn raises, or None if it succeeds."""
    try:
        fn(*args)
    except (engine.Rejected, deps.ApiError) as e:
        return e.code
    except service.NotFound:
        return "not_found"
    return None


def roomy_user_months(month, need, skip=()):
    """User ids whose month-`month` balance stays at or above `need` on days 3..20 (enough room to test with)."""
    out = []
    for (u, m), days in service.state()["balance_by_um"].items():
        if m == month and u not in skip and min(d["balance_bdt"] for d in days if d["day"] >= 3) >= need:
            out.append(u)
    return out


def check_validation(report, u, m):
    """Check 18: every bad case is rejected with its own code, and nothing is stored for a rejection."""
    db = database.get()
    lowest = min(b["balance_bdt"] for b in service.balance_for(u, m) if b["day"] >= 5)
    submit = lambda day, type_, amount, key: engine.submit(u, m, day, type_, amount, key)  # noqa: E731
    cases = [("unknown type", code_of(submit, 5, "gift", 100, "k1"), "unknown_type"),
             ("amount zero", code_of(submit, 5, "merchant_payment", 0, "k2"), "amount_out_of_range"),
             ("amount too big", code_of(submit, 5, "add_money", cfg.LIVE_MAX_AMOUNT_BDT + 1, "k3"), "amount_out_of_range"),
             ("amount not whole", code_of(submit, 5, "merchant_payment", 10.5, "k4"), "amount_out_of_range"),
             ("amount bool", code_of(submit, 5, "merchant_payment", True, "k5"), "amount_out_of_range"),
             ("day after 20", code_of(submit, DAY + 1, "merchant_payment", 100, "k6"), "day_after_prediction_day"),
             ("day zero", code_of(submit, 0, "merchant_payment", 100, "k7"), "invalid"),
             ("more than lowest later balance", code_of(submit, 5, "merchant_payment", lowest + 1, "k8"),
              "insufficient_balance"),
             ("unknown month", code_of(engine.submit, u, cfg.N_MONTHS, 5, "add_money", 100, "k9"), "not_found")]
    if cashout_fee(lowest) > 0:  # Amount alone fits, amount + fee does not.
        cases.append(("cash-out fee counted", code_of(submit, 5, "cash_out", lowest, "k10"), "insufficient_balance"))
    db.execute("INSERT INTO settings (scope, key, value, updated_at) VALUES ('global', 'live_transactions', 'off', 0)")
    cases.append(("switch off", code_of(submit, 5, "add_money", 100, "k11"), "feature_disabled"))
    db.execute("DELETE FROM settings")
    stored_after_rejections = db.one("SELECT COUNT(*) n FROM live_transactions")["n"]
    cases.append(("valid accepted", code_of(submit, 5, "add_money", 100, "ok1"), None))
    cases.append(("duplicate key", code_of(submit, 6, "add_money", 100, "ok1"), "duplicate"))
    bad = [name for name, got, want in cases if got != want]
    stored = db.one("SELECT COUNT(*) n FROM live_transactions")["n"]
    logged = db.one("SELECT COUNT(*) n FROM predictions_log WHERE outcome = 'rejected'")["n"]
    if stored_after_rejections != 0 or stored != 1:
        bad.append("rows stored for rejections")
    if logged != len(cases) - 2:  # Every rejection except the unknown month (404 before validation) is logged.
        bad.append(f"rejections logged {logged}")
    engine.reset(u)
    return report(18, "live validation rejects every bad case", not bad,
                  f"failed: {', '.join(bad)}" if bad else f"{len(cases)} cases")


def check_consent(report, linked_user, free_user):
    """Check 19: a linked user needs a current, unwithdrawn consent; an unlinked fixture does not."""
    db = database.get()
    acc = auth.create_account("consent_check", "consent-pass-1", "customer", linked_user)
    p_cus = auth.principal_of(db.one("SELECT * FROM accounts WHERE id = ?", (acc,)))
    p_ana = {"kind": "session", "account_id": None, "name": "ana", "role": "analyst", "user_id": None}
    live = lambda key: code_of(engine.submit, linked_user, 4, 5, "add_money", 100, key)  # noqa: E731
    bad = []
    if (live("c1"), code_of(deps.check_read, p_cus, linked_user), code_of(deps.check_read, p_ana, linked_user)) \
            != ("consent_required",) * 3:
        bad.append("no consent")
    db.execute("INSERT INTO consents (user_id, notice_version, given_at) VALUES (?, 'old-notice', 1)", (linked_user,))
    if code_of(deps.check_read, p_cus, linked_user) != "consent_required":
        bad.append("old notice")
    db.execute("INSERT INTO consents (user_id, notice_version, given_at) VALUES (?, ?, 2)",
               (linked_user, cfg.CONSENT_NOTICE_VERSION))
    if (live("c2"), code_of(deps.check_read, p_cus, linked_user)) != (None, None):
        bad.append("given")
    db.execute("UPDATE consents SET withdrawn_at = 3 WHERE user_id = ?", (linked_user,))
    if (live("c3"), code_of(deps.check_read, p_cus, linked_user)) != ("consent_required",) * 2:
        bad.append("withdrawn")
    if code_of(deps.check_read, p_ana, free_user) is not None or deps.data_subject(free_user) != "simulated_fixture":
        bad.append("fixture")
    engine.reset(linked_user)
    return report(19, "consent gate (linked users only)", not bad,
                  f"failed: {', '.join(bad)}" if bad else "none, old, given, withdrawn, fixture")


def check_balance(report, u, m):
    """Check 20: base balance + cumulative live effects = chart = balance_day20; no day below zero."""
    bad = []
    # (a) With no live rows the rebuilt view equals the loaded data exactly (the cut method is sound).
    for uu, mm in list(service.state()["features"].index[::250])[:20]:
        view = engine.compute_view(int(uu), int(mm), [])
        service.OVERLAY, saved = None, service.OVERLAY
        same = view["features"] == service.features_for(int(uu), int(mm)) \
            and view["balance_by_day"] == service.balance_for(int(uu), int(mm))
        service.OVERLAY = saved
        bad += [] if same else [f"empty view {uu}/{mm}"]
    # (b) Four live transactions, then the balance worked out by hand.
    base = {b["day"]: b["balance_bdt"] for b in service.state()["balance_by_um"][(u, m)]}
    before = service.features_for(u, m)
    plan = [(3, "add_money", 1500), (5, "merchant_payment", 700), (10, "cash_out", 1000), (DAY, "bill_payment", 300)]
    for i, (day, type_, amount) in enumerate(plan):
        engine.submit(u, m, day, type_, amount, f"bal{i}")
    effect = {3: 1500, 5: -700, 10: -(1000 + cashout_fee(1000)), DAY: -300}
    by_hand = {k: base[k] + sum(v for d, v in effect.items() if d <= k) for k in base}
    chart = {b["day"]: b["balance_bdt"] for b in service.balance_for(u, m)}
    after = service.features_for(u, m)
    if chart != by_hand:
        bad.append("chart")
    if after["balance_day20"] != chart[DAY] or after["min_balance_d1_20"] != min(chart.values()):
        bad.append("features")
    if min(chart.values()) < 0:
        bad.append("negative")
    if (after["total_inflow_d1_20"] - before["total_inflow_d1_20"] != 1500
            or after["total_outflow_d1_20"] - before["total_outflow_d1_20"] != 700 + 1000 + cashout_fee(1000) + 300
            or after["cashout_count_d1_20"] - before["cashout_count_d1_20"] != 1
            or after["bill_payments_d1_20"] - before["bill_payments_d1_20"] != 1):
        bad.append("sums")
    # (c) The full SHAP vector agrees with the model's top reasons.
    vector, _ = engine.shap_vector(after)
    top = sorted(vector, key=lambda f: -abs(vector[f]))[:cfg.TOP_REASONS]
    if top != [r["feature"] for r in predict_and_explain(after)["reasons"]] or len(vector) != 11:
        bad.append("shap")
    # (d) Reset brings back the simulated month.
    engine.reset(u)
    if service.balance_for(u, m) != service.state()["balance_by_um"][(u, m)]:
        bad.append("reset")
    return report(20, "balance consistency after live transactions", not bad,
                  f"failed: {', '.join(bad)}" if bad else f"user {u} month {m}, 4 live rows, 20 empty views")


def check_live(report):
    """Run checks 18-20 with a temporary database and the overlay on; always switch both off again."""
    db = database.Database(":memory:")
    database.use(db)
    engine.reset(None)
    service.OVERLAY = engine.overlay
    try:
        roomy = roomy_user_months(4, 5000)
        check_validation(report, roomy[0], 4)
        check_consent(report, roomy[1], roomy[2])
        check_balance(report, roomy[3], 4)
    finally:
        service.OVERLAY = None
        engine.reset(None)
        db.close()
        database.use(None)
