# Public pages and aggregate results: the wallet page, the admin page, health, and the judges' results.
# /results is aggregate and simulated, so it stays public; /model-results carries internal values
# (calibration and the threshold), so it is for staff only. All data is simulated.

from fastapi import APIRouter, Depends  # Routing.

from src.api import deps, service  # Access rules; all the real work.
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
    """Trimmed results for the judges' tab plus the cached cash-out fee base (English only, public)."""
    return service.results()
