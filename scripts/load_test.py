# Load test against a RUNNING server, measured on one machine. All data is simulated.
# HTTP part: standard library only (urllib + threads). Batch timing: imports the installed model code.
# Needs COPILOT_ADMIN_PASSWORD in the environment. It adds live rows to unlinked simulated users, so run it
# against a test server (set COPILOT_DB_PATH to a throwaway file for that server) or press
# "Reset all live data" in the admin panel afterwards.
# Run: python scripts/load_test.py [--clients 8] [--requests 40]

import argparse  # Command-line options.
import concurrent.futures  # Concurrent clients.
import datetime  # Time of the run.
import http.cookiejar  # Session cookies.
import json  # Bodies and the result file.
import os  # Environment.
import platform  # Machine details.
import secrets  # Idempotency keys.
import statistics  # Percentiles.
import sys  # Import path and exit code.
import time  # Timing.
import urllib.error  # 4xx/5xx answers.
import urllib.request  # HTTP client.
from pathlib import Path  # Project folder.

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("COPILOT_URL", "http://127.0.0.1:8000").rstrip("/")


def opener():
    """A client with its own cookie jar."""
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(client, method, path, body=None, headers=None):
    """One request. Returns (status, parsed JSON or None, seconds)."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    start = time.perf_counter()
    try:
        with client.open(req, timeout=120) as resp:
            status, text = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read()
    seconds = time.perf_counter() - start
    try:
        return status, json.loads(text), seconds
    except ValueError:
        return status, None, seconds


def summarise(name, results, wall):
    """Requests per second and p50/p95/p99 of the successful requests; 429s counted on their own."""
    ok = sorted(s for status, s in results if status < 400)
    q = statistics.quantiles(ok, n=100) if len(ok) >= 2 else [ok[0] if ok else 0.0] * 99
    out = {"requests": len(results), "ok": len(ok), "rate_limited_429": sum(st == 429 for st, _ in results),
           "other_errors": sum(st >= 400 and st != 429 for st, _ in results),
           "requests_per_second": round(len(results) / wall, 1),
           "p50_ms": round(q[49] * 1000, 1), "p95_ms": round(q[94] * 1000, 1), "p99_ms": round(q[98] * 1000, 1)}
    print(f"{name}: {out['requests']} requests in {wall:.1f} s = {out['requests_per_second']} req/s; "
          f"p50 {out['p50_ms']} ms, p95 {out['p95_ms']} ms, p99 {out['p99_ms']} ms")
    print(f"{name}: 429 rate-limited {out['rate_limited_429']}, other errors {out['other_errors']}")
    return out


def run_clients(clients, per_client, fn):
    """Run fn(client_index, request_index) from `clients` threads. Returns (results, wall seconds)."""
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
        futures = [pool.submit(fn, c, i) for c in range(clients) for i in range(per_client)]
        results = [f.result() for f in futures]
    return results, time.perf_counter() - start


def batch_timing(rows_wanted=100_000):
    """Score a large table built by repeating the feature rows, with the saved model, in this process."""
    sys.path.insert(0, str(ROOT))
    import pandas as pd  # Installed with the project.
    from src.api import service  # Loads the simulated features.
    from src.models.predict import load_artifacts  # The saved model.
    features = service.state()["features"].astype(float)
    table = pd.concat([features] * (rows_wanted // len(features) + 1), ignore_index=True).iloc[:rows_wanted]
    clf, _, _ = load_artifacts()
    start = time.perf_counter()
    clf.predict_proba(table)  # Scores only; nothing is kept or shown.
    seconds = time.perf_counter() - start
    print(f"Batch score: {len(table)} rows in {seconds:.2f} s = {len(table) / seconds:,.0f} rows/s")
    return {"rows": len(table), "seconds": round(seconds, 3), "rows_per_second": round(len(table) / seconds)}


def main():
    """Forecast reads with an API key, live writes with admin sessions, one queued batch, and batch scoring."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--requests", type=int, default=40, help="requests per client")
    args = parser.parse_args()
    password = os.environ.get("COPILOT_ADMIN_PASSWORD")
    if not password:
        print("Set COPILOT_ADMIN_PASSWORD to the admin password in this window first.")
        return 2

    admin = opener()
    status, _, _ = call(admin, "POST", "/auth/login", {"username": os.environ.get("COPILOT_ADMIN_USER", "admin"),
                                                       "password": password})
    if status != 200:
        print(f"Admin sign-in failed ({status}).")
        return 1
    _, key, _ = call(admin, "POST", "/admin/api-keys", {"label": "load test"})
    headers = {"X-API-Key": key["key"]}
    _, accounts, _ = call(admin, "GET", "/admin/accounts")
    linked = {a["user_id"] for a in accounts if a["user_id"] is not None}
    _, users, _ = call(opener(), "GET", "/users", headers=headers)
    fixtures = [u["user_id"] for u in users if u["user_id"] not in linked]  # Unlinked simulated users only.
    report = {"simulated": True, "measured_on": "one laptop", "base_url": BASE,
              "when": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
              "machine": {"platform": platform.platform(), "processor": platform.processor(),
                          "cpu_count": os.cpu_count(), "python": platform.python_version()},
              "clients": args.clients, "requests_per_client": args.requests}

    # 1. Forecast reads with the API key (its higher rate limit).
    readers = [opener() for _ in range(args.clients)]
    def read(c, i):
        u = fixtures[(c * args.requests + i) % len(fixtures)]
        status, _, s = call(readers[c], "GET", f"/users/{u}/months/{4 + i % 2}/forecast", headers=headers)
        return status, s
    report["forecast"] = summarise("GET forecast (API key)", *run_clients(args.clients, args.requests, read))

    # 2. Live transactions: API keys may not add live data, so each writer is an admin session
    #    (sign-ins are limited to 10 a minute per address, so at most 4 writers).
    writers = []
    for _ in range(min(4, args.clients)):
        w = opener()
        call(w, "POST", "/auth/login", {"username": os.environ.get("COPILOT_ADMIN_USER", "admin"), "password": password})
        writers.append(w)
    def write(c, i):
        u = fixtures[(c * 7919 + i) % len(fixtures)]
        status, _, s = call(writers[c], "POST", "/live/transactions", {
            "user_id": u, "month": 4, "day": 5, "type": "add_money", "amount": 100,
            "idempotency_key": "load-" + secrets.token_hex(8)})
        return status, s
    report["live_transactions"] = summarise("POST live transaction (session)",
                                            *run_clients(len(writers), args.requests, write))

    # 3. One queued integration batch through the event bus, timed until the worker finishes.
    events = [{"user_id": fixtures[i % len(fixtures)], "month": 5, "day": 6, "type": "add_money", "amount": 100,
               "idempotency_key": "batch-" + secrets.token_hex(8)} for i in range(200)]
    start = time.perf_counter()
    status, accepted, _ = call(opener(), "POST", "/integration/events", {"events": events}, headers)
    state = {}
    while status == 202 and state.get("status") not in ("done", "failed") and time.perf_counter() - start < 600:
        time.sleep(0.5)
        _, state, _ = call(opener(), "GET", f"/integration/events/{accepted['batch_id']}", headers=headers)
    seconds = time.perf_counter() - start
    report["integration_batch"] = {"events": len(events), "status": state.get("status"),
                                   "accepted": state.get("accepted"), "rejected": state.get("rejected"),
                                   "seconds": round(seconds, 2), "events_per_second": round(len(events) / seconds, 1)}
    print(f"Integration batch: {len(events)} events {state.get('status')} in {seconds:.1f} s "
          f"({report['integration_batch']['events_per_second']} events/s)")

    call(admin, "POST", f"/admin/api-keys/{key['id']}/revoke", {})
    report["batch_score"] = batch_timing()
    path = ROOT / "artifacts" / "load_test.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {path.relative_to(ROOT)}. Live rows were added to simulated users: reset them in the admin panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
