# One HTTP middleware for every request: work out who is calling (session cookie or X-API-Key),
# apply the rate limits, insist on JSON for request bodies, and add the security headers.
# Also serves the two HTML pages with a Content-Security-Policy that pins each page's inline script.

import base64  # CSP hashes are base64.
import hashlib  # SHA-256 of the inline script.
import re  # Finds the inline script in a page.
from pathlib import Path  # Page files.

from fastapi import Request  # The incoming request.
from fastapi.responses import HTMLResponse  # Page responses.

from src import config as cfg  # Rate limits, cookie name.
from src.api.deps import error_response  # Bilingual error body with a code.
from src.security import auth  # Session and API key lookups.
from src.security.ratelimit import LIMITER  # The shared rate limiter.

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"  # Folder of the HTML pages.
PAGE_PATHS = {"/", "/admin"}  # Responses that are pages, not API answers.
BODY_METHODS = {"POST", "PUT", "PATCH"}  # Methods whose body must be JSON.

# Headers on every response.
BASE_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}


def identify(request):
    """(principal or None, bad_key). A sent but unknown or revoked X-API-Key is reported as bad_key."""
    key = request.headers.get("x-api-key")
    if key is not None:
        p = auth.api_key_principal(key)
        return p, p is None
    return auth.session_principal(request.cookies.get(cfg.SESSION_COOKIE)), False


def rate_key(request, p):
    """The bucket and limit for this request: per API key, per session, or per IP address."""
    if p and p["kind"] == "api_key":
        return ("key", p["key_id"]), cfg.RATE_LIMIT_API_KEY
    if p:
        return ("session", auth.token_hash(request.cookies.get(cfg.SESSION_COOKIE, ""))), cfg.RATE_LIMIT_SESSION
    return ("ip", request.client.host if request.client else "?"), cfg.RATE_LIMIT_IP


async def security_middleware(request: Request, call_next):
    """Identify, rate-limit and check the request, then add the security headers to the answer.

    ponytail: the session and key lookups are short synchronous SQLite reads on the event loop;
    fine at demo load, move them to a thread if lookups ever show up in latency.
    """
    p, bad_key = identify(request)
    ip = request.client.host if request.client else "?"
    response = None
    if bad_key:
        response = error_response(401, "invalid_api_key")
    else:
        # Stricter limit on sign-in attempts per IP, then the normal per-caller limit.
        wait = LIMITER.hit(("login", ip), cfg.RATE_LIMIT_LOGIN, cfg.RATE_WINDOW_SECONDS) \
            if request.url.path == "/auth/login" else 0
        if not wait:
            key, limit = rate_key(request, p)
            wait = LIMITER.hit(key, limit, cfg.RATE_WINDOW_SECONDS)
        if wait:
            response = error_response(429, "rate_limited", headers={"Retry-After": str(wait)})
        elif request.method in BODY_METHODS and \
                request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            response = error_response(415, "json_required")  # Blocks plain HTML form posts from other sites.
    if response is None:
        request.state.principal = p
        response = await call_next(request)
    for name, value in BASE_HEADERS.items():
        response.headers[name] = value
    if request.url.path not in PAGE_PATHS:
        response.headers["Cache-Control"] = "no-store"  # API answers are never cached.
    return response


def page_response(filename):
    """Serve one HTML page with a CSP that allows only its own inline script (by SHA-256 hash).

    Inline styles stay allowed ('unsafe-inline' for style-src) because the pages use style attributes.
    The browser hashes the script text with line endings normalised to LF, so we do the same.
    """
    html = (FRONTEND / filename).read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(s.replace("\r\n", "\n").encode("utf-8"))
                                                    .digest()).decode("ascii") + "'" for s in scripts)
    csp = ("default-src 'none'; script-src " + (hashes or "'none'") + "; style-src 'unsafe-inline'; "
           "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; "
           "frame-ancestors 'none'")
    return HTMLResponse(html, headers={"Content-Security-Policy": csp, "Cache-Control": "no-cache"})
