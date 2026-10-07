# Risk factor register on top of an assessment: each reason gets its fixed code (RF-01..RF-11), its rank,
# whether it raises or lowers the risk, and a strength 1-5 from its share of the total absolute SHAP
# contribution of that prediction. The band gets a level number (1 low, 2 medium, 3 high). With an alert,
# the model-driven target balance is added next to the rule-based buffer. New fields only; old ones kept.
# No probability is ever added. All data is simulated.

import math  # Rounding the strength up.

from xgboost import DMatrix  # Full SHAP contribution vector.

from src.features.build_features import FEATURES  # The 11 model inputs, in order.
from src.i18n.messages import RISK_FACTORS  # Codes and names.
from src.models import target_balance  # Model-driven target balance.
from src.models.predict import load_artifacts, validate  # The saved model and its input checks.

LEVELS = {"low": 1, "medium": 2, "high": 3}  # Band -> level number.


def shap_vector(features):
    """All 11 SHAP contributions (log-odds) for one feature set, plus the bias, from the saved model."""
    clf, _, _ = load_artifacts()
    contribs = clf.get_booster().predict(DMatrix(validate(features)), pred_contribs=True)[0]
    return {f: float(c) for f, c in zip(FEATURES, contribs[:-1])}, float(contribs[-1])


def strength(value, total):
    """1-5: ceil(5 x |SHAP| / sum |SHAP|), kept within 1..5."""
    return max(1, min(5, math.ceil(5 * abs(value) / total))) if total > 0 else 1


def enrich(assessment, features, lang):
    """Add codes, ranks, effects, strengths, the level and the model target to one assessment (in place)."""
    vector, _ = shap_vector(features)
    total = sum(abs(v) for v in vector.values())
    order = sorted(vector, key=lambda f: -abs(vector[f]))  # Same order as the model's top reasons.
    for r in assessment["reasons"]:
        code, name_en, name_bn = RISK_FACTORS[r["feature"]]
        r.update(code=code, factor_name=name_en if lang == "en" else name_bn, rank=order.index(r["feature"]) + 1,
                 effect="raises_risk" if r["direction"] == "up" else "lowers_risk",
                 strength=strength(vector[r["feature"]], total))
    assessment["level"] = LEVELS[assessment["risk_band"]]
    assessment["model_target"] = target_balance.target_for(features, lang) if assessment["alert"] else None
    for s in assessment["suggestions"]:
        if s["type"] == "buffer":
            s["source"] = "rule"  # The buffer is a rule (days of the user's own spending), not the model.
    return assessment


def register(lang="en"):
    """The 11 factors with code and name, in FEATURES order (for the results tab)."""
    return [{"feature": f, "code": RISK_FACTORS[f][0], "name": RISK_FACTORS[f][1 if lang == "en" else 2]}
            for f in FEATURES]
