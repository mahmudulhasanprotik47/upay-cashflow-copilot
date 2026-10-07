# upay Smart Cash-Flow Copilot

**Team:** TriStack
**Event:** AI Dev Fest 2026, AI Hackathon (DIU CPC × upay)
**Track:** Track 03, Customer Innovation & Financial Independence

## What it is

A prototype for the upay wallet. On day 20 of a month it predicts whether a
simulated wallet balance will drop below 500 BDT on days 21-30. It explains why
in English and বাংলা, then suggests a buffer, a cash-out fee saver and a
savings plan. These are suggestions only. The user decides. Nothing happens
automatically.

**All data is simulated. No real upay customer data is used.**

## What is inside

- A seeded data generator (1,000 simulated users, 6 months).
- An XGBoost model with SHAP reasons. The buffer, fee saver and savings plan
  are rules, not model output. Messages are fixed templates. There is no LLM.
- A FastAPI service and one self-contained web page with two tabs:
  Wallet, and Results (for judges, English only).
- 6 one-click demo cases and 23 self-checks.

### Added after the Phase 1 judging (all on simulated data)

- **Sign-in and roles**: admin, analyst, customer. Passwords are hashed with scrypt; sessions use
  HttpOnly cookies; API keys; rate limits; security headers; an audit log. An admin panel is at `/admin`.
- **SQLite storage** (`data/copilot.db`, not committed): accounts, consents, live transactions, budgets,
  feedback, logs.
- **Consent**: a customer accepts a data notice before any assessment, and can withdraw it, download their
  data or delete it.
- **Live transactions**: add one, and the month is rescored on this machine in milliseconds. Each
  transaction is validated, and the balance can never go below zero.
- **Budget bars** per spending type. These are a rule, not AI.
- **"Unusual for you" check** (IsolationForest). This is a pattern check, not fraud detection. On its own
  test it did not separate injected outliers (see `artifacts/anomaly/metrics.json`).
- **Numbered risk factors** RF-01..RF-11, with rank and strength 1-5, and numbered levels 1-3.
- **Model-driven target balance** (labelled "From the model") next to the rule-based buffer.
- **Feedback buttons** with a recorded A/B group. No cohort test has been run: see `docs/pilot_plan.md`.
- **Event bus**: an in-process queue for API-key batches (`/integration/events`). The upay adapter is a
  stub, because no real upay API was available.
- **Load test** (`scripts/load_test.py`), measured on one laptop.
- **Challenger experiment** (`python -m src.models.tune_challenger`). Verdict: not clearly better. The app
  still uses the shipped model.

## Honest results

On simulated data the model's lead over a simple day-20 balance rule is small
and not statistically clear. Its measurable extras are a minimum-balance
estimate and a reason for every alert. See the Results tab and
`docs/model_card.md`. The cash-out fee rate in the code (1.5%) is a placeholder.

## Quick start (Windows PowerShell)

Tested on Python 3.14.8. Other versions are untested.

```
git clone https://github.com/mahmudulhasanprotik47/upay-cashflow-copilot
cd upay-cashflow-copilot
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m src.data.generator
python -m src.api.service
python -m src.models.anomaly
$env:COPILOT_ADMIN_PASSWORD = "<at least 10 characters>"
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000/ in a browser.

- `python -m src.data.generator` creates the simulated data in `data/`.
- `python -m src.api.service` runs the 23 self-checks. All should pass.
- `python -m src.models.anomaly` trains the unusual-activity check (`artifacts/anomaly/`).
- The first start creates the admin account `admin` with the password from `COPILOT_ADMIN_PASSWORD`. If
  the variable is not set, a random password is printed once. The admin creates the other accounts in `/admin`.
- With the server running, in a window where the same variable is set: `python scripts/smoke_test.py`
  (wait a minute between runs). Run `python scripts/load_test.py` on a fresh server: it adds live rows to
  simulated users.
- Use months 4 and 5 for demos (months 0-3 were used for training).

## Docs

- `docs/model_card.md`: model, results, limits
- `docs/target_definition.md`: what "shortfall" means
- `docs/api_contract.md`: API responses
- `docs/synthetic_assumptions.md` and `docs/data_assumptions.md`: simulator assumptions
- `docs/security_privacy.md`: what is protected, and what is not done
- `docs/realtime_design.md`: how this would run at upay scale (what exists, what is design only)
- `docs/pilot_plan.md`: how a real cohort test would run (none has been run)
- `docs/survey_results.example.json`: the shape of user-research results. The Results tab shows
  `docs/survey_results.json` only if the team adds real collected answers.

## Team

- Mahmudul Hasan: build
- Fahim Montasir: research
- Ahsanur Rahman Nakib: slides and presentation