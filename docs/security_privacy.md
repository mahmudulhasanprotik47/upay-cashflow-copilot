# Security and privacy

All data in this prototype is simulated. This page lists what is protected and how, and what is not done.

## What is protected, and how

| Area | How |
|---|---|
| Passwords | Salted scrypt hashes only (`src/security/auth.py`), compared in constant time. An unknown username takes as long as a wrong password. |
| First admin | Password from the `COPILOT_ADMIN_PASSWORD` environment variable, or generated and printed once. Never written to a file. |
| Sign-in | 5 wrong passwords lock the account for 5 minutes. Sign-in is rate-limited per IP address. |
| Sessions | Random 32-byte token in an HttpOnly, SameSite=Strict cookie. Only its SHA-256 hash is stored. Expires after 8 hours; logout, a password reset, a role change or disabling ends it. |
| API keys | Shown once, stored as SHA-256, revocable, sent in `X-API-Key`. |
| Access | A customer reads and changes only their own `user_id`. An analyst reads but changes nothing. An admin does everything. Every staff or API-key view of a wallet is in the audit log. |
| Consent | A linked customer must accept the current notice before any assessment. Withdrawing it stops new assessments. Export (`GET /me/export`) and delete (`DELETE /me/data`) are self-service. |
| Requests | JSON only for request bodies (blocks cross-site form posts). Strict input checks. Errors never echo the input. Parameterised SQL only. |
| Rate limits | Sliding window per session, per API key and per IP address. A 429 answer carries `Retry-After`. |
| Headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on API answers. A Content-Security-Policy on the pages allows only each page's own script, by hash. |
| Suggestions | Every suggestion has `requires_user_confirmation: true` and `auto_action: false`. Nothing moves money. |

## What is NOT done (honest list)

- **No encryption at rest.** `data/copilot.db` is a plain SQLite file.
- **No HTTPS on localhost.** The session cookie has no `Secure` flag because the demo runs on plain HTTP.
- **Single process.** One database connection behind one lock. Not built for several servers.
- **In-memory rate limit.** Counters reset on restart and are not shared between processes.
- **Inline styles are allowed by the CSP** (`style-src 'unsafe-inline'`), because the pages use style attributes.
- **No multi-factor sign-in, no password-reset email, and no account deletion** (accounts can be disabled).
- **Audit log is not tamper-proof**: an admin with file access could edit it.
- **The pickled unusual-activity model** is loaded only from this project's own `artifacts/anomaly/` folder; a changed file there would run code.
- **No penetration test** has been done.
