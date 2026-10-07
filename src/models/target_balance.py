# Model-driven target balance: for a user-month with an alert, the smallest day-20 balance at which the
# SAVED model stops alerting, with every other input held fixed. Valid because the model was trained with
# a monotone constraint: risk never goes up when balance_day20 goes up (train_liquidity.py). A reading of
# the model, not a cause and not a promise. All data is simulated.

import math  # Rounding up.

from src import config as cfg  # Search cap and rounding step.
from src.i18n.messages import render  # The sentence in English or Bangla.
from src.models.predict import alert_threshold, load_artifacts, validate  # The saved model and its threshold.
from src.rules.suggestions import as_suggestion  # Keeps requires_user_confirmation / auto_action flags.


def alerts(features, balance):
    """Would the saved model alert with balance_day20 set to this value (other inputs unchanged)?"""
    clf, _, info = load_artifacts()
    return float(clf.predict_proba(validate({**features, "balance_day20": float(balance)}))[0, 1]) >= alert_threshold(info)


def search(features):
    """Smallest whole-BDT balance_day20 in [current, WHATIF_MAX_BDT] with no alert, rounded up to
    BUFFER_ROUND_BDT. None if the model still alerts at WHATIF_MAX_BDT."""
    lo = max(0, math.ceil(features["balance_day20"]))
    hi = cfg.WHATIF_MAX_BDT
    if alerts(features, hi):
        return None  # No balance within the cap stops the alert.
    if not alerts(features, lo):
        hi = lo  # Already no alert at the current (rounded) balance.
    while hi - lo > 1:  # Invariant: alert at lo, no alert at hi.
        mid = (lo + hi) // 2
        if alerts(features, mid):
            lo = mid
        else:
            hi = mid
    step = cfg.BUFFER_ROUND_BDT
    return int(math.ceil(hi / step) * step)  # Rounding up keeps "no alert" (risk never rises with balance).


def target_for(features, lang):
    """The target as a suggestion-shaped dict labelled 'model', or None when no target exists."""
    amount = search(features)
    if amount is None:
        return None
    return as_suggestion("model_target_balance", amount_bdt=amount, source="model",
                         text=render("target_balance", lang, amount=amount))
