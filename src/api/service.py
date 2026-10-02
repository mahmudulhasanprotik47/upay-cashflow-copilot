# Service layer for the Cash-Flow Copilot: plain functions the API calls. No web code here.
# Loads data, features, models and metrics once, then answers forecast, savings, what-if and summary
# questions in English or Bangla. All data is simulated. Nothing here moves money.
# Run: python -m src.api.service   (runs the self-checks; prints plain ASCII lines only)

import functools  # Load everything once and reuse it.
import json  # Reads the metrics, fairness and SHAP files.
import math  # Checks for NaN and infinity.
import numbers  # Checks that a value is a real number.
import re  # Finds numbers inside rendered text (self-check 8).
import time  # Measures start-up and response times.

import pandas as pd  # Table tools.

from src import config as cfg  # Central settings.
from src.features.build_features import FEATURES, build_features, load_data  # Phase 2 features.
from src.i18n import messages  # English and Bangla templates.
from src.i18n.messages import render  # Fills a template.
from src.models.predict import load_artifacts, predict_and_explain  # Phase 2 model code (reused).
from src.rules import suggestions as rules  # Suggestion rules.

# Feature groups used to check what-if inputs.
MONEY_FEATURES = ["balance_day20", "min_balance_d1_20", "avg_daily_spend_d1_20", "total_inflow_d1_20",
                  "total_outflow_d1_20", "cashout_amount_d1_20"]  # Amounts in BDT.
WHOLE_NUMBER_FEATURES = ["cashout_count_d1_20", "bill_payments_d1_20", "days_since_last_inflow",
                         "prev_month_shortfall"]  # Counts, days and yes/no must be whole numbers.
FEATURE_LIMITS = {"days_since_last_inflow": cfg.PREDICTION_DAY,  # Cannot be longer than the days we see.
                  "prev_month_shortfall": 1}  # Yes (1) or no (0). Everything else: up to WHATIF_MAX_BDT.

# Message keys for the what-if risk change.
RISK_CHANGE_KEYS = {"lower": "whatif_lower", "about the same": "whatif_same", "higher": "whatif_higher"}


class NotFound(Exception):
    """The user or month does not exist."""


class InvalidInput(Exception):
    """An input is not allowed. The API turns this into a short generic error."""


def read_json(name):
    """Read one JSON file from the artifacts folder."""
    return json.loads((cfg.ARTIFACTS_DIR / name).read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def state():
    """Load data, features, models and metrics ONCE; every call after that reuses them."""
    started = time.perf_counter()
    users, tx, bal = load_data()  # Simulated users, transactions and daily balances.
    # Keep only the 11 model inputs: labels, future columns and fairness columns are dropped here.
    feat = build_features(users, tx, bal).set_index(["user_id", "month"])[FEATURES]
    load_artifacts()  # Warm the model cache in predict.py.
    seen = bal[bal["day"] <= cfg.PREDICTION_DAY]  # Days 1-20 only, for the chart.
    metrics = read_json("metrics.json")
    loaded = {
        "features": feat,
        "tx_by_user": {int(u): g for u, g in tx.groupby("user_id")},  # Transactions per user.
        "balance_by_um": {(int(u), int(m)): [{"day": int(d), "balance_bdt": int(b)}
                                             for d, b in zip(g["day"], g["end_of_day_balance"])]
                          for (u, m), g in seen.groupby(["user_id", "month"])},
        "users": [{"user_id": int(u), "income_type": t}  # No fairness columns.
                  for u, t in zip(users["user_id"], users["income_type"])],
        "metrics": metrics,
        "fairness": read_json("fairness.json"),
        "shap_global": read_json("shap_global.json"),
        "mae": int(round(metrics["min_balance_mae_bdt"]["model_all"])),  # Helper model's typical error.
    }
    loaded["startup_seconds"] = round(time.perf_counter() - started, 2)
    return loaded


def check_user_month(user_id, month):
    """Raise NotFound unless this user-month exists (whole numbers only)."""
    for value in (user_id, month):
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidInput("user_id and month must be whole numbers")
    if (user_id, month) not in state()["features"].index:
        raise NotFound("no such user-month")


def features_for(user_id, month):
    """The 11 model inputs for one user-month, with blanks as None."""
    row = state()["features"].loc[(user_id, month)]
    return {name: (None if pd.isna(row[name]) else float(row[name])) for name in FEATURES}


def tx_for(user_id, month=None):
    """One user's transactions, optionally for one month only."""
    tx = state()["tx_by_user"][user_id]
    return tx if month is None else tx[tx["month"] == month]


def display_value(feature, value):
    """A reason's value as the user sees it, and its unit."""
    if feature == "inflow_vs_prev_month":
        return int(round(value * 100)), "percent"  # A ratio shown as a percentage of last month.
    if feature in MONEY_FEATURES:
        return int(round(value)), "BDT"
    return int(round(value)), "count"  # Counts, days and yes/no.


def reason_key(feature, value, direction):
    """Message key for one reason. days_since_last_inflow 20 means nothing came in yet; 0 means today."""
    if feature == "days_since_last_inflow" and value >= cfg.PREDICTION_DAY:
        feature += "_none"  # No inflow at all on days 1-20.
    elif feature == "days_since_last_inflow" and value == 0:
        feature += "_today"  # Money came in on day 20 itself.
    return f"reason_{feature}_{direction}"


def reason_items(raw_reasons, lang):
    """Turn the model's top reasons into plain sentences, skipping blank values."""
    items = []
    for r in raw_reasons:
        if r["value"] is None:
            continue  # Blank (e.g. no previous month): nothing honest to say.
        if r["feature"] == "prev_month_shortfall" and (r["value"] == 1) != (r["direction"] == "up"):
            continue  # Yes/no wording must match the direction, otherwise the sentence would be odd.
        value, unit = display_value(r["feature"], r["value"])
        items.append({"feature": r["feature"], "value": value, "unit": unit, "direction": r["direction"],
                      "text": render(reason_key(r["feature"], value, r["direction"]), lang, value=value)})
    return items


def assess(features, lang):
    """Risk band, alert, buffer and reasons for one set of inputs. Returns (public dict, probability).

    The probability is only used inside the service; it never goes into a response.
    """
    raw = predict_and_explain(features)  # Phase 2 model, reused as is.
    band = rules.risk_band(raw["alert"], raw["probability"])
    out = {"risk_band": band, "risk_band_text": render(f"band_{band}", lang), "alert": bool(raw["alert"]),
           "floor_bdt": cfg.SHORTFALL_FLOOR_BDT, "predicted_min_balance": None,  # None unless alert.
           "reasons": reason_items(raw["reasons"], lang), "suggestions": [], "notes": []}
    if not raw["alert"]:
        return out, raw["probability"]  # Low band: no minimum balance, no buffer, no warning.
    shown = rules.shown_min_balance(raw["predicted_min_balance"])
    if shown < cfg.SHORTFALL_FLOOR_BDT:  # At or above the floor the two models disagree, so show nothing.
        out["predicted_min_balance"] = {"amount_bdt": shown, "is_estimate": True,
                                        "typical_error_bdt": state()["mae"]}  # Helper model's typical error.
    out["notes"].append({"type": "shortfall_warning",
                         "text": render("shortfall_warning", lang, floor=cfg.SHORTFALL_FLOOR_BDT)})
    buffer, capped = rules.buffer_amount(features["avg_daily_spend_d1_20"],
                                         features["balance_day20"])  # A rule, not a model.
    if buffer > 0:
        # Capped by the balance: no "days of spending" claim. Otherwise the days wording.
        text = (render("buffer_capped", lang, buffer=buffer) if capped
                else render("buffer", lang, buffer=buffer, days=cfg.BUFFER_DAYS_OF_SPEND))
        out["suggestions"].append(rules.as_suggestion(
            "buffer", amount_bdt=buffer, days_of_spend=cfg.BUFFER_DAYS_OF_SPEND, capped_by_balance=capped,
            text=text))
    else:
        out["notes"].append({"type": "no_buffer_low_balance", "text": render("no_buffer_low_balance", lang)})
    out["notes"].append({"type": "savings_blocked_alert", "text": render("savings_blocked_alert", lang)})
    return out, raw["probability"]


def forecast(user_id, month, lang="en"):
    """Full forecast for one user-month: band, reasons, suggestions, chart data, disclaimer."""
    check_user_month(user_id, month)
    out, _ = assess(features_for(user_id, month), lang)
    saver = rules.cashout_saver(tx_for(user_id, month))
    if saver:
        saver["text"] = render("cashout_saver", lang, count=saver["cashout_count"],
                               fees=saver["fees_paid_bdt"], fee_rate=saver["fee_rate_pct"])
        out["suggestions"].append(saver)
    return {"user_id": user_id, "month": month, "lang": lang,
            "month_in_training": month < cfg.N_MONTHS - cfg.TEST_MONTHS,  # Months 0-3 were used to train.
            **out,
            "balance_by_day": state()["balance_by_um"][(user_id, month)],
            "disclaimer": render("disclaimer", lang)}


def check_savings_inputs(goal_bdt, months):
    """Goal: whole BDT, 1 to WHATIF_MAX_BDT. Months: whole number, 1 to SAVINGS_MAX_MONTHS."""
    for value, top in ((goal_bdt, cfg.WHATIF_MAX_BDT), (months, cfg.SAVINGS_MAX_MONTHS)):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= top:
            raise InvalidInput("goal or months out of range")


def plan_text(plan, goal_bdt, months, capacity, lang):
    """The sentence for a feasible, not feasible, or not-reachable-in-time plan."""
    if plan["status"] == "feasible":
        return render("savings_feasible", lang, goal=goal_bdt, months=months,
                      monthly=plan["monthly_bdt"], capacity=capacity)
    if plan["reaches_goal"]:
        return render("savings_not_feasible", lang, goal=goal_bdt, months=months, needed=plan["needed_monthly_bdt"],
                      capacity=capacity, months_needed=plan["months"])
    return render("savings_not_reached", lang, goal=goal_bdt, months=months, needed=plan["needed_monthly_bdt"],
                  capacity=capacity, max_months=cfg.SAVINGS_MAX_MONTHS, saved=plan["saved_in_max_months_bdt"])


def option_text(option, lang):
    """One savings option as a sentence."""
    if option["reaches_goal"]:
        return render("savings_option", lang, monthly=option["monthly_bdt"], months=option["months"])
    return render("savings_option_not_reached", lang, monthly=option["monthly_bdt"],
                  max_months=cfg.SAVINGS_MAX_MONTHS)


def savings_plan(user_id, month, goal_bdt, months, lang="en"):
    """Savings plan for a goal. None while the user has an alert (buffer first) or has no room to save."""
    check_user_month(user_id, month)
    check_savings_inputs(goal_bdt, months)
    out = {"user_id": user_id, "month": month, "lang": lang, "goal_bdt": goal_bdt, "target_months": months,
           "max_months": cfg.SAVINGS_MAX_MONTHS, "capacity_bdt": None, "plan": None, "options": []}
    assessment, _ = assess(features_for(user_id, month), lang)
    if assessment["alert"]:
        status, capacity = "blocked_alert", 0  # Never a savings suggestion while at risk.
    else:
        status, _, capacity = rules.savings_capacity(tx_for(user_id), month)
    if status != "ok":
        key = {"blocked_alert": "savings_blocked_alert", "no_history": "savings_no_history",
               "no_room": "savings_no_room"}[status]
        return {**out, "status": status, "text": render(key, lang), "disclaimer": render("disclaimer", lang)}
    plan = rules.savings_plan(goal_bdt, months, capacity)
    options = [{**o, "text": option_text(o, lang)} for o in plan.pop("options")]
    status = plan.pop("status")
    return {**out, "status": status, "capacity_bdt": capacity,
            "plan": rules.as_suggestion("savings_plan", **plan),
            "options": options, "text": plan_text({**plan, "status": status}, goal_bdt, months, capacity, lang),
            "disclaimer": render("disclaimer", lang)}


def clean_overrides(overrides):
    """Allow only the 11 model features with finite, non-negative numbers within limits."""
    if not isinstance(overrides, dict) or not overrides:
        raise InvalidInput("overrides must be a non-empty object")
    clean = {}
    for name, value in overrides.items():
        if name not in FEATURES:
            raise InvalidInput("unknown input name")
        if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
            raise InvalidInput("inputs must be finite numbers")
        if value < 0 or value > FEATURE_LIMITS.get(name, cfg.WHATIF_MAX_BDT):
            raise InvalidInput("input out of range")
        if name in WHOLE_NUMBER_FEATURES and not float(value).is_integer():
            raise InvalidInput("input must be a whole number")
        clean[name] = int(value) if float(value).is_integer() else float(value)
    return clean


def whatif(user_id, month, overrides, lang="en"):
    """Forecast with some inputs changed, next to the original. Not a re-simulation of the month."""
    check_user_month(user_id, month)
    changed = clean_overrides(overrides)
    original_features = features_for(user_id, month)
    original, p_before = assess(original_features, lang)
    new, p_after = assess({**original_features, **changed}, lang)
    change = rules.risk_change(p_before, p_after)  # Probabilities stay inside the service.
    return {"user_id": user_id, "month": month, "lang": lang, "changed_inputs": changed,
            "risk_change": change, "risk_change_text": render(RISK_CHANGE_KEYS[change], lang),
            "original": original, "whatif": new,
            "note": render("whatif_note", lang), "disclaimer": render("disclaimer", lang)}


def list_users():
    """User ids and income types for a dropdown. No fairness columns."""
    return state()["users"]


def model_results():
    """Metrics, fairness and global SHAP for a results tab, plus the honest summary."""
    s = state()
    return {"metrics": s["metrics"], "fairness": s["fairness"], "shap_global": s["shap_global"],
            "honest_summary": {"en": render("honest_summary", "en"), "bn": render("honest_summary", "bn")},
            "disclaimer": {"en": render("disclaimer", "en"), "bn": render("disclaimer", "bn")}}


def month_summary(user_id, month, lang="en"):
    """Spending on days 1-20 by category and by week, with a sentence about the biggest week."""
    check_user_month(user_id, month)
    categories, weeks = rules.spending_breakdown(tx_for(user_id, month))
    for c in categories:
        c["label"] = render(f"cat_{c['category']}", lang)  # Category name in the chosen language.
    biggest = max(weeks, key=lambda w: w["amount_bdt"])
    top = max(categories, key=lambda c: c["amount_bdt"])
    total = sum(c["amount_bdt"] for c in categories)
    text = render("summary_biggest_week", lang, start_day=biggest["start_day"], end_day=biggest["end_day"],
                  amount=biggest["amount_bdt"], total=total, category=top["label"],
                  category_amount=top["amount_bdt"])
    return {"user_id": user_id, "month": month, "lang": lang, "total_spent_bdt": total,
            "by_category": categories, "by_week": weeks, "biggest_week": biggest,
            "text": text, "disclaimer": render("disclaimer", lang)}


# ---------------------------------------------------------------------------
# Self-checks (python -m src.api.service). Plain ASCII output only.
# ---------------------------------------------------------------------------

def report(number, name, ok, detail=""):
    """Print one PASS/FAIL line under 100 characters."""
    line = f"{number}. {'PASS' if ok else 'FAIL'} {name}" + (f" ({detail})" if detail else "")
    print(line[:99])
    return ok


def walk(obj):
    """Yield every (key, value) pair in a nested response."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def numbers_in_data(response):
    """Every number stored in a response (not counting numbers written inside text)."""
    return {float(v) for _, v in walk(response) if isinstance(v, (int, float)) and not isinstance(v, bool)}


def numbers_in_text(response):
    """Every number written inside the text of a response (Bengali digits turned back into 0-9)."""
    back = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
    found = set()
    for _, v in walk(response):
        if isinstance(v, str) and v not in FEATURES:  # Feature names like min_balance_d1_20 are not text.
            found |= {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", v.translate(back))}
    return found


def has_fairness_data(response):
    """True if a fairness column name or a region/age-band value appears anywhere."""
    banned_values = set(cfg.REGIONS) | set(cfg.AGE_BANDS)  # Income bands share words with risk bands.
    return any(k in cfg.FAIRNESS_COLUMNS or (isinstance(v, str) and v in banned_values) for k, v in walk(response))


def low_band_ok(assessment):
    """A Low band answer carries no minimum balance, no buffer and no shortfall warning."""
    return (assessment["risk_band"] != "low"
            or (assessment["predicted_min_balance"] is None
                and not any(s["type"] == "buffer" for s in assessment["suggestions"])
                and not assessment["notes"]))


def rejected(user_id, month, overrides):
    """True if whatif refuses these overrides."""
    try:
        whatif(user_id, month, overrides)
    except InvalidInput:
        return True
    return False


def timed(fn, *args):
    """Run fn and return (result, seconds)."""
    start = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - start


@functools.lru_cache(maxsize=1)
def sampled_alert_rows(n=300):
    """The first n user-months with an alert, in a fixed shuffled order (seed SEED)."""
    rows = []
    for u, m in state()["features"].sample(frac=1, random_state=cfg.SEED).index:
        if predict_and_explain(features_for(int(u), int(m)))["alert"]:
            rows.append((int(u), int(m)))
        if len(rows) == n:
            break
    return rows


def expected_wanted(features):
    """The uncapped buffer by hand: days of spending rounded up, at least the minimum (checks 12 and 16)."""
    step = cfg.BUFFER_ROUND_BDT
    return max(math.ceil(cfg.BUFFER_DAYS_OF_SPEND * features["avg_daily_spend_d1_20"] / step) * step,
               cfg.BUFFER_MIN_BDT)


def expected_buffer(features):
    """The buffer rule worked out again by hand, without the rules module (for self-check 12)."""
    step = cfg.BUFFER_ROUND_BDT
    cap = math.floor(max(features["balance_day20"], 0) / step) * step  # The balance rounded down.
    return max(0, min(expected_wanted(features), cap))


# The "3 days of your usual spending" wording, per language (for self-check 16).
DAYS_WORDING = {"en": "days of your usual spending", "bn": "দিনের সমান"}


def has_causal_word(text, lang):
    """True if a reason claims a cause (pushes, helps, ... or the Bangla equivalents)."""
    if lang == "en":
        return any(re.search(rf"\b{w}\b", text.lower()) for w in cfg.CAUSAL_WORDS_EN)
    return any(w in text for w in cfg.CAUSAL_WORDS_BN)


def has_error_sentence(text):
    """True if a buffer text mentions the typical error (en or bn wording)."""
    return "typical" in text.lower() or "off by" in text.lower() or "পার্থক্য" in text


def fake_reason(feature, value, direction="up"):
    """A one-item reason list as predict_and_explain would give it (for checks 13 and 14)."""
    return [{"feature": feature, "value": float(value), "direction": direction}]


def self_checks():
    """Run checks 1-16 and print PASS/FAIL per line."""
    s = state()
    print(f"Start-up: {s['startup_seconds']} s")
    saved = pd.read_csv(cfg.ARTIFACTS_DIR / "test_predictions.csv").sort_values(["user_id", "month"])
    alert_row = saved[saved["alert"] == 1].iloc[0]
    calm_row = saved[saved["alert"] == 0].iloc[0]
    first_user = int(saved.iloc[0]["user_id"])
    samples = [(int(alert_row["user_id"]), int(alert_row["month"])),
               (int(calm_row["user_id"]), int(calm_row["month"])), (first_user, 0)]
    results = []  # Every response produced, for checks 6, 8 and 9.

    # 1. Three sample user-months: alert, no alert, month 0 (blank prev_month_shortfall).
    f_alert, f_calm, f_zero = (forecast(u, m, "en") for u, m in samples)
    results += [f_alert, f_calm, f_zero] + [forecast(u, m, "bn") for u, m in samples]
    zero_blank = features_for(first_user, 0)["prev_month_shortfall"] is None
    ok1 = (f_alert["alert"] and not f_calm["alert"] and zero_blank
           and all(r["feature"] != "prev_month_shortfall" for r in f_zero["reasons"]))
    report(1, "forecast: alert, no alert, month 0", ok1,
           f"bands {f_alert['risk_band']}/{f_calm['risk_band']}/{f_zero['risk_band']}")

    # 2. Probability matches the saved test prediction.
    raw = predict_and_explain(features_for(*samples[0]))
    ok2 = abs(raw["probability"] - alert_row["probability"]) < 1e-6 and raw["alert"] == bool(alert_row["alert"])
    report(2, "probability matches test_predictions.csv", ok2, f"user {samples[0][0]} month {samples[0][1]}")

    # 3. Every template renders in en and bn, no leftover placeholder, no banned words in either language.
    values = messages.sample_values()
    leftovers = banned = 0
    for key in messages.MESSAGES:
        for lang in cfg.LANGUAGES:
            text = render(key, lang, **values)
            leftovers += ("{" in text or "}" in text)
            banned += lang == "en" and any(w in text.lower() for w in cfg.BANNED_WORDS_EN)
            banned += lang == "bn" and any(w in text for w in cfg.BANNED_WORDS_BN)  # Bangla pressure words.
    try:
        render("buffer", "en")  # Missing values must raise a clear error.
        missing_raises = False
    except messages.MissingValueError:
        missing_raises = True
    report(3, "templates render, no placeholders, no banned words", not leftovers and not banned
           and missing_raises, f"{len(messages.MESSAGES)} keys x 2 languages")

    # 4. Buffer within 0..balance_day20; no savings with an alert; savings never above capacity.
    sample_index = s["features"].sample(n=300, random_state=cfg.SEED).index
    goal_months = [(cfg.BUFFER_ROUND_BDT * 4, 3), (cfg.BUFFER_ROUND_BDT * 40, 12), (cfg.BUFFER_ROUND_BDT * 400, 6)]
    bad_buffer = bad_savings = 0
    for u, m in sample_index:
        f = forecast(int(u), int(m))
        results.append(f)
        balance = features_for(int(u), int(m))["balance_day20"]
        bad_buffer += any(not 0 <= sg["amount_bdt"] <= balance for sg in f["suggestions"] if sg["type"] == "buffer")
        for goal, months in goal_months:
            p = savings_plan(int(u), int(m), goal, months)
            results.append(p)
            if f["alert"]:
                bad_savings += p["status"] != "blocked_alert" or p["plan"] is not None
            elif p["plan"]:
                amounts = [p["plan"]["monthly_bdt"]] + [o["monthly_bdt"] for o in p["options"]]
                bad_savings += max(amounts) > p["capacity_bdt"]
    report(4, "buffer in range, no savings on alert, savings <= capacity", not bad_buffer and not bad_savings,
           f"{len(sample_index)} rows, bad {bad_buffer + bad_savings}")

    # 5. what-if: +1000 BDT on balance_day20 never raises the risk; bad inputs rejected.
    raised = 0
    for u, m in sample_index[:200]:
        feats = features_for(int(u), int(m))
        bigger = min(feats["balance_day20"] + 1000, cfg.WHATIF_MAX_BDT)
        w = whatif(int(u), int(m), {"balance_day20": bigger})
        results.append(w)
        p_before = predict_and_explain(feats)["probability"]
        p_after = predict_and_explain({**feats, "balance_day20": bigger})["probability"]
        raised += p_after > p_before or w["risk_change"] == "higher"
    u0, m0 = samples[0]
    bad_inputs = [{"not_a_feature": 1}, {"balance_day20": "1000"}, {"balance_day20": float("nan")},
                  {"balance_day20": float("inf")}, {"balance_day20": -1}, {"balance_day20": True},
                  {"balance_day20": cfg.WHATIF_MAX_BDT + 1}, {"cashout_count_d1_20": 1.5}, {}]
    all_rejected = all(rejected(u0, m0, o) for o in bad_inputs)
    report(5, "whatif: +1000 never raises risk; bad inputs rejected", not raised and all_rejected,
           f"raised {raised}/200, rejected {all_rejected}")

    # 6. No fairness column anywhere in forecast, savings or what-if responses.
    leaks = sum(has_fairness_data(r) for r in results)
    report(6, "no fairness columns in responses", leaks == 0, f"{len(results)} responses checked")

    # 7. Timing per call (target under 1 second).
    timings = {"forecast": timed(forecast, u0, m0, "bn")[1],
               "savings_plan": timed(savings_plan, samples[1][0], samples[1][1], cfg.BUFFER_ROUND_BDT * 40, 12)[1],
               "whatif": timed(whatif, u0, m0, {"balance_day20": cfg.BUFFER_ROUND_BDT})[1],
               "month_summary": timed(month_summary, u0, m0, "bn")[1],
               "list_users": timed(list_users)[1], "model_results": timed(model_results)[1]}
    for name, secs in timings.items():
        print(f"   {name}: {secs * 1000:.1f} ms")
    report(7, "every call under 1 second", max(timings.values()) < 1.0,
           f"start-up {s['startup_seconds']} s (one-off)")

    # 8. Every number written in a message appears in the response data (no invented numbers).
    results += [month_summary(u, m, lang) for u, m in samples for lang in cfg.LANGUAGES]
    results += [savings_plan(samples[1][0], samples[1][1], cfg.BUFFER_ROUND_BDT * 400, 6, "bn")]
    invented = sum(not numbers_in_text(r) <= numbers_in_data(r) for r in results)
    report(8, "every number in messages is in the response data", invented == 0,
           f"{len(results)} responses, {invented} with invented numbers")

    # 9. A Low band answer never contains a minimum-balance number (forecasts and both what-if sides).
    assessments = [r for r in results if "risk_band" in r]
    assessments += [side for r in results if "whatif" in r for side in (r["original"], r["whatif"])]
    low_count = sum(a["risk_band"] == "low" for a in assessments)
    report(9, "Low band never shows a min-balance number", all(low_band_ok(a) for a in assessments),
           f"{low_count} low-band answers checked")

    # 10. An alert whose minimum balance is at or above the floor shows no minimum balance (300 alert rows).
    alert_rows = sampled_alert_rows()
    alert_en = [forecast(u, m, "en") for u, m in alert_rows]
    alert_bn = [forecast(u, m, "bn") for u, m in alert_rows]
    above = bad_min = 0
    for (u, m), f in zip(alert_rows, alert_en):
        raw_min = predict_and_explain(features_for(u, m))["predicted_min_balance"]
        above += raw_min >= cfg.SHORTFALL_FLOOR_BDT
        shown = f["predicted_min_balance"]
        bad_min += (raw_min >= cfg.SHORTFALL_FLOOR_BDT and shown is not None) or (
            shown is not None and shown["amount_bdt"] >= cfg.SHORTFALL_FLOOR_BDT)
    report(10, "alert with min balance at/above floor shows null", bad_min == 0,
           f"{len(alert_rows)} alerts, {above} at/above floor, bad {bad_min}")

    # 11. No reason (sampled responses and every reason template) claims a cause, in en or bn.
    reason_texts = [(r["text"], a["lang"]) for a in alert_en + alert_bn + [x for x in results if "reasons" in x]
                    for r in a["reasons"]]
    reason_texts += [(render(k, lang, value=1), lang) for k in messages.MESSAGES if k.startswith("reason_")
                     for lang in cfg.LANGUAGES]
    causal = sum(has_causal_word(text, lang) for text, lang in reason_texts)
    report(11, "no causal words in reasons (en and bn)", causal == 0, f"{len(reason_texts)} texts, {causal} bad")

    # 12. Buffer texts have no error sentence, and each buffer equals the rule worked out again by hand.
    amounts, bad_buffer12 = [], 0
    for (u, m), fe, fb in zip(alert_rows, alert_en, alert_bn):
        expected = expected_buffer(features_for(u, m))
        amounts.append(expected)
        for f in (fe, fb):
            buffers = [sg for sg in f["suggestions"] if sg["type"] == "buffer"]
            if expected == 0:  # No buffer: only the "balance is small" note.
                bad_buffer12 += bool(buffers) or not any(n["type"] == "no_buffer_low_balance" for n in f["notes"])
            else:
                bad_buffer12 += (len(buffers) != 1 or buffers[0]["amount_bdt"] != expected
                                 or has_error_sentence(buffers[0]["text"]) or "typical_error_bdt" in buffers[0])
    given = pd.Series([a for a in amounts if a > 0])
    report(12, "buffer = days-of-spend rule, no error sentence", bad_buffer12 == 0,
           f"{len(alert_rows)} alerts x 2 languages, bad {bad_buffer12}")
    print(f"   buffer BDT over {len(given)} alerts with a buffer: min {given.min()}, median {given.median():g}, "
          f"max {given.max()}; {len(amounts) - len(given)} with no buffer")

    # 13. English singular and plural for 0 and 1 (cash-outs, bills, days, months).
    def en_reason(feature, value):
        return reason_items(fake_reason(feature, value), "en")[0]["text"]
    singular_ok = ("made 1 cash-out." in en_reason("cashout_count_d1_20", 1)
                   and "made 0 cash-outs." in en_reason("cashout_count_d1_20", 0)
                   and "paid 1 bill." in en_reason("bill_payments_d1_20", 1)
                   and "paid 0 bills." in en_reason("bill_payments_d1_20", 0)
                   and "came in 1 day ago." in en_reason("days_since_last_inflow", 1)
                   and "for 1 month." in render("savings_option", "en", monthly=500, months=1)
                   and "for 11 months." in render("savings_option", "en", monthly=500, months=11)
                   and "for 21 months." in render("savings_option", "en", monthly=500, months=21))
    report(13, "singular and plural render for 0 and 1", singular_ok)

    # 14. days_since_last_inflow 20 means nothing came in yet; 0 means today (en and bn).
    def reason_text(value, lang):
        return reason_items(fake_reason("days_since_last_inflow", value), lang)[0]["text"]
    facts = messages._REASON_FACTS  # The fact sentences, to compare against.
    inflow_ok = (reason_text(20, "en").startswith("No money has come in so far this month.")
                 and reason_text(0, "en").startswith("Money came in today.")
                 and reason_text(20, "bn").startswith(facts["days_since_last_inflow_none"][1])
                 and reason_text(0, "bn").startswith(facts["days_since_last_inflow_today"][1])
                 and "20" not in reason_text(20, "en"))
    report(14, "no-inflow (20) and today (0) sentences render", inflow_ok)

    # 15. 200000 in Bangla is written with lakh grouping and still passes the check-8 number reader.
    plan_bn = {"goal_bdt": 200000, "months": 24, "monthly_bdt": 8334, "capacity_bdt": 9000,
               "text": render("savings_feasible", "bn", goal=200000, months=24, monthly=8334, capacity=9000)}
    lakh_ok = ("২,০০,০০০" in plan_bn["text"] and numbers_in_text(plan_bn) <= numbers_in_data(plan_bn)
               and "200,000" in render("savings_feasible", "en", goal=200000, months=24, monthly=8334, capacity=9000)
               and messages.format_value(12500, "bn") == "12,500")
    report(15, "bn 200000 renders as lakh grouping and passes check 8", lakh_ok)

    # 16. Capped buffers never claim "3 days"; uncapped ones always do; the flag matches the rule by hand.
    capped_n = uncapped_n = bad16 = 0
    for (u, m), fe, fb in zip(alert_rows, alert_en, alert_bn):
        wanted = expected_wanted(features_for(u, m))
        for f in (fe, fb):
            for sg in (x for x in f["suggestions"] if x["type"] == "buffer"):
                has_days = DAYS_WORDING[f["lang"]] in sg["text"]
                capped_n += sg["capped_by_balance"]
                uncapped_n += not sg["capped_by_balance"]
                bad16 += (has_days == sg["capped_by_balance"]  # Wording must follow the flag.
                          or sg["capped_by_balance"] != (sg["amount_bdt"] < wanted)  # Flag must follow the rule.
                          or "is_estimate" in sg)  # The buffer is a rule, not an estimate.
    report(16, "buffer '3 days' text only when not capped", bad16 == 0 and capped_n and uncapped_n,
           f"{capped_n} capped, {uncapped_n} uncapped texts, bad {bad16}")


if __name__ == "__main__":
    self_checks()
