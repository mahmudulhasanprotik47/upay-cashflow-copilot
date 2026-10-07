# Public pages and aggregate results: the wallet page, the admin page, health, and the judges' results.
# /results is aggregate and simulated, so it stays public; /model-results carries internal values
# (calibration and the threshold), so it is for staff only. All data is simulated.

import json  # Reads the survey file.

from fastapi import APIRouter, Depends  # Routing.

from src import config as cfg  # Project folder.
from src.api import deps, service  # Access rules; all the real work.
from src.features.build_features import SPEND_TYPES  # Everyday spending types used by the model.
from src.live import risk_factors  # Risk factor register.
from src.rules.suggestions import SPEND_CATEGORIES  # Spending categories shown in the month summary.
from src.security.middleware import page_response  # Pages with their Content-Security-Policy.

router = APIRouter()


@router.get("/", include_in_schema=False)
def wallet_page():
    """The wallet screen: one self-contained HTML file, hidden from the API docs."""
    return page_response("index.html")


@router.get("/admin", include_in_schema=False)
def admin_page():
    """The admin panel: one self-contained HTML file. Its data calls need an admin or analyst session."""
    return page_response("admin.html")


@router.get("/health")
def health():
    """Is the server up, and how long did start-up take?"""
    return {"status": "ok", "startup_seconds": service.state()["startup_seconds"]}


@router.get("/model-results")
def model_results(_p=Depends(deps.staff)):
    """Metrics, fairness, global SHAP and the honest summary (staff only)."""
    return service.model_results()


@router.get("/results")
def results():
    """Trimmed results for the judges' tab plus the cached cash-out fee base (English only, public).
    Adds the risk factor register (codes and names); global importance is already in shap_global."""
    return {**service.results(), "risk_factors": risk_factors.register("en")}


def read_artifact(path):
    """A JSON artifact file, or None if it has not been made yet."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def without_thresholds(obj):
    """A copy with every key that holds a threshold or probability left out (nothing like that reaches a page)."""
    if isinstance(obj, dict):
        return {k: without_thresholds(v) for k, v in obj.items()
                if not any(w in k.lower() for w in ("threshold", "prob", "mean_pred"))}
    if isinstance(obj, list):
        return [without_thresholds(v) for v in obj]
    return obj


@router.get("/results/details")
def details():
    """Model details for the results tab, read from artifact files and code constants only (public, aggregate).
    Each part is null when its file does not exist yet. No probability or threshold is included."""
    metrics = service.state()["metrics"]
    challenger = read_artifact(cfg.CHALLENGER_DIR / "comparison.json")
    first_test = cfg.N_MONTHS - cfg.TEST_MONTHS
    return {
        "simulated": True,
        "inputs": risk_factors.register("en"),
        "split": {"train_months": list(range(first_test)), "test_months": list(range(first_test, cfg.N_MONTHS)),
                  "out_of_fold_rows": int(metrics["settings"]["oof_rows"]),
                  "how": "Alert setting chosen on out-of-fold predictions within the training months "
                         "(each of the last two training months predicted by a model fit on earlier months); "
                         "test months used once."},
        # Ten groups of test rows ordered by the model's score: row count and actual shortfall rate only.
        "groups": [{"group": i + 1, "rows": b["rows"], "actual_shortfall_rate": b["actual_rate"]}
                   for i, b in enumerate(metrics["calibration_bins"])],
        "spending_types": {"model_everyday_spend": SPEND_TYPES, "summary_categories": SPEND_CATEGORIES,
                           "budget_types": cfg.BUDGET_TYPES, "live_types": cfg.LIVE_TYPES},
        "anomaly": without_thresholds(read_artifact(cfg.ANOMALY_DIR / "metrics.json")),
        "confusion": challenger and challenger.get("shipped_confusion"),
        "challenger": without_thresholds(challenger),
        "load_test": read_artifact(cfg.LOAD_TEST_FILE),
    }


@router.get("/evidence")
def evidence():
    """User-research results from docs/survey_results.json if the team has added it; otherwise 404.
    The project never fills in survey numbers itself."""
    path = cfg.PROJECT_ROOT / "docs" / "survey_results.json"
    if not path.exists():
        raise deps.ApiError(404, "not_found")
    return json.loads(path.read_text(encoding="utf-8"))
