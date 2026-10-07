# Smoke test against a RUNNING server, standard library only (urllib, no TestClient). All data is simulated.
# Needs the first admin's password in the COPILOT_ADMIN_PASSWORD environment variable (never in a file).
# Creates a throwaway analyst and customer with random passwords held only in memory, and switches them
# off again at the end. The sign-in rate-limit test runs last; wait a minute before running it again.
# Run: python scripts/smoke_test.py      (optional: COPILOT_URL=http://127.0.0.1:8000)

import base64  # CSP hash format.
import hashlib  # Recomputes the page script hash.
import http.cookiejar  # Keeps each client's session cookie.
import json  # Request and response bodies.
import os  # Admin password and server URL from the environment.
import re  # Finds the inline script in a page.
import secrets  # Random throwaway usernames and passwords.
import sys  # Exit code.
import urllib.error  # 4xx/5xx answers.
import urllib.request  # HTTP client.

BASE = os.environ.get("COPILOT_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_USER = os.environ.get("COPILOT_ADMIN_USER", "admin")
RESULTS = []  # (passed, name, detail) for every check.

# Response fields the original endpoints had; they must all still be there.
OLD_FIELDS = {
    "forecast": {"user_id", "month", "lang", "month_in_training", "risk_band", "risk_band_text", "alert", "floor_bdt",
                 "predicted_min_balance", "reasons", "suggestions", "notes", "balance_by_day", "disclaimer"},
    "summary": {"user_id", "month", "lang", "total_spent_bdt", "by_category", "by_week", "biggest_week", "text",
                "disclaimer"},
    "savings": {"user_id", "month", "lang", "goal_bdt", "target_months", "max_months", "capacity_bdt", "plan",
                "options", "status", "text", "disclaimer"},
    "whatif": {"user_id", "month", "lang", "changed_inputs", "risk_change", "risk_change_text", "original", "whatif",
               "note", "disclaimer"},
    "results": {"simulated", "metrics", "fairness", "shap_global", "impact", "disclaimer"},
    "model_results": {"metrics", "fairness", "shap_global", "honest_summary", "disclaimer"},
    "health": {"status", "startup_seconds"},
    "users_item": {"user_id", "income_type"},
    "error": {"error", "error_bn"},
}


class Client:
    """One browser-like client with its own cookie jar."""

    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None, headers=None, raw=None, content_type="application/json"):
        """Send one request. Returns (status, headers, parsed JSON or text). Never raises on 4xx/5xx."""
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=dict(headers or {}))
        if data is not None:
            req.add_header("Content-Type", content_type)
        try:
            with self.opener.open(req, timeout=60) as resp:
                status, hdrs, text = resp.status, resp.headers, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            status, hdrs, text = e.code, e.headers, e.read().decode("utf-8")
        try:
            return status, hdrs, json.loads(text)
        except ValueError:
            return status, hdrs, text

    def login(self, username, password):
        """POST /auth/login; returns (status, headers, body)."""
        return self.call("POST", "/auth/login", {"username": username, "password": password})


def check(name, ok, detail=""):
    """Record and print one PASS/FAIL line (ASCII only)."""
    RESULTS.append((bool(ok), name, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" ({detail})" if detail and not ok else ""))


def code_of(body):
    """The error code in an error body, or None."""
    return body.get("code") if isinstance(body, dict) else None


def has_fields(body, kind):
    """True if a JSON object has every field the original endpoint had."""
    return isinstance(body, dict) and OLD_FIELDS[kind] <= set(body)


def page_checks(anon):
    """Both pages are public, carry a CSP, and the CSP hash matches the page's own inline script."""
    for path in ("/", "/admin"):
        status, hdrs, html = anon.call("GET", path)
        csp = hdrs.get("Content-Security-Policy", "")
        scripts = re.findall(r"<script>(.*?)</script>", html if isinstance(html, str) else "", flags=re.DOTALL)
        want = ["'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'" for s in scripts]
        check(f"page {path} served with CSP pinning its script", status == 200 and scripts and all(w in csp for w in want)
              and "frame-ancestors 'none'" in csp, csp[:80])


def main():
    """Run every check in order; exit 1 if any failed."""
    admin_pw = os.environ.get("COPILOT_ADMIN_PASSWORD")
    if not admin_pw:
        print("Set COPILOT_ADMIN_PASSWORD to the admin password in this window first.")
        return 2
    anon, admin, analyst, customer = Client(), Client(), Client(), Client()

    # Public endpoints, security headers, pages.
    status, hdrs, body = anon.call("GET", "/health")
    check("health is public and keeps its fields", status == 200 and has_fields(body, "health"))
    check("security headers on API answers", hdrs.get("X-Content-Type-Options") == "nosniff"
          and hdrs.get("X-Frame-Options") == "DENY" and hdrs.get("Referrer-Policy") == "no-referrer"
          and hdrs.get("Cache-Control") == "no-store")
    status, _, body = anon.call("GET", "/results")
    check("/results is public and keeps its fields", status == 200 and has_fields(body, "results"))
    page_checks(anon)

    # Signed out: wallet data needs a session or a key; bad keys are refused.
    status, _, body = anon.call("GET", "/users/1/months/4/forecast")
    check("signed out: forecast refused (401)", status == 401 and code_of(body) == "auth_required"
          and has_fields(body, "error"))
    status, _, body = anon.call("GET", "/users")
    check("signed out: /users refused (401)", status == 401)
    status, _, body = anon.call("GET", "/users/1/months/4/forecast", headers={"X-API-Key": "cfk_not_a_key"})
    check("wrong API key refused (401)", status == 401 and code_of(body) == "invalid_api_key")
    status, _, body = anon.call("POST", "/auth/login", raw=b"username=admin&password=x",
                                content_type="application/x-www-form-urlencoded")
    check("form-encoded POST refused (JSON only)", status == 415 and code_of(body) == "json_required")

    # Admin signs in; the cookie is HttpOnly and SameSite=Strict.
    status, hdrs, body = admin.login(ADMIN_USER, admin_pw)
    cookie = hdrs.get("Set-Cookie", "")
    check("admin signs in", status == 200 and body.get("role") == "admin", str(status))
    if status != 200:
        return finish()
    check("session cookie is HttpOnly and SameSite=Strict", "httponly" in cookie.lower()
          and "samesite=strict" in cookie.lower())

    # Throwaway analyst and customer (random names and passwords, kept in memory only).
    tag = secrets.token_hex(3)
    pw_analyst, pw_customer = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    _, _, accounts = admin.call("GET", "/admin/accounts")
    linked = {a["user_id"] for a in accounts if a["user_id"] is not None}
    _, _, users = admin.call("GET", "/users")
    check("/users items keep their fields", users and all(has_fields(u, "users_item") for u in users))
    free = [u["user_id"] for u in users if u["user_id"] not in linked]
    uid = free[len(free) // 2]  # A simulated user no other account is linked to.
    other = next(u for u in free if u != uid)
    status, _, a_body = admin.call("POST", "/admin/accounts", {"username": f"smoke_analyst_{tag}", "password": pw_analyst,
                                                                "role": "analyst"})
    status2, _, c_body = admin.call("POST", "/admin/accounts", {"username": f"smoke_customer_{tag}",
                                                                 "password": pw_customer, "role": "customer",
                                                                 "user_id": uid})
    check("admin creates an analyst and a linked customer", status == 200 and status2 == 200, f"{status} {status2}")
    status, _, body = admin.call("POST", "/admin/accounts", {"username": f"smoke_short_{tag}", "password": "short",
                                                              "role": "analyst"})
    check("short password refused", status == 422 and code_of(body) == "weak_password")

    # Wrong password, then the customer signs in and sees only their own wallet after consenting.
    status, _, body = customer.login(f"smoke_customer_{tag}", pw_customer + "x")
    check("wrong password rejected (401)", status == 401 and code_of(body) == "bad_credentials")
    status, _, me = customer.login(f"smoke_customer_{tag}", pw_customer)
    check("customer signs in", status == 200 and me.get("user_id") == uid)
    _, _, own = customer.call("GET", "/users")
    check("customer /users lists only their own id", [u["user_id"] for u in own] == [uid])
    status, _, body = customer.call("GET", f"/users/{uid}/months/4/forecast")
    check("no consent: own forecast refused (403 consent_required)", status == 403
          and code_of(body) == "consent_required")
    status, _, body = customer.call("POST", "/me/consent", {"notice_version": me["consent"]["notice_version"]})
    check("customer gives consent", status == 200 and body["consent"]["given"] is True)
    status, _, body = customer.call("GET", f"/users/{uid}/months/4/forecast?lang=bn")
    check("customer reads own forecast with the old fields", status == 200 and has_fields(body, "forecast"))
    status, _, body = customer.call("GET", f"/users/{other}/months/4/forecast")
    check("customer blocked from another wallet (403)", status == 403 and code_of(body) == "forbidden")
    status, _, _ = customer.call("POST", "/whatif", {"user_id": other, "month": 4, "overrides": {"balance_day20": 1000}})
    check("customer blocked from another user's what-if (403)", status == 403)
    status, _, _ = customer.call("GET", "/admin/monitoring")
    check("customer blocked from admin routes (403)", status == 403)

    # Analyst: reads wallets and monitoring, never admin-only routes.
    analyst.login(f"smoke_analyst_{tag}", pw_analyst)
    status, _, _ = analyst.call("GET", "/admin/accounts")
    check("analyst blocked from admin-only routes (403)", status == 403)
    status, _, _ = analyst.call("POST", "/admin/settings", {"key": "unusual_check", "on": False, "user_id": None})
    check("analyst cannot change switches (403)", status == 403)
    status, _, _ = analyst.call("GET", "/admin/monitoring")
    check("analyst reads monitoring", status == 200)
    status, _, body = analyst.call("GET", f"/users/{uid}/months/4/forecast")
    check("analyst reads a customer wallet", status == 200 and body.get("data_subject") == "linked_customer")

    # Every original endpoint keeps its fields (as admin).
    checks = [("forecast", "GET", "/users/8/months/4/forecast", None),
              ("summary", "GET", "/users/8/months/4/summary?lang=bn", None),
              ("savings", "POST", "/savings-plan", {"user_id": 19, "month": 4, "goal_bdt": 10000, "months": 6}),
              ("whatif", "POST", "/whatif", {"user_id": 8, "month": 4, "overrides": {"balance_day20": 5000}}),
              ("model_results", "GET", "/model-results", None)]
    for kind, method, path, body_in in checks:
        status, _, body = admin.call(method, path, body_in)
        check(f"old endpoint {path} keeps its fields", status == 200 and has_fields(body, kind), str(status))
    status, _, body = admin.call("GET", "/users/1/months/9/forecast")
    check("unknown month still 422/404 with the old error fields", status in (404, 422) and has_fields(body, "error"))

    # The analyst's view of the customer's wallet is in the audit log.
    _, _, log = admin.call("GET", f"/admin/audit?user_id={uid}")
    check("staff wallet view is audited", any(e["action"] == "view_forecast" and e["role"] == "analyst" for e in log))

    # API keys: shown once, work, then stop working when revoked.
    status, _, key = admin.call("POST", "/admin/api-keys", {"label": f"smoke {tag}"})
    status, _, _ = anon.call("GET", "/users/8/months/4/forecast", headers={"X-API-Key": key.get("key", "")})
    check("valid API key reads a wallet", status == 200)
    admin.call("POST", f"/admin/api-keys/{key.get('id')}/revoke", {})
    status, _, _ = anon.call("GET", "/users/8/months/4/forecast", headers={"X-API-Key": key.get("key", "")})
    check("revoked API key refused (401)", status == 401)
    _, _, listed = admin.call("GET", "/admin/api-keys")
    check("key list never shows the key", all("key" not in k for k in listed))

    live_checks(admin, analyst, customer, uid, other)

    # Sign-out ends the session.
    customer.call("POST", "/auth/logout", {})
    status, _, _ = customer.call("GET", "/auth/me")
    check("sign-out ends the session", status == 401)

    # Clean up: unlink and disable the throwaway accounts.
    _, _, accounts = admin.call("GET", "/admin/accounts")
    for a in accounts:
        if a["username"].endswith(tag):
            admin.call("POST", f"/admin/accounts/{a['id']}", {"disabled": True, "user_id": None})

    # Rate limit last: repeated sign-ins from one address end in 429 with Retry-After.
    got = None
    for _ in range(40):
        status, hdrs, body = anon.login(f"nobody_{tag}", "wrong-password")
        if status == 429:
            got = hdrs.get("Retry-After")
            break
    check("sign-in rate limit answers 429 with Retry-After", got is not None and int(got) > 0)
    return finish()


def keys_in(obj):
    """Every key anywhere in a nested JSON value."""
    if isinstance(obj, dict):
        return set(obj) | set().union(*(keys_in(v) for v in obj.values())) if obj else set()
    if isinstance(obj, list):
        return set().union(*(keys_in(v) for v in obj)) if obj else set()
    return set()


def live_checks(admin, analyst, customer, uid, other):
    """Live transactions, budgets, switches, monitoring and reset (Phase B)."""
    tag = secrets.token_hex(4)
    tx = lambda **kw: {"user_id": uid, "month": 4, "day": 5, "type": "add_money", "amount": 500,  # noqa: E731
                       "idempotency_key": f"{tag}-{secrets.token_hex(4)}", **kw}
    _, _, before = customer.call("GET", f"/users/{uid}/months/4/forecast")
    first = tx()
    status, _, body = customer.call("POST", "/live/transactions", first)
    ok = status == 200 and has_fields(body.get("assessment"), "forecast") and isinstance(body.get("ms"), (int, float))
    check("customer adds a live transaction; new assessment comes back", ok, str(status))
    if not ok:
        return
    check("live answer has changed, budgets and unusual parts", {"band_before", "band_after", "balance_day20_before",
          "balance_day20_after", "reasons_added", "reasons_removed"} <= set(body["changed"])
          and len(body["budgets"]["bars"]) == 5 and "enabled" in body["unusual"])
    check("live answer carries no probability", not any("prob" in k for k in keys_in(body)))
    check("day-20 balance moved by the amount", body["changed"]["balance_day20_after"]
          - body["changed"]["balance_day20_before"] == 500)
    _, _, again = customer.call("GET", f"/users/{uid}/months/4/forecast")
    check("forecast reload shows the live balance", again["balance_by_day"][-1]["balance_bdt"]
          == body["changed"]["balance_day20_after"])
    rejects = [("duplicate key", first, 409, "duplicate"),
               ("unknown type", tx(type="gift"), 422, "unknown_type"),
               ("day after 20", tx(day=21), 422, "day_after_prediction_day"),
               ("amount zero", tx(amount=0), 422, "amount_out_of_range"),
               ("more than the balance", tx(type="merchant_payment", amount=200000), 422, "insufficient_balance")]
    for name, payload, want_status, want_code in rejects:
        status, _, b = customer.call("POST", "/live/transactions", payload)
        check(f"live rejected: {name} ({want_code})", status == want_status and code_of(b) == want_code,
              f"{status} {code_of(b)}")
    status, _, _ = customer.call("POST", "/live/transactions", tx(user_id=other))
    check("customer cannot add to another wallet (403)", status == 403)
    status, _, _ = analyst.call("POST", "/live/transactions", tx())
    check("analyst cannot add live transactions (403)", status == 403)

    # Budgets: read, set your own, analyst cannot set.
    status, _, b = customer.call("GET", f"/users/{uid}/budgets?month=4")
    check("budget bars for own wallet (labelled a rule)", status == 200 and b.get("is_rule") is True
          and len(b["bars"]) == 5)
    status, _, _ = customer.call("PUT", f"/users/{uid}/budgets", {"budgets": {"merchant_payment": 1000}})
    _, _, b = customer.call("GET", f"/users/{uid}/budgets?month=4")
    mp = next(x for x in b["bars"] if x["type"] == "merchant_payment")
    check("customer sets own budget", status == 200 and mp["budget_bdt"] == 1000 and mp["budget_source"] == "yours")
    status, _, _ = analyst.call("PUT", f"/users/{uid}/budgets", {"budgets": {"merchant_payment": 5}})
    check("analyst cannot set budgets (403)", status == 403)

    # Feature switch for one user.
    admin.call("POST", "/admin/settings", {"key": "live_transactions", "on": False, "user_id": uid})
    status, _, b = customer.call("POST", "/live/transactions", tx())
    check("live switched off for this user (403 feature_disabled)", status == 403 and code_of(b) == "feature_disabled")
    admin.call("POST", "/admin/settings", {"key": "live_transactions", "on": None, "user_id": uid})

    # Monitoring counts the live work; reset brings back the simulated month.
    _, _, mon = admin.call("GET", "/admin/monitoring")
    check("monitoring counts scored and rejected live transactions", mon.get("live_processed", 0) >= 1
          and mon.get("rejected_by_code", {}).get("duplicate", 0) >= 1 and mon.get("median_scoring_ms") is not None)
    status, _, b = customer.call("DELETE", "/me/live")
    _, _, after = customer.call("GET", f"/users/{uid}/months/4/forecast")
    check("reset my live data restores the simulated month", status == 200 and b.get("deleted", 0) >= 1
          and after["balance_by_day"] == before["balance_by_day"])
    customer.call("PUT", f"/users/{uid}/budgets", {"budgets": {"merchant_payment": None}})


def finish():
    """Print the total and return the exit code."""
    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
