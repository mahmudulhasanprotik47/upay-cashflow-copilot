# Inference: risk of a shortfall on days 21-30 for one user-month, with top reasons.
# Returns numbers only; the English/Bangla wording comes in Phase 3. All data is simulated.
# Run: python -m src.models.predict

import functools  # Caches the loaded models so they are read from disk once.
import json  # Reads threshold.json.
import math  # Checks for blank (NaN) and infinite numbers.
import numbers  # Checks that a value is a real number.

import numpy as np  # Number tools.
import pandas as pd  # Table tools.
from xgboost import DMatrix, XGBClassifier, XGBRegressor  # Saved model classes.

from src import config as cfg  # Central settings.
from src.features.build_features import BLANK_ALLOWED, FEATURES, build_features, load_data


@functools.lru_cache(maxsize=1)
def load_artifacts():
    """Load the classifier, the min-balance regressor and the threshold settings once."""
    clf = XGBClassifier()
    clf.load_model(cfg.ARTIFACTS_DIR / "liquidity_model.json")
    reg = XGBRegressor()
    reg.load_model(cfg.ARTIFACTS_DIR / "min_balance_model.json")
    info = json.loads((cfg.ARTIFACTS_DIR / "threshold.json").read_text(encoding="utf-8"))
    return clf, reg, info


def alert_threshold(info):
    """The config override if set, otherwise the threshold learned in training."""
    if cfg.ALERT_THRESHOLD_OVERRIDE is not None:
        return cfg.ALERT_THRESHOLD_OVERRIDE
    return info["learned_threshold"]


def is_blank(value):
    """True for None or NaN (a blank value)."""
    return value is None or (isinstance(value, float) and math.isnan(value))


def validate(features):
    """Check the input dict and turn it into a one-row table in the model's column order."""
    if not isinstance(features, dict):
        raise TypeError("features must be a dict")
    unknown = sorted(set(features) - set(FEATURES))  # Keys the model does not know.
    missing = sorted(set(FEATURES) - set(features))  # Keys the model needs.
    if unknown:
        raise ValueError(f"unknown feature keys: {unknown}")
    if missing:
        raise ValueError(f"missing feature keys: {missing}")
    row = {}
    for name in FEATURES:
        value = features[name]
        # Blank is only allowed where no complete previous month may exist.
        if is_blank(value) and name in BLANK_ALLOWED:
            row[name] = np.nan
            continue
        # Must be a real, finite number (True/False are not accepted as numbers).
        if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number, got {value!r}")
        row[name] = float(value)
    return pd.DataFrame([row], columns=FEATURES)


def top_reasons(clf, X, features):
    """The TOP_REASONS features that moved this prediction the most (log-odds contributions)."""
    contribs = clf.get_booster().predict(DMatrix(X), pred_contribs=True)[0, :-1]  # Drop bias.
    order = np.argsort(-np.abs(contribs), kind="stable")[:cfg.TOP_REASONS]  # Biggest effects first.
    return [{"feature": FEATURES[i],
             "value": None if is_blank(features[FEATURES[i]]) else float(features[FEATURES[i]]),
             "direction": "up" if contribs[i] > 0 else "down",  # "up" = raises the risk.
             "contribution": round(float(contribs[i]), 4)}
            for i in order]


def predict_and_explain(features: dict) -> dict:
    """Probability, alert, predicted minimum balance and top reasons for one user-month."""
    X = validate(features)
    clf, reg, info = load_artifacts()
    probability = float(clf.predict_proba(X)[0, 1])  # Chance of dipping below the floor.
    return {"probability": round(probability, 6),
            "alert": probability >= alert_threshold(info),
            "predicted_min_balance": int(round(float(reg.predict(X)[0]))),  # Helper model's lowest balance on days 21-30, BDT (not the buffer).
            "reasons": top_reasons(clf, X, features)}


def load_feature_row(user_id, month):
    """Build the feature dict for one user-month from the data files."""
    users, tx, bal = load_data()
    feat = build_features(users, tx, bal)
    row = feat[(feat["user_id"] == user_id) & (feat["month"] == month)]
    if row.empty:
        raise ValueError(f"no data for user {user_id}, month {month}")
    values = row.iloc[0][FEATURES]
    return {f: (None if pd.isna(v) else float(v)) for f, v in values.items()}


def main():
    """Explain one example (first test user) and check it matches test_predictions.csv."""
    saved = pd.read_csv(cfg.ARTIFACTS_DIR / "test_predictions.csv")
    first = saved.sort_values(["user_id", "month"]).iloc[0]  # First test user, earliest test month.
    user_id, month = int(first["user_id"]), int(first["month"])
    result = predict_and_explain(load_feature_row(user_id, month))
    print(f"User {user_id}, month {month}:")
    print(f"  probability {result['probability']:.6f}, alert {result['alert']}, "
          f"predicted_min_balance {result['predicted_min_balance']} BDT")
    for reason in result["reasons"]:
        print(f"  reason: {reason['feature']} = {reason['value']}, {reason['direction']}, "
              f"contribution {reason['contribution']:+.4f}")
    # Same numbers as the saved test prediction for this user-month?
    match = (abs(result["probability"] - first["probability"]) < 1e-6
             and int(result["alert"]) == int(first["alert"])
             and result["predicted_min_balance"] == int(first["predicted_min_balance"]))
    print(f"Matches test_predictions.csv: {match}")


if __name__ == "__main__":
    main()
